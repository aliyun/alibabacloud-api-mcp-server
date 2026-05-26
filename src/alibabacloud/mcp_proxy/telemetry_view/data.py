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
                "skill_tag": ev.get("skill_tag"),
                "cloud_api": ev.get("cloud_api"),
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
# The producer hook emits per-turn `turn_end` events carrying these Layer 1
# (strict, high-confidence) fields:
#
#   * ``turn_tokens``            — sum of LLM token usage rows that belong to
#                                  this turn.
#   * ``aliyun_session_tokens``  — cumulative running total across traced
#                                  turns (already accumulated by the producer).
#   * ``llm_calls``              — one entry per real LLM call: ``call_index``,
#                                  ``model``, ``ts``, ``tool_use_ids``,
#                                  ``tool_span_ids``, ``llm_tokens``. Tokens
#                                  belong to the call, not to each emitted
#                                  tool span — this prevents the fan-out
#                                  overcount when one call emits N parallel
#                                  bashes.
#   * ``tool_tokens``            — LEGACY per-tool-span breakdown, keyed by
#                                  span_id. Empty dict on new traces; only
#                                  populated by old hooks. The viewer falls
#                                  back to this path when ``llm_calls`` is
#                                  absent.
#
# The viewer reconstructs Layer 2 (estimated skill attribution) itself by
# walking each LLM call's tool_span_ids up to their nearest
# ``skill_invocation`` ancestor. The confidence label reflects how confidently
# those calls can be attributed to a single skill:
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

    Legacy heuristic for the old tool_tokens fan-out path. The new path
    (use_llm_calls=True) computes confidence per-skill from actual attribution
    weights via _label_for_confidence and aggregates them up to the turn.
    """
    if skill_count == 0:
        return ("high", 1.0)
    if skill_count == 1:
        return ("high", 0.9)
    if skill_count <= 3 and non_skill_tool_count == 0:
        return ("medium", 0.6)
    return ("low", 0.3)


def _label_for_confidence(value: float) -> str:
    """Single source of truth for confidence label thresholds.

    A skill is "high" only when every attributed call gave it ≥0.85 weight
    (i.e. it was sole or near-sole owner). Medium when avg weight ≥0.5
    (typically 2 parallel/serial skills). Low otherwise (3+ ambiguous)."""
    if value >= 0.85:
        return "high"
    if value >= 0.5:
        return "medium"
    if value > 0:
        return "low"
    return "none"


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
    # Real first-class llm_call events keyed by (turn, call_index) → span_id.
    # When present, the viewer uses these real ids for chip lookup so the
    # chip lands on the real tree node instead of a synthetic placeholder.
    real_llm_call_id: dict[tuple[int, Any], str] = {}

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
        elif event == "llm_call":
            ci = span.get("call_index")
            if ci is not None:
                real_llm_call_id[(turn, ci)] = sid

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
        llm_calls_raw = te.get("llm_calls") or []
        use_llm_calls = bool(llm_calls_raw)

        skill_spans = skills_in_turn.get(turn, [])
        tool_spans = tools_in_turn.get(turn, [])
        skill_set = {s["span_id"] for s in skill_spans if s.get("span_id")}

        # Per-skill attribution. Two paths:
        #  * NEW (use_llm_calls): active-set algorithm. Walk LLM calls in
        #    order, maintain the set of skills invoked-so-far in this turn.
        #    For each call:
        #      - if it invokes K≥1 skill(s): attribute its tokens to those
        #        K skills with weight 1/K (the invocation itself).
        #      - if it has no skill invocations but skills are active:
        #        attribute to all K active skills with weight 1/K (execution
        #        cost of those skills).
        #      - if no skills active: prompt-level, count as non_skill.
        #    Per-skill confidence = token-weighted average of contributing
        #    call weights. high (≥0.85) means sole-owner most of the time;
        #    low (<0.5) means consistently sharing with 2+ siblings.
        #  * LEGACY: old trace files without llm_calls — walk-ancestor logic.
        skill_tokens: dict[str, dict[str, int]] = {sid: _empty_tokens() for sid in skill_set}
        skill_attribution: dict[str, list[dict[str, Any]]] = {sid: [] for sid in skill_set}
        non_skill_tool_count = 0
        tools_out: list[dict[str, Any]] = []
        llm_calls_out: list[dict[str, Any]] = []

        if use_llm_calls:
            # Tools listed once each, with zero tokens — chips are now driven
            # by llm_calls at the call level, not per-tool.
            for tool in tool_spans:
                sid = tool.get("span_id")
                if sid and (sid + ".skill") in skill_set:
                    continue
                empty = _empty_tokens()
                tools_out.append({
                    "span_id": sid,
                    "tool_name": tool.get("tool_name") or "",
                    "tokens": {**empty, "grand_total": 0},
                })

            # Map every tool_use_id that corresponds to a skill invocation →
            # the skill_span_id. Two sources: (1) skill.tool_use_id from the
            # event itself (Codex bash-as-skill: the inner bash id),
            # (2) the .skill suffix convention used by the Codex synthesizer.
            # Claude does NOT surface Skill as a tool_use in its transcript
            # (Skill is harness-side), so this map is empty for Claude.
            tool_use_to_skill: dict[str, str] = {}
            for sk in skill_spans:
                sk_sid = sk.get("span_id") or ""
                sk_tu = sk.get("tool_use_id") or sk_sid
                if sk_tu:
                    tool_use_to_skill[sk_tu] = sk_sid
                if sk_sid and sk_sid not in tool_use_to_skill:
                    tool_use_to_skill[sk_sid] = sk_sid

            # Detect which skills have ANY binding evidence in this turn's
            # transcript. Codex: typically all (skill bash_ids appear in
            # call.tool_use_ids). Claude: typically none (Skill is harness-
            # only) — but occasionally one bound skill leaks through.
            # PARTIAL coverage is dangerous: if only 1 of N parallel skills
            # has bindings, naively trusting the bind would steer ALL orphan
            # tokens to that one skill (the a7d477f7 bug). We require
            # FULL coverage before using the per-call active-set algorithm.
            # Otherwise we treat every skill as equally active for orphan
            # calls, while still attributing bound calls precisely.
            sorted_skill_set = sorted(skill_set)
            bound_skills: set[str] = set()
            for c in llm_calls_raw:
                for t in (
                    list(c.get("tool_use_ids") or [])
                    + list(c.get("tool_span_ids") or [])
                ):
                    sk = tool_use_to_skill.get(t)
                    if sk in skill_set:
                        bound_skills.add(sk)
            full_binding_coverage = bool(skill_set) and bound_skills == skill_set

            # Pre-seed with all skills unless we have full coverage (in which
            # case we trust per-call discovery to add them in invocation order).
            active_skills_order: list[str] = (
                [] if full_binding_coverage else list(sorted_skill_set)
            )

            for call in llm_calls_raw:
                tokens = dict(call.get("llm_tokens") or {})
                normalised = {k: int(tokens.get(k) or 0) for k in _TOKEN_KEYS}
                grand = sum(normalised.values())
                call_tool_span_ids = list(call.get("tool_span_ids") or [])
                call_tool_use_ids = list(call.get("tool_use_ids") or [])
                ci = call.get("call_index")
                # Prefer real first-class llm_call event id (new traces) so
                # the chip lands on the real tree node; fall back to the
                # synthetic id for legacy traces that only have side-table.
                real_sid = real_llm_call_id.get((turn, ci))
                llm_calls_out.append({
                    "span_id": real_sid or llm_call_span_id(turn, ci),
                    "call_index": ci,
                    "model": call.get("model"),
                    "ts": call.get("ts"),
                    "tool_span_ids": call_tool_span_ids,
                    "tokens": {**normalised, "grand_total": grand},
                })

                # Identify skill invocations in this call (dedup-preserving).
                skills_in_call: list[str] = []
                seen_in_call: set[str] = set()
                for ident in (call_tool_use_ids + call_tool_span_ids):
                    sk_sid = tool_use_to_skill.get(ident)
                    if sk_sid and sk_sid not in seen_in_call:
                        skills_in_call.append(sk_sid)
                        seen_in_call.add(sk_sid)

                # Update active set (newly-invoked skills join the context).
                for sk in skills_in_call:
                    if sk not in active_skills_order:
                        active_skills_order.append(sk)

                if grand <= 0:
                    continue

                # Three attribution branches.
                if skills_in_call:
                    n = len(skills_in_call)
                    weight = 1.0 / n
                    reason = "sole invocation" if n == 1 else f"1 of {n} parallel skill invocations"
                    for sk in skills_in_call:
                        skill_attribution[sk].append({
                            "call_index": call.get("call_index"),
                            "weight": weight,
                            "tokens_grand": int(round(grand * weight)),
                            "tokens": {k: normalised[k] * weight for k in _TOKEN_KEYS},
                            "reason": reason,
                        })
                elif active_skills_order:
                    k = len(active_skills_order)
                    weight = 1.0 / k
                    reason = "sole active skill" if k == 1 else f"1 of {k} active skills"
                    for sk in active_skills_order:
                        skill_attribution[sk].append({
                            "call_index": call.get("call_index"),
                            "weight": weight,
                            "tokens_grand": int(round(grand * weight)),
                            "tokens": {kk: normalised[kk] * weight for kk in _TOKEN_KEYS},
                            "reason": reason,
                        })
                else:
                    # No skills active in this turn yet — prompt-level work.
                    non_skill_tool_count += 1

            # Materialise per-skill totals (round shares to int last).
            for sid in skill_set:
                records = skill_attribution[sid]
                if not records:
                    continue
                acc = {k: 0.0 for k in _TOKEN_KEYS}
                for r in records:
                    for k in _TOKEN_KEYS:
                        acc[k] += r["tokens"][k]
                skill_tokens[sid] = {k: int(round(acc[k])) for k in _TOKEN_KEYS}
        else:
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

        skills_out: list[dict[str, Any]] = []
        for skill in skill_spans:
            sid = skill.get("span_id")
            tokens = skill_tokens.get(sid, _empty_tokens())
            grand = sum(tokens.values())
            records = skill_attribution.get(sid, [])
            if use_llm_calls and records and grand > 0:
                # Token-weighted average of call weights.
                weighted_sum = sum(r["weight"] * r["tokens_grand"] for r in records)
                total_grand = sum(r["tokens_grand"] for r in records)
                sk_conf = weighted_sum / total_grand if total_grand > 0 else 0.0
            elif use_llm_calls and records:
                sk_conf = sum(r["weight"] for r in records) / len(records)
            else:
                sk_conf = 1.0 if not use_llm_calls and grand > 0 else 0.0
            skills_out.append({
                "span_id": sid,
                "skill_name": skill.get("skill_name") or "",
                "estimated_tokens": {**tokens, "grand_total": grand},
                "confidence_value": round(sk_conf, 3),
                "confidence_level": _label_for_confidence(sk_conf),
                "attribution_basis": [
                    {
                        "call_index": r["call_index"],
                        "weight": round(r["weight"], 3),
                        "grand_total": r["tokens_grand"],
                        "reason": r["reason"],
                    }
                    for r in records
                ],
            })

        # Turn-level confidence: token-weighted average of skill confidences.
        if use_llm_calls and skills_out:
            total_attributed = sum(s["estimated_tokens"]["grand_total"] for s in skills_out)
            if total_attributed > 0:
                confidence_value = sum(
                    s["confidence_value"] * s["estimated_tokens"]["grand_total"]
                    for s in skills_out
                ) / total_attributed
            else:
                confidence_value = sum(s["confidence_value"] for s in skills_out) / len(skills_out)
            confidence_level = _label_for_confidence(confidence_value)
        else:
            confidence_level, confidence_value = _confidence_for_turn(
                len(skill_set), non_skill_tool_count
            )
        confidence_value = round(confidence_value, 3)

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
            "llm_calls": llm_calls_out,
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
                # Drop the bash's duration_ms after promotion: skill rows
                # should not display a Duration chip (parity with claude /
                # qoderwork native Skill rows, which have no duration_ms).
                node["duration_ms"] = None
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


def _reanchor_real_llm_call_starts(spans: list[dict[str, Any]]) -> None:
    """Codex emits the token_count event AFTER LLM streaming finishes, so the
    first-class llm_call event's start_timestamp can land AFTER the tool
    calls it produced. That breaks chronological views (flat timeline, tree
    sibling order under prompt) — the LLM call appears below its bash. For
    each real llm_call event with non-empty tool_span_ids, re-anchor its
    start/end to ``min(child.start_timestamp) - 1ms`` so it sorts strictly
    before its tools. Mutates the dicts in place; only adjusts when the
    current ts is not already earliest, so Claude (already-correct ordering)
    is untouched."""
    span_start: dict[str, str] = {}
    for s in spans:
        # parse_jsonl_file merges tool_start+tool_end into event="tool";
        # check both shapes to be safe with mixed inputs.
        if s.get("event") in ("tool", "tool_start"):
            sid = s.get("span_id")
            ts = s.get("start_timestamp")
            if sid and ts:
                # First write wins (tool_start arrives before tool_end).
                span_start.setdefault(sid, ts)
    for s in spans:
        if s.get("event") != "llm_call":
            continue
        tu_ids = s.get("tool_span_ids") or []
        candidates = [span_start[t] for t in tu_ids if t in span_start]
        if not candidates:
            continue
        earliest = min(_normalize_ts(c) for c in candidates)
        cur = _normalize_ts(s.get("start_timestamp") or "")
        if cur and cur < earliest:
            continue  # already strictly before — Claude path, nothing to do
        new_ts = _iso_minus_ms(earliest, 1)
        if new_ts:
            s["start_timestamp"] = new_ts
            s["end_timestamp"] = new_ts


def build_span_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _reanchor_real_llm_call_starts(spans)
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
    _insert_llm_call_nodes(roots, spans)
    return roots


def llm_call_span_id(turn: Any, call_index: Any) -> str:
    """Stable id for the synthetic LLM-call node. Shared between data.py
    (tree insertion) and the frontend (token index lookup)."""
    return f"llm-call-t{turn}-c{call_index}"


def _normalize_ts(ts: Any) -> str:
    """Pad ISO timestamps without fractional seconds (...:56Z) so they sort
    consistently with timestamps that include milliseconds (...:56.720Z).
    Without this, 'Z' (0x5A) sorts after '.' (0x2E) and turn-end always
    appears before sub-second-precision LLM call ts in the same second."""
    if not ts:
        return ""
    if isinstance(ts, str) and ts.endswith("Z") and "." not in ts:
        return ts[:-1] + ".000Z"
    return str(ts)


def _interpolate_iso_ts(start: Any, end: Any, step: int, total: int) -> str:
    """Return start + (step/total) * (end - start) as ISO-Z. Used as a
    fallback to redistribute orphan synthetic LLM calls evenly across a
    turn's wall-clock duration when the producer wrote identical ts on
    every call (legacy traces). Best-effort: returns "" on any parse error
    so the caller can fall back to the original ts."""
    from datetime import datetime, timezone
    if not start or not end or total <= 0:
        return ""
    try:
        s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    delta = (e - s).total_seconds()
    if delta <= 0:
        return ""
    out = s + (e - s) * (step / total)
    return out.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{out.microsecond // 1000:03d}Z"


def _iso_minus_ms(ts: Any, ms: int) -> str:
    """Subtract `ms` milliseconds from an ISO-Z timestamp. Returns "" on
    any parse failure so callers can fall back to the original ts."""
    from datetime import datetime, timedelta, timezone
    if not ts or ms <= 0:
        return ""
    try:
        s = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    out = s - timedelta(milliseconds=ms)
    return out.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{out.microsecond // 1000:03d}Z"


def _insert_llm_call_nodes(
    roots: list[dict[str, Any]],
    spans: list[dict[str, Any]],
) -> None:
    """Wrap each prompt's tool/skill children in synthetic 'llm_call' nodes
    so the tree visually groups tools that came from the same LLM API call.

    For every ``turn_end`` event with an ``llm_calls`` list, look up the
    prompt span (parent_span_id of the turn_end), and for each call create a
    leaf node attached to that prompt. Existing children whose ``span_id``
    appears in ``call.tool_span_ids`` are moved under the synthetic node.
    Orphan calls (no ``tool_span_ids`` — pure reasoning / final text)
    appear as childless leaves so their tokens stay visible.
    """
    by_id: dict[str, dict[str, Any]] = {}

    def index(node: dict[str, Any]) -> None:
        sid = node.get("span_id")
        if sid:
            by_id[sid] = node
        for c in node.get("children") or []:
            index(c)
    for r in roots:
        index(r)

    # Turns that already have real first-class llm_call events get no
    # synthesis — the producer's events are already in the tree as siblings
    # of their tool calls under the prompt, ordered by start_timestamp.
    turns_with_real_calls: set[Any] = {
        s.get("turn") for s in spans if s.get("event") == "llm_call"
    }

    for te in spans:
        if te.get("event") != "turn_end":
            continue
        if te.get("turn") in turns_with_real_calls:
            continue
        calls = te.get("llm_calls") or []
        if not calls:
            continue
        prompt_id = te.get("parent_span_id")
        prompt_node = by_id.get(prompt_id) if prompt_id else None
        if prompt_node is None:
            continue

        existing = list(prompt_node.get("children") or [])
        child_by_sid = {
            c.get("span_id"): c for c in existing if c.get("span_id")
        }
        moved: set[str] = set()
        synth_nodes: list[dict[str, Any]] = []

        # Pre-fix Claude traces wrote `_now_iso()` at stop-time for every
        # llm_call row, so all calls share one ts (e.g. turn-end's). Detect
        # and interpolate orphan ts across [prompt, turn_end] by call_index
        # so the visual order is at least monotonic instead of clustered.
        # Normalize ts before comparing — call.ts has second precision while
        # turn_end's start_timestamp has ms precision; raw string equality
        # would never match.
        call_ts_set = {_normalize_ts(c.get("ts") or "")[:19] for c in calls}
        te_ts_trim = _normalize_ts(te.get("start_timestamp") or "")[:19]
        broken_ts = (
            len(call_ts_set) == 1
            and len(calls) > 1
            and next(iter(call_ts_set)) == te_ts_trim
        )
        prompt_start_ts = prompt_node.get("start_timestamp") or ""
        turn_end_ts = te.get("start_timestamp") or ""

        def _interp_ts(call_index: Any, total: int) -> str:
            ci = call_index if isinstance(call_index, int) else 1
            ts = _interpolate_iso_ts(prompt_start_ts, turn_end_ts, ci, total + 1)
            return ts or turn_end_ts

        total_calls = len(calls)
        for call in calls:
            tspan_ids = list(call.get("tool_span_ids") or [])
            taken: list[dict[str, Any]] = []
            for sid in tspan_ids:
                ch = child_by_sid.get(sid)
                if ch is not None and sid not in moved:
                    taken.append(ch)
                    moved.add(sid)
            tokens = call.get("llm_tokens") or {}
            if taken:
                # Codex emits token_count AFTER LLM streaming finishes, which
                # means call.ts > children's start_timestamp — naive use of
                # taken[0].start_timestamp would also tie-break wrong (taken
                # is in tool_span_ids iteration order, not chronological).
                # Re-anchor to min(child) - 1ms so the synth LLM call sorts
                # strictly before every child in flat-mode timeline.
                child_starts = [
                    _normalize_ts(t.get("start_timestamp"))
                    for t in taken if t.get("start_timestamp")
                ]
                child_ends = [
                    _normalize_ts(t.get("end_timestamp"))
                    for t in taken if t.get("end_timestamp")
                ]
                earliest = min(child_starts) if child_starts else ""
                shifted = _iso_minus_ms(earliest, 1) if earliest else ""
                start_ts = shifted or earliest or taken[0].get("start_timestamp")
                end_ts = max(child_ends) if child_ends else taken[-1].get("end_timestamp")
            elif broken_ts:
                start_ts = _interp_ts(call.get("call_index"), total_calls)
                end_ts = start_ts
            else:
                start_ts = call.get("ts") or te.get("start_timestamp")
                end_ts = call.get("ts") or te.get("end_timestamp")
            synth = {
                "span_id": llm_call_span_id(te.get("turn"), call.get("call_index")),
                "parent_span_id": prompt_id,
                "event": "llm_call",
                "call_index": call.get("call_index"),
                "model": call.get("model"),
                "ts": call.get("ts"),
                "tool_span_ids": tspan_ids,
                "llm_tokens": tokens,
                "turn": te.get("turn"),
                "start_timestamp": start_ts,
                "end_timestamp": end_ts,
                "children": taken,
            }
            synth_nodes.append(synth)

        leftover = [c for c in existing if c.get("span_id") not in moved]
        combined = leftover + synth_nodes
        # Secondary key: call_index lets identically-stamped synth calls keep
        # producer order; non-llm spans get a large constant so they sort
        # purely by timestamp.
        combined.sort(key=lambda c: (
            _normalize_ts(c.get("start_timestamp")),
            c.get("call_index") if c.get("event") == "llm_call" else 10**9,
        ))
        prompt_node["children"] = combined


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
