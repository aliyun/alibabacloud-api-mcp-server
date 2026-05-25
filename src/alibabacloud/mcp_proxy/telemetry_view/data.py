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


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except (FileNotFoundError, OSError):
        return None


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


# ---------------------------------------------------------------------------
# Token layers
# ---------------------------------------------------------------------------
#
# The producer hook emits per-turn `turn_end` events carrying three Layer 1
# (strict, high-confidence) fields:
#
#   * ``turn_tokens``            — sum of LLM token usage rows that belong to
#                                  this turn.
#   * ``aliyun_session_tokens``  — cumulative running total across traced
#                                  turns (already accumulated by the producer).
#   * ``tool_tokens``            — per-tool-span breakdown, keyed by span_id.
#
# The viewer reconstructs Layer 2 (estimated skill attribution) itself by
# walking each tool's parent chain to find the nearest ``skill_invocation``
# ancestor. The confidence label reflects how confidently those tools can be
# attributed to a single skill:
#
#   * ``high``   — turn contains exactly one skill and (almost) no extra
#                  noise; assume every tool ran inside that skill.
#   * ``medium`` — turn contains 2-3 skills in a clean sequence; attribution
#                  follows the parent chain but order matters.
#   * ``low``    — many skills, or skills mixed with non-skill bash; the
#                  attribution is best-effort.
#
# Keeping the heuristic on the viewer means we can iterate on it without
# rewriting historical trace files.

_TOKEN_KEYS = (
    "input_uncached",
    "input_cached",
    "input_creation",
    "output",
    "reasoning",
)


def _empty_tokens() -> dict[str, int]:
    return {k: 0 for k in _TOKEN_KEYS}


def _add_tokens(a: dict[str, Any], b: dict[str, Any]) -> dict[str, int]:
    out = _empty_tokens()
    for k in _TOKEN_KEYS:
        out[k] = int((a or {}).get(k) or 0) + int((b or {}).get(k) or 0)
    return out


def _grand_total(tokens: dict[str, Any]) -> int:
    return sum(int((tokens or {}).get(k) or 0) for k in _TOKEN_KEYS)


def _confidence_for_turn(skill_count: int, non_skill_tool_count: int) -> tuple[str, float]:
    """Return ``(label, numeric_value)`` for skill-attribution confidence.

    The heuristic mirrors the user-facing description:
      * one skill, little noise          → high (0.9)
      * two-to-three skills, sequential   → medium (0.6)
      * many skills, or mixed with bash   → low (0.3)
    """
    if skill_count == 0:
        return ("high", 1.0)
    if skill_count == 1:
        # Single skill: even some surrounding bash is fine — anything in the
        # turn is most likely related to that skill.
        return ("high", 0.9)
    if skill_count <= 3 and non_skill_tool_count == 0:
        return ("medium", 0.6)
    return ("low", 0.3)


def _walk_skill_ancestor(
    span_id: str,
    parent_of: dict[str, str | None],
    skill_set: set[str],
) -> str:
    """Walk parent chain until we hit a skill_invocation span, or root.

    Codex bash-as-skill detail: the synthesized skill_invocation event lives
    at id ``<bash_id>.skill`` (sibling-or-child of the bash). Inner bashes
    nested by Codex report ``parent_span_id == <bash_id>`` (the bash), not
    the synthesized skill. So at each hop, also probe the ``.skill`` variant
    of the current id — that lets attribution find the skill even though
    it is not literally on the parent chain.
    """
    seen: set[str] = set()
    cur: str | None = span_id
    while cur and cur not in seen:
        seen.add(cur)
        if cur in skill_set:
            return cur
        skill_variant = cur + ".skill"
        if skill_variant in skill_set:
            return skill_variant
        cur = parent_of.get(cur)
    return ""


