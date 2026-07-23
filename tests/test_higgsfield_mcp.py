from __future__ import annotations

import pytest
from asset_assembly_automator.clients.higgsfield_mcp import _tool_payload


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text


class _Result:
    def __init__(self, *, structured=None, content=None, is_error=False) -> None:
        self.structuredContent = structured
        self.content = content or []
        self.isError = is_error


def test_tool_payload_prefers_structured_content():
    payload = _tool_payload(_Result(structured={"results": [{"id": "abc"}]}))
    assert payload["results"][0]["id"] == "abc"


def test_tool_payload_parses_json_text_blocks():
    payload = _tool_payload(_Result(content=[_Block('{"results": [{"status": "completed"}]}')]))
    assert payload["results"][0]["status"] == "completed"


def test_tool_payload_raises_on_error():
    with pytest.raises(RuntimeError, match="billing"):
        _tool_payload(_Result(is_error=True, content=[_Block("billing required")]))
