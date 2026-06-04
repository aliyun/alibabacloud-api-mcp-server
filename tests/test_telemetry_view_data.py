from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from alibabacloud.mcp_proxy.telemetry_view.data import (
    resolve_data_dirs,
    parse_jsonl_file,
    build_session_index,
    compute_token_layers,
    SessionMeta,
)


@pytest.fixture
def trace_dir(tmp_path: Path) -> Path:
    """Create a minimal trace directory structure with sample data."""
    traces_dir = tmp_path / "claude-code" / "traces"
    traces_dir.mkdir(parents=True)
    jsonl_file = traces_dir / "sess-001.jsonl"
    lines = [
        {
            "event": "prompt",
            "span_id": "span-root-0",
            "parent_span_id": None,
            "turn": 0,
            "start_timestamp": "2026-05-20T06:11:20.455Z",
            "end_timestamp": "2026-05-20T06:13:02.064Z",
            "session_id": "sess-001",
            "client": "claude-code",
            "prompt": "Help me list ECS instances in cn-hangzhou region",
        },
        {
            "event": "tool_start",
            "span_id": "span-tool-1",
            "parent_span_id": "span-root-0",
            "turn": 0,
            "start_timestamp": "2026-05-20T06:11:25.000Z",
            "end_timestamp": "2026-05-20T06:11:25.000Z",
            "session_id": "sess-001",
            "client": "claude-code",
            "tool_name": "AlibabaCloud___CallCLI",
            "tool_use_id": "toolu_001",
            "tool_input": {"command": "aliyun ecs DescribeInstances --RegionId cn-hangzhou"},
        },
        {
            "event": "tool_end",
            "span_id": "span-tool-1",
            "parent_span_id": "span-root-0",
            "turn": 0,
            "start_timestamp": "2026-05-20T06:11:25.000Z",
            "end_timestamp": "2026-05-20T06:11:27.500Z",
            "session_id": "sess-001",
            "client": "claude-code",
            "tool_name": "AlibabaCloud___CallCLI",
            "tool_use_id": "toolu_001",
            "status": "success",
            "error_message": None,
            "request_id": "REQ-123",
            "duration_ms": 2500,
            "tool_response": [{"type": "text", "text": "{\"Instances\": []}"}],
            "truncated": False,
        },
        {
            "event": "turn_end",
            "span_id": "span-turn-end-0",
            "parent_span_id": "span-root-0",
            "turn": 0,
            "start_timestamp": "2026-05-20T06:13:02.064Z",
            "end_timestamp": "2026-05-20T06:13:02.064Z",
            "session_id": "sess-001",
            "client": "claude-code",
            "stop_reason": "Stop",
        },
    ]
    jsonl_file.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return tmp_path


class TestResolveDataDirs:
    def test_returns_existing_dirs_only(self, tmp_path: Path) -> None:
        existing = tmp_path / "telemetry"
        existing.mkdir()
        non_existing = tmp_path / "nope"
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("ALIBABACLOUD_TELEMETRY_STATE_DIR", str(existing))
            dirs = resolve_data_dirs()
        assert existing in dirs
        assert non_existing not in dirs

    def test_env_var_takes_priority(self, tmp_path: Path) -> None:
        env_dir = tmp_path / "env-telemetry"
        env_dir.mkdir()
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("ALIBABACLOUD_TELEMETRY_STATE_DIR", str(env_dir))
            dirs = resolve_data_dirs()
        assert dirs[0] == env_dir


class TestParseJsonlFile:
    def test_parses_spans_and_merges_tool_pairs(self, trace_dir: Path) -> None:
        jsonl_file = trace_dir / "claude-code" / "traces" / "sess-001.jsonl"
        spans = parse_jsonl_file(jsonl_file)
        # tool_start + tool_end merged into one span
        tool_spans = [s for s in spans if s["event"] == "tool"]
        assert len(tool_spans) == 1
        assert tool_spans[0]["status"] == "success"
        assert tool_spans[0]["duration_ms"] == 2500
        assert tool_spans[0]["tool_input"]["command"] == "aliyun ecs DescribeInstances --RegionId cn-hangzhou"

    def test_prompt_span_is_root(self, trace_dir: Path) -> None:
        jsonl_file = trace_dir / "claude-code" / "traces" / "sess-001.jsonl"
        spans = parse_jsonl_file(jsonl_file)
        prompts = [s for s in spans if s["event"] == "prompt"]
        assert len(prompts) == 1
        assert prompts[0]["parent_span_id"] is None

    def test_all_spans_have_required_fields(self, trace_dir: Path) -> None:
        jsonl_file = trace_dir / "claude-code" / "traces" / "sess-001.jsonl"
        spans = parse_jsonl_file(jsonl_file)
        for span in spans:
            assert "span_id" in span
            assert "event" in span
            assert "start_timestamp" in span
            assert "end_timestamp" in span


