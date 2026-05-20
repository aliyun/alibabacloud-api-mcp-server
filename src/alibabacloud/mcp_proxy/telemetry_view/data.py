from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable


@dataclass
class SessionMeta:
    client: str
    session_id: str
    file_path: Path
    file_offset: int = 0
    start_time: str = ""
    last_activity: str = ""
    first_prompt_preview: str = ""
    span_count: int = 0
    turn_count: int = 0
    has_errors: bool = False


def resolve_data_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_dir = os.environ.get("ALIBABACLOUD_TELEMETRY_STATE_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    dirs.append(Path.home() / ".cache" / "alibabacloud-agent-toolkit" / "telemetry")
    uid = os.getuid() if hasattr(os, "getuid") else 0
    dirs.append(Path(f"/tmp/alibabacloud-agent-toolkit-telemetry-{uid}"))
    return [d for d in dirs if d.exists()]


def parse_jsonl_file(file_path: Path, offset: int = 0) -> list[dict[str, Any]]:
    raw_events: list[dict[str, Any]] = []
    with open(file_path, "r", encoding="utf-8") as f:
        if offset:
            f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw_events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return _merge_tool_spans(raw_events)


def _merge_tool_spans(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_starts: dict[str, dict[str, Any]] = {}
    merged: list[dict[str, Any]] = []

    for ev in events:
        event_type = ev.get("event")
        if event_type == "tool_start":
            tool_starts[ev["span_id"]] = ev
        elif event_type == "tool_end":
            span_id = ev["span_id"]
            start_ev = tool_starts.pop(span_id, None)
            merged_span: dict[str, Any] = {
                "span_id": span_id,
                "parent_span_id": ev.get("parent_span_id"),
                "event": "tool",
                "turn": ev.get("turn"),
                "session_id": ev.get("session_id"),
                "client": ev.get("client"),
                "tool_name": ev.get("tool_name"),
                "tool_use_id": ev.get("tool_use_id"),
                "start_timestamp": start_ev["start_timestamp"] if start_ev else ev.get("start_timestamp"),
                "end_timestamp": ev.get("end_timestamp"),
                "duration_ms": ev.get("duration_ms"),
                "status": ev.get("status"),
                "error_message": ev.get("error_message"),
                "request_id": ev.get("request_id"),
                "tool_input": start_ev.get("tool_input") if start_ev else None,
                "tool_response": ev.get("tool_response"),
                "truncated": ev.get("truncated", False),
            }
            merged.append(merged_span)
        else:
            merged.append(ev)

    # Orphaned tool_starts (no matching tool_end yet)
    for span_id, start_ev in tool_starts.items():
        merged.append({
            **start_ev,
            "event": "tool",
            "status": "pending",
            "duration_ms": None,
            "tool_response": None,
            "truncated": False,
            "error_message": None,
            "request_id": None,
        })

    return merged


def build_session_index(data_dirs: list[Path]) -> dict[tuple[str, str], SessionMeta]:
    index: dict[tuple[str, str], SessionMeta] = {}

    for base_dir in data_dirs:
        if not base_dir.exists():
            continue
        for client_dir in base_dir.iterdir():
            if not client_dir.is_dir():
                continue
            traces_dir = client_dir / "traces"
            if not traces_dir.exists():
                continue
            client = client_dir.name
            for jsonl_file in traces_dir.glob("*.jsonl"):
                spans = parse_jsonl_file(jsonl_file)
                if not spans:
                    continue
                session_id = _extract_session_id(spans, jsonl_file)
                meta = _build_meta(client, session_id, jsonl_file, spans)
                index[(client, session_id)] = meta

    return index


def _extract_session_id(spans: list[dict[str, Any]], file_path: Path) -> str:
    for span in spans:
        sid = span.get("session_id")
        if sid:
            return sid
    return file_path.stem


def _build_meta(
    client: str,
    session_id: str,
    file_path: Path,
    spans: list[dict[str, Any]],
) -> SessionMeta:
    timestamps: list[str] = []
    prompt_preview = ""
    turn_numbers: set[int] = set()
    has_errors = False

    for span in spans:
        ts = span.get("start_timestamp", "")
        te = span.get("end_timestamp", "")
        if ts:
            timestamps.append(ts)
        if te:
            timestamps.append(te)

        turn = span.get("turn")
        if turn is not None:
            turn_numbers.add(turn)

        if span.get("event") == "prompt" and not prompt_preview:
            raw = span.get("prompt", "")
            prompt_preview = raw[:80] if raw else ""

        if span.get("status") == "failure" or span.get("stop_reason") == "StopFailure":
            has_errors = True

    timestamps.sort()
    file_size = file_path.stat().st_size

    return SessionMeta(
        client=client,
        session_id=session_id,
        file_path=file_path,
        file_offset=file_size,
        start_time=timestamps[0] if timestamps else "",
        last_activity=timestamps[-1] if timestamps else "",
        first_prompt_preview=prompt_preview,
        span_count=len(spans),
        turn_count=len(turn_numbers),
        has_errors=has_errors,
    )


def build_span_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []

    for span in spans:
        span_copy = {**span, "children": []}
        by_id[span["span_id"]] = span_copy

    for span in spans:
        node = by_id[span["span_id"]]
        parent_id = span.get("parent_span_id")
        if parent_id is None:
            roots.append(node)
        elif parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)

    def sort_children(node: dict[str, Any]) -> None:
        node["children"].sort(key=lambda c: c.get("start_timestamp", ""))
        for child in node["children"]:
            sort_children(child)

    for root in roots:
        sort_children(root)
    roots.sort(key=lambda r: r.get("start_timestamp", ""))
    return roots


class TraceFileWatcher:
    def __init__(
        self,
        index: dict[tuple[str, str], SessionMeta],
        data_dirs: list[Path],
        on_change: Callable[[str, dict[str, Any]], Awaitable[None]],
        poll_interval: float = 2.0,
    ) -> None:
        self._index = index
        self._data_dirs = data_dirs
        self._on_change = on_change
        self._poll_interval = poll_interval
        self._known_files: set[Path] = {meta.file_path for meta in index.values()}

    async def run(self) -> None:
        while True:
            await self._check_existing_files()
            await self._check_new_files()
            await asyncio.sleep(self._poll_interval)

    async def _check_existing_files(self) -> None:
        for key, meta in list(self._index.items()):
            if not meta.file_path.exists():
                continue
            current_size = meta.file_path.stat().st_size
            if current_size <= meta.file_offset:
                continue
            new_spans = parse_jsonl_file(meta.file_path, offset=meta.file_offset)
            if not new_spans:
                meta.file_offset = current_size
                continue
            self._update_meta(meta, new_spans, current_size)
            await self._on_change("session_updated", {
                "client": meta.client,
                "session_id": meta.session_id,
                "last_activity": meta.last_activity,
                "span_count": meta.span_count,
                "new_spans": new_spans,
            })

    async def _check_new_files(self) -> None:
        for base_dir in self._data_dirs:
            if not base_dir.exists():
                continue
            for client_dir in base_dir.iterdir():
                if not client_dir.is_dir():
                    continue
                traces_dir = client_dir / "traces"
                if not traces_dir.exists():
                    continue
                for jsonl_file in traces_dir.glob("*.jsonl"):
                    if jsonl_file in self._known_files:
                        continue
                    self._known_files.add(jsonl_file)
                    spans = parse_jsonl_file(jsonl_file)
                    if not spans:
                        continue
                    client = client_dir.name
                    session_id = _extract_session_id(spans, jsonl_file)
                    meta = _build_meta(client, session_id, jsonl_file, spans)
                    self._index[(client, session_id)] = meta
                    await self._on_change("session_updated", {
                        "client": meta.client,
                        "session_id": meta.session_id,
                        "last_activity": meta.last_activity,
                        "span_count": meta.span_count,
                        "new_spans": spans,
                    })

    def _update_meta(self, meta: SessionMeta, new_spans: list[dict[str, Any]], new_offset: int) -> None:
        meta.file_offset = new_offset
        meta.span_count += len(new_spans)

        for span in new_spans:
            ts = span.get("end_timestamp") or span.get("start_timestamp", "")
            if ts and ts > meta.last_activity:
                meta.last_activity = ts

            turn = span.get("turn")
            if turn is not None:
                expected_turns = turn + 1
                if expected_turns > meta.turn_count:
                    meta.turn_count = expected_turns

            if span.get("status") == "failure" or span.get("stop_reason") == "StopFailure":
                meta.has_errors = True