def compute_token_layers(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute Layer 1 strict + Layer 2 estimated token attribution.

    Input is the flat span list (output of ``parse_jsonl_file``), not the
    tree — we need the parent_span_id pointers regardless of nesting.

    Returns a JSON-serialisable dict with shape::

        {
          "session_total": {tokens..., "grand_total": int},
          "turns": [
            {
              "turn": int,
              "turn_tokens": {tokens..., "grand_total": int},
              "confidence_level": "high"|"medium"|"low",
              "confidence_value": float,
              "skill_count": int,
              "non_skill_tool_count": int,
              "skills": [
                {"span_id", "skill_name", "estimated_tokens": {tokens..., "grand_total"}}
              ],
              "tools": [
                {"span_id", "tool_name", "tokens": {tokens..., "grand_total"}}
              ]
            },
            ...
          ]
        }
    """
    if not spans:
        return {"session_total": {**_empty_tokens(), "grand_total": 0}, "turns": []}

    parent_of: dict[str, str | None] = {}
    skills_in_turn: dict[int, list[dict[str, Any]]] = {}
    tools_in_turn: dict[int, list[dict[str, Any]]] = {}
    prompts_in_turn: dict[int, list[str]] = {}
    turn_end_by_turn: dict[int, dict[str, Any]] = {}

    for span in spans:
        sid = span.get("span_id")
        if not sid:
            continue
        parent_of[sid] = span.get("parent_span_id")
        event = span.get("event")
        turn = span.get("turn")
        if turn is None:
            continue
        turn = int(turn)
        if event == "skill_invocation":
            skills_in_turn.setdefault(turn, []).append(span)
        elif event == "tool":
            tools_in_turn.setdefault(turn, []).append(span)
        elif event == "prompt":
            prompts_in_turn.setdefault(turn, []).append(sid)
        elif event == "turn_end":
            # Keep the last turn_end if the producer ever emits duplicates.
            turn_end_by_turn[turn] = span

    # Session total: prefer the most recent aliyun_session_tokens (it's
    # already cumulative); fall back to summing turn_tokens.
    last_turn = max(turn_end_by_turn) if turn_end_by_turn else None
    if last_turn is not None:
        session_tokens = dict(turn_end_by_turn[last_turn].get("aliyun_session_tokens") or {})
    else:
        session_tokens = _empty_tokens()
        for te in turn_end_by_turn.values():
            session_tokens = _add_tokens(session_tokens, te.get("turn_tokens") or {})
    session_total = {**_empty_tokens(), **{k: int(session_tokens.get(k) or 0) for k in _TOKEN_KEYS}}
    session_total["grand_total"] = _grand_total(session_total)

    turns_out: list[dict[str, Any]] = []
    all_turns = sorted(
        set(turn_end_by_turn)
        | set(skills_in_turn)
        | set(tools_in_turn)
        | set(prompts_in_turn)
    )
    for turn in all_turns:
        te = turn_end_by_turn.get(turn) or {}
        turn_tokens_raw = te.get("turn_tokens") or {}
        tool_tokens_map = te.get("tool_tokens") or {}

        skill_spans = skills_in_turn.get(turn, [])
        tool_spans = tools_in_turn.get(turn, [])
        skill_set = {s["span_id"] for s in skill_spans if s.get("span_id")}

        # Per-skill attribution: walk each tool's parent chain to its
        # nearest skill ancestor and accumulate the tool's tokens there.
        # Skip Codex outer-bash tools that pair with a `.skill` companion —
        # those bashes are folded into the skill display node, so counting
        # their own llm_tokens in the skill estimate would double-count
        # "the message that invoked the skill" and break the invariant
        # `skill_est == Σ(visible children)` that Claude already satisfies.
        skill_tokens: dict[str, dict[str, int]] = {sid: _empty_tokens() for sid in skill_set}
        non_skill_tool_count = 0
        tools_out: list[dict[str, Any]] = []
        for tool in tool_spans:
            sid = tool.get("span_id")
            # Codex outer-bash that pairs with a `.skill` companion is folded
            # into the skill display node — drop it from tools_out so the
            # frontend's attributed-token count matches the visible tree.
            # Its llm_tokens (the "message that invoked the skill" cost) then
            # surface in the prompt's Un-attributed breakdown.
            if sid and (sid + ".skill") in skill_set:
                continue
            entry = tool_tokens_map.get(sid) if sid else None
            tokens = dict((entry or {}).get("llm_tokens") or {})
            normalised = {k: int(tokens.get(k) or 0) for k in _TOKEN_KEYS}
            grand = sum(normalised.values())
            tools_out.append({
                "span_id": sid,
                "tool_name": tool.get("tool_name") or "",
                "tokens": {**normalised, "grand_total": grand},
            })
            if grand <= 0:
                if sid:
                    anc = _walk_skill_ancestor(sid, parent_of, skill_set)
                    if not anc:
                        non_skill_tool_count += 1
                continue
            anc = _walk_skill_ancestor(sid, parent_of, skill_set) if sid else ""
            if anc:
                skill_tokens[anc] = _add_tokens(skill_tokens[anc], normalised)
            else:
                non_skill_tool_count += 1

        confidence_level, confidence_value = _confidence_for_turn(
            len(skill_set), non_skill_tool_count
        )

        skills_out: list[dict[str, Any]] = []
        for skill in skill_spans:
            sid = skill.get("span_id")
            tokens = skill_tokens.get(sid, _empty_tokens())
            grand = sum(tokens.values())
            skills_out.append({
                "span_id": sid,
                "skill_name": skill.get("skill_name") or "",
                "estimated_tokens": {**tokens, "grand_total": grand},
            })

        normalised_turn = {k: int(turn_tokens_raw.get(k) or 0) for k in _TOKEN_KEYS}
        turn_tokens_out = {
            **normalised_turn,
            "grand_total": sum(normalised_turn.values()),
        }

        turns_out.append({
            "turn": turn,
            "turn_end_span_id": te.get("span_id") if te else None,
            "prompt_span_ids": list(prompts_in_turn.get(turn, [])),
            "turn_tokens": turn_tokens_out,
            "confidence_level": confidence_level,
            "confidence_value": confidence_value,
            "skill_count": len(skill_set),
            "non_skill_tool_count": non_skill_tool_count,
            "skills": skills_out,
            "tools": tools_out,
        })

    return {"session_total": session_total, "turns": turns_out}


def _collapse_codex_bash_skill_pairs(roots: list[dict[str, Any]]) -> None:
    """Codex bash-as-skill: merge a Bash tool with its matching `.skill`
    companion into a single skill node.

    Codex reports each `bash <SKILL.sh>` invocation as a Bash tool call. The
    producer hook synthesises a sibling/child skill_invocation event with id
    ``<bash_id>.skill`` so the lightning icon shows up. The user only cares
    about the skill — the outer bash is mechanical noise. Collapse them:

      Before:
        Bash <bash_id>
          [Skill <bash_id>.skill]   (child in new traces)
          inner Bash 1              (Codex reports parent=<bash_id>)
          inner Bash 2
        Skill <bash_id>.skill        (sibling in old traces)

      After:
        Skill <bash_id>              (display fields promoted, bash id kept)
          inner Bash 1
          inner Bash 2

    The bash's span_id is kept so the viewer's per-tool token data still
    resolves. ``buildTokenIndex`` aliases ``<bash_id>`` to the skill entry
    so clicks land on the skill's attributed-tokens panel.
    """
    skill_by_bash_id: dict[str, dict[str, Any]] = {}
    pseudo_root = {"children": list(roots)}

    def collect(node: dict[str, Any]) -> None:
        for child in node.get("children") or []:
            sid = child.get("span_id") or ""
            if child.get("event") == "skill_invocation" and sid.endswith(".skill"):
                skill_by_bash_id[sid[:-len(".skill")]] = child
            collect(child)
    collect(pseudo_root)

    if not skill_by_bash_id:
        return

    to_remove: set[int] = set()

    def promote(node: dict[str, Any]) -> None:
        if node.get("event") == "tool" and node.get("tool_name") == "Bash":
            skill = skill_by_bash_id.get(node.get("span_id"))
            if skill is not None and id(skill) not in to_remove:
                node["event"] = "skill_invocation"
                node["tool_name"] = "Skill"
                node["skill_name"] = skill.get("skill_name", "")
                node["plugin_name"] = skill.get("plugin_name", "")
                node["_collapsed_from_bash"] = True
                to_remove.add(id(skill))
        for child in node.get("children") or []:
            promote(child)
    promote(pseudo_root)

    def prune(node: dict[str, Any]) -> None:
        kids = node.get("children") or []
        node["children"] = [c for c in kids if id(c) not in to_remove]
        for child in node["children"]:
            prune(child)
    prune(pseudo_root)

    roots[:] = pseudo_root["children"]


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
    _collapse_codex_bash_skill_pairs(roots)
    return roots


class TraceFileWatcher:
    def __init__(
        self,
        index: dict[tuple[str, str], SessionMeta],
        data_dirs: list[Path],
        on_change: Callable[[str, dict[str, Any]], Awaitable[None]],
        poll_interval: float = 5.0,
    ) -> None:
        self._index = index
        self._data_dirs = data_dirs
        self._on_change = on_change
        self._poll_interval = poll_interval
        self._known_files: set[Path] = {meta.file_path for meta in index.values()}
        # last-seen mtime per session to skip parse when nothing changed
        self._last_mtime: dict[Path, int] = {}

    async def run(self) -> None:
        while True:
            await self._check_existing_files()
            await self._check_new_files()
            await asyncio.sleep(self._poll_interval)

    async def _check_existing_files(self) -> None:
        for key, meta in list(self._index.items()):
            stat_result = await asyncio.to_thread(_safe_stat, meta.file_path)
            if stat_result is None:
                continue
            current_size = stat_result.st_size
            current_mtime_ns = stat_result.st_mtime_ns
            if self._last_mtime.get(meta.file_path) == current_mtime_ns and current_size <= meta.file_offset:
                continue
            self._last_mtime[meta.file_path] = current_mtime_ns
            if current_size <= meta.file_offset:
                continue
            new_spans = await asyncio.to_thread(
                parse_jsonl_file, meta.file_path, meta.file_offset
            )
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
        new_paths = await asyncio.to_thread(self._scan_new_paths)
        for client, jsonl_file in new_paths:
            self._known_files.add(jsonl_file)
            spans = await asyncio.to_thread(parse_jsonl_file, jsonl_file)
            if not spans:
                continue
            session_id = _extract_session_id(spans, jsonl_file)
            meta = await asyncio.to_thread(_build_meta, client, session_id, jsonl_file, spans)
            self._index[(client, session_id)] = meta
            await self._on_change("session_updated", {
                "client": meta.client,
                "session_id": meta.session_id,
                "last_activity": meta.last_activity,
                "span_count": meta.span_count,
                "new_spans": spans,
            })

    def _scan_new_paths(self) -> list[tuple[str, Path]]:
        """Sync FS walk that returns (client_name, jsonl_path) for files we haven't seen."""
        results: list[tuple[str, Path]] = []
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
                    results.append((client_dir.name, jsonl_file))
        return results

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