class TestBuildSessionIndex:
    def test_builds_index_from_directory(self, trace_dir: Path) -> None:
        index = build_session_index([trace_dir])
        key = ("claude-code", "sess-001")
        assert key in index
        meta = index[key]
        assert meta.client == "claude-code"
        assert meta.session_id == "sess-001"
        assert meta.span_count == 3  # prompt + merged tool + turn_end
        assert meta.turn_count == 1
        assert meta.has_errors is False
        assert "Help me list ECS" in meta.first_prompt_preview

    def test_empty_directory_returns_empty_index(self, tmp_path: Path) -> None:
        index = build_session_index([tmp_path])
        assert len(index) == 0


def _mk_spans(turn: int, skills: list[str], llm_calls: list[dict]) -> list[dict]:
    """Build a flat span list for one turn with N skills and given LLM calls.

    Skills are emitted as skill_invocation events with span_id == tool_use_id
    (Claude convention). LLM calls live on the turn_end event so attribution
    logic sees them via `llm_calls_raw`.
    """
    spans: list[dict] = [{
        "event": "prompt", "span_id": f"prompt-t{turn}", "parent_span_id": None,
        "turn": turn, "start_timestamp": "2026-05-25T10:00:00.000Z",
        "end_timestamp": "2026-05-25T10:00:01.000Z",
    }]
    for i, sk_name in enumerate(skills):
        sid = f"sk-t{turn}-{i}"
        spans.append({
            "event": "skill_invocation", "span_id": sid,
            "parent_span_id": f"prompt-t{turn}",
            "turn": turn, "skill_name": sk_name,
            "tool_use_id": sid,
            "start_timestamp": f"2026-05-25T10:00:0{i+2}.000Z",
            "end_timestamp": f"2026-05-25T10:00:0{i+2}.100Z",
        })
    spans.append({
        "event": "turn_end", "span_id": f"end-t{turn}",
        "parent_span_id": f"prompt-t{turn}", "turn": turn,
        "start_timestamp": "2026-05-25T10:00:30.000Z",
        "end_timestamp": "2026-05-25T10:00:30.000Z",
        "turn_tokens": _sum_call_tokens(llm_calls),
        "llm_calls": llm_calls,
    })
    return spans


def _sum_call_tokens(calls: list[dict]) -> dict:
    keys = ["input_uncached", "input_cached", "input_creation", "output", "reasoning"]
    out = {k: 0 for k in keys}
    for c in calls:
        for k in keys:
            out[k] += int((c.get("llm_tokens") or {}).get(k) or 0)
    return out


def _call(idx: int, tu_ids: list[str], total: int) -> dict:
    return {
        "call_index": idx, "model": "test", "ts": f"2026-05-25T10:00:{idx:02d}Z",
        "tool_use_ids": tu_ids, "tool_span_ids": tu_ids,
        "llm_tokens": {"input_uncached": total, "input_cached": 0,
                       "input_creation": 0, "output": 0, "reasoning": 0},
    }


