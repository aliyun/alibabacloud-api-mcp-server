from __future__ import annotations

from typing import Any

import pytest

from alibabacloud.mcp_proxy import safety_policy


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def call_api_async(self, params: Any, request: Any, runtime: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {"statusCode": 200}


@pytest.mark.asyncio
async def test_apply_safety_policy_includes_tool_policy_and_empty_safe_policy(
    monkeypatch,
) -> None:
    client = FakeClient()
    monkeypatch.setattr(safety_policy, "_create_anonymous_client", lambda: client)

    await safety_policy.apply_safety_policy(
        "bearer-token",
        None,
        allowed_tools=("AlibabaCloud___RunScript", "AlibabaCloud___GetTask"),
    )

    assert client.requests[0].body == {
        "bearerToken": "bearer-token",
        "safePolicy": "{\"rules\":[]}",
        "toolPolicy": "{\"allowedTools\":[\"AlibabaCloud___RunScript\",\"AlibabaCloud___GetTask\"]}",
    }
