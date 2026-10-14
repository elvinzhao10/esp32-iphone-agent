import asyncio
import json

import httpx
import pytest

from hidagent.actions import action_tools, validate_action
from hidagent.agent import parse_command
from hidagent.llm import LLM


@pytest.mark.parametrize("action", [
    {"action": "tap", "x": -1, "y": 500}, {"action": "tap", "x": True, "y": 500},
    {"action": "tap", "x": float("nan"), "y": 500}, {"action": "swipe", "x1": 0},
    {"action": "type", "text": "text\nclick"}, {"action": "type", "text": "你好"},
    {"action": "path", "points": [[1, 2], [3, 1001]]}, {"action": "home", "extra": "ignored?"},
])
def test_invalid_actions_are_rejected(action):
    with pytest.raises(ValueError):
        validate_action(action)


def test_text_actor_has_the_same_bounds():
    with pytest.raises(ValueError):
        parse_command("tap 1001 500")
    with pytest.raises(ValueError):
        parse_command("type 你好")


def test_structured_actor_sends_image_and_decodes_one_function():
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [{"function": {
            "name": "tap", "arguments": '{"x": 500, "y": 300, "thought": "Settings is visible"}',
        }}]}}]})

    async def scenario():
        llm = LLM("http://test/v1", "vision")
        llm._http = httpx.AsyncClient(base_url="http://test/v1", transport=httpx.MockTransport(handle))
        result = json.loads(await llm.chat("system", "goal", b"jpeg", tools=action_tools()))
        assert validate_action(result)["action"] == "tap"
        await llm._http.aclose()

    asyncio.run(scenario())
    assert seen[0]["tool_choice"] == "required"
    assert seen[0]["parallel_tool_calls"] is False
    assert {"multi_tap", "long_press", "edit_text", "shortcut"} <= {t["function"]["name"] for t in seen[0]["tools"]}
    assert seen[0]["messages"][1]["content"][0]["type"] == "image_url"