class TestSkillAttribution:
    """Active-set + whole-turn-fallback attribution with per-skill confidence."""

    def test_single_skill_full_attribution_high_confidence(self) -> None:
        spans = _mk_spans(0, ["skill-A"], [
            _call(1, ["sk-t0-0"], 1000),  # invocation (binding present)
            _call(2, ["bash-x"], 5000),   # bash execution
            _call(3, [], 2000),           # final answer
        ])
        out = compute_token_layers(spans)
        t = out["turns"][0]
        assert t["skill_count"] == 1
        sk = t["skills"][0]
        # Single skill is sole owner of every call → full attribution
        assert sk["estimated_tokens"]["grand_total"] == 8000
        assert sk["confidence_level"] == "high"
        assert sk["confidence_value"] == 1.0

    def test_three_parallel_skills_split_low_confidence(self) -> None:
        # Codex case: one LLM call returns 3 parallel skill invocations
        spans = _mk_spans(0, ["skill-A", "skill-B", "skill-C"], [
            _call(1, ["sk-t0-0", "sk-t0-1", "sk-t0-2"], 9000),
            _call(2, ["bash-x"], 3000),
        ])
        out = compute_token_layers(spans)
        t = out["turns"][0]
        assert t["skill_count"] == 3
        # Each skill takes 1/3 of every call: (9000 + 3000) / 3 = 4000
        for sk in t["skills"]:
            assert sk["estimated_tokens"]["grand_total"] == 4000
            assert sk["confidence_level"] == "low"
            assert abs(sk["confidence_value"] - 1.0/3) < 0.01

    def test_two_serial_skills_no_binding_medium_confidence(self) -> None:
        # Claude case: Skill is harness-side, no tool_use_id in calls.
        # All 3 calls have empty/non-skill tool_use_ids → no binding signal.
        spans = _mk_spans(0, ["skill-A", "skill-B"], [
            _call(1, [], 4000),
            _call(2, [], 4000),
            _call(3, [], 4000),
        ])
        out = compute_token_layers(spans)
        t = out["turns"][0]
        assert t["skill_count"] == 2
        # Whole-turn split: each skill gets half of 12000 = 6000
        for sk in t["skills"]:
            assert sk["estimated_tokens"]["grand_total"] == 6000
            assert sk["confidence_level"] == "medium"
            assert sk["confidence_value"] == 0.5

    def test_token_conservation_across_skills(self) -> None:
        """Sum of per-skill attribution + non_skill bucket must equal turn total."""
        spans = _mk_spans(0, ["skill-A", "skill-B"], [
            _call(1, ["sk-t0-0"], 1000),
            _call(2, ["sk-t0-1"], 2000),
            _call(3, ["bash-x"], 3000),
        ])
        out = compute_token_layers(spans)
        t = out["turns"][0]
        turn_total = t["turn_tokens"]["grand_total"]
        attributed = sum(sk["estimated_tokens"]["grand_total"] for sk in t["skills"])
        # Conservation within ±1 rounding (call 3 splits 3000 across 2 active skills)
        assert abs(attributed - turn_total) <= 1

    def test_partial_binding_does_not_starve_unbound_skills(self) -> None:
        # Claude case: 3 parallel skills, but only ONE happens to have a
        # bash whose tool_use_id leaks through into call.tool_use_ids.
        # The bound skill should NOT absorb all orphan-call tokens — that
        # would zero-out the other 2 parallel skills (a7d477f7 bug).
        spans = _mk_spans(0, ["skill-A", "skill-B", "skill-C"], [
            _call(1, [], 3000),                # orphan
            _call(2, [], 3000),                # orphan
            _call(3, ["sk-t0-2"], 3000),       # bound to skill-C ONLY
            _call(4, [], 3000),                # orphan
        ])
        out = compute_token_layers(spans)
        t = out["turns"][0]
        assert t["skill_count"] == 3
        by_name = {s["skill_name"]: s for s in t["skills"]}
        # Orphans (3 calls × 3000 = 9000) split 1/3 across all → 3000 each
        # Bound call (3000) goes 100% to skill-C
        assert by_name["skill-A"]["estimated_tokens"]["grand_total"] == 3000
        assert by_name["skill-B"]["estimated_tokens"]["grand_total"] == 3000
        assert by_name["skill-C"]["estimated_tokens"]["grand_total"] == 6000
        # A and B never had a binding → low confidence
        assert by_name["skill-A"]["confidence_level"] == "low"
        assert by_name["skill-B"]["confidence_level"] == "low"
        # C got 1 sole-binding (weight 1.0) + 3 split (weight 0.333)
        # token-weighted avg: (3000*1.0 + 3*1000*0.333) / 6000 = 0.667 → medium
        assert by_name["skill-C"]["confidence_level"] == "medium"

    def test_attribution_basis_records_call_history(self) -> None:
        spans = _mk_spans(0, ["skill-A"], [
            _call(1, ["sk-t0-0"], 1000),
            _call(2, ["bash-x"], 2000),
        ])
        out = compute_token_layers(spans)
        t = out["turns"][0]
        sk = t["skills"][0]
        basis = sk["attribution_basis"]
        assert len(basis) == 2
        assert basis[0]["call_index"] == 1
        assert basis[0]["weight"] == 1.0
        assert basis[1]["call_index"] == 2
        assert basis[1]["weight"] == 1.0

    def test_real_llm_call_event_takes_precedence_over_synthetic(self) -> None:
        """When a first-class llm_call event exists, t.llm_calls[i].span_id
        is the real event's span_id (so the chip lands on the real tree
        node), not the synthetic placeholder."""
        spans = _mk_spans(0, ["skill-A"], [_call(1, ["sk-t0-0"], 1000)])
        # Inject a real llm_call event matching call_index=1
        spans.append({
            "event": "llm_call", "span_id": "real-llm-call-abc",
            "parent_span_id": "prompt-t0", "turn": 0,
            "call_index": 1, "model": "test",
            "start_timestamp": "2026-05-25T10:00:01.500Z",
            "end_timestamp": "2026-05-25T10:00:01.500Z",
            "tool_use_ids": ["sk-t0-0"], "tool_span_ids": ["sk-t0-0"],
            "llm_tokens": {"input_uncached": 1000, "input_cached": 0,
                           "input_creation": 0, "output": 0, "reasoning": 0},
        })
        out = compute_token_layers(spans)
        t = out["turns"][0]
        assert len(t["llm_calls"]) == 1
        # Real event id wins, not the synthetic "llm-call-t0-c1"
        assert t["llm_calls"][0]["span_id"] == "real-llm-call-abc"

    def test_synthetic_id_used_when_no_real_event(self) -> None:
        """Legacy traces with only the side-table fall back to the synthetic
        span_id so old viewers keep working."""
        spans = _mk_spans(0, ["skill-A"], [_call(1, ["sk-t0-0"], 1000)])
        out = compute_token_layers(spans)
        t = out["turns"][0]
        assert t["llm_calls"][0]["span_id"] == "llm-call-t0-c1"
