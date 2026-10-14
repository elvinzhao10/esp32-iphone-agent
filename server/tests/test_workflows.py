import asyncio
import json

import httpx
import pytest

from hidagent.workflows import Recipe, route


def test_jev_routes_only_known_recipes_and_escalates(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    recipe = Recipe(name="search", description="Open search", precondition="Home screen visible",
                    steps=[{"action": "wait"}])
    confidence, choice = .95, "search"

    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == "jev-latest"
        assert body["state"]["goal"] == "Search"
        assert body["state"]["observed_context"] == "Home screen visible"
        assert "search" in body["state"]["workflows"]
        assert "escalate" in body["questions"]["workflow"]["criteria"]
        assert "Authorization" in request.headers
        return httpx.Response(200, json={"answers": {"workflow": {
            "type": "choice", "choice": choice, "confidence": confidence}, "eligible": {"noul": .99}}})

    async def run():
        return await route("Search", "Home screen visible", {"search": recipe},
                           transport=httpx.MockTransport(respond))
    assert asyncio.run(run())["workflow"] == "search"
    confidence = .3
    assert asyncio.run(run())["needs_remote"] is True
    confidence, choice = .99, "escalate"
    assert asyncio.run(run())["workflow"] is None
    choice = "invented-action"
    with pytest.raises(ValueError):
        asyncio.run(run())
    choice, confidence = "search", float("nan")
    with pytest.raises(ValueError):
        asyncio.run(run())
    monkeypatch.delenv("TYPESAFE_API_KEY")
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        asyncio.run(run())


@pytest.mark.parametrize("arguments", [{"x": True, "y": .5}, {"x": .5, "y": float("inf")},
                                      {"x": .5, "y": .5, "shell": "bad"}])
def test_recipe_rejects_invalid_actions(arguments):
    recipe = Recipe(name="tap", description="Tap", precondition="Known screen",
                    steps=[{"action": "tap", "arguments": arguments}])
    with pytest.raises(ValueError):
        recipe.commands()


def test_openai_router_uses_custom_base_and_rejects_free_actions(monkeypatch, tmp_path):
    from hidagent.settings import save_settings, update_settings
    monkeypatch.setenv("HIDAGENT_DATA", str(tmp_path))
    save_settings(update_settings({"jev": {"protocol": "openai", "base_url": "http://router.test/v1",
                                          "model": "my-router", "api_key": "test-only"}}))
    recipe = Recipe(name="search", description="Search", precondition="Focused search", steps=[{"action": "wait"}])
    choice = "search"

    def respond(request):
        assert str(request.url) == "http://router.test/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "my-router"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "choice": choice, "confidence": .95})}}]})

    async def run():
        return await route("Search", "Focused search", {"search": recipe}, transport=httpx.MockTransport(respond))
    assert asyncio.run(run())["workflow"] == "search"
    choice = "tap-anywhere"
    with pytest.raises(ValueError):
        asyncio.run(run())
