import asyncio

import pytest

from hidagent.actions import validate_action
from hidagent.phone import Phone
from hidagent.workflows import Recipe


class Board:
    links = 0
    def __init__(self): self.commands = []
    async def send(self, command): self.commands.append(command)


def test_gestures_and_editing_use_old_firmware_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE_KIND", "ipad")
    board = Board()
    phone = Phone(board, tmp_path / "calibration.json")
    phone.span, phone._pos = {"w": 400, "h": 800}, (0, 0)

    async def no_sleep(_): pass
    monkeypatch.setattr("hidagent.phone.asyncio.sleep", no_sleep)

    async def run():
        await phone.multi_tap(.5, .5, 3)
        assert board.commands == ["move 200 400", "click", "click", "click"]
        board.commands.clear()
        await phone.long_press(.5, .5)
        assert board.commands == ["move 0 0", "press", "release"]
        board.commands.clear()
        await phone.edit_text("Calendar", replace=True)
        assert board.commands == ["key cmd+a", "type Calendar"]
        board.commands.clear()
        await phone.edit_text("Settings", submit=True)
        assert board.commands == ["type Settings", "key enter"]
        board.commands.clear()
        await phone.shortcut("search")
        assert board.commands == ["key cmd+space"]
        board.commands.clear()
        await phone.type(" hi ")
        assert board.commands == ["key space", "type hi", "key space"]
        board.commands.clear()
        await phone.type("  ")
        assert board.commands == ["key space", "key space"]
    asyncio.run(run())


def test_cancelled_hold_releases_mouse_button(tmp_path):
    board = Board()
    phone = Phone(board, tmp_path / "calibration.json")
    phone.span, phone._pos = {"w": 400, "h": 800}, (0, 0)

    async def run():
        task = asyncio.create_task(phone.long_press(.5, .5, 2000))
        while "press" not in board.commands:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert board.commands[-1] == "release"
    asyncio.run(run())


def test_iphone_search_does_not_chain_unverified_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE_KIND", "iphone")
    phone = Phone(Board(), tmp_path / "calibration.json")
    gestures = []

    async def home(): pytest.fail("Home must be observed separately before Search")
    async def swipe(*args, **kwargs): gestures.append((args, kwargs))
    monkeypatch.setattr(phone, "go_home", home)
    monkeypatch.setattr(phone, "swipe", swipe)
    asyncio.run(phone.shortcut("search"))
    assert gestures == [((.5, .35, .5, .65), {"hold": False})]


@pytest.mark.parametrize("action", [
    {"action": "multi_tap", "x": 500, "y": 500, "count": 4},
    {"action": "multi_tap", "x": 500, "y": 500, "count": True},
    {"action": "long_press", "x": 500, "y": 500, "duration_ms": 2001},
    {"action": "shortcut", "name": "globe"},
    {"action": "edit_text", "text": "Hello", "submit": "yes"},
])
def test_new_actions_validate_without_weakening_old_actions(action):
    with pytest.raises(ValueError): validate_action(action)


def test_final_settling_requires_independent_keyboard_actions():
    recipe = Recipe(name="edit", description="Edit query", precondition="Focused field", settle="final",
                    steps=[{"action": "edit_text", "arguments": {"text": "Calendar", "replace": True}}])
    assert recipe.commands()[0][0]["replace"] is True
    recipe.steps[0].require_change = True
    with pytest.raises(ValueError): recipe.commands()
    recipe = Recipe(name="search", description="Search", precondition="Home", settle="final",
                    steps=[{"action": "shortcut", "arguments": {"name": "search"}}])
    with pytest.raises(ValueError): recipe.commands()


def test_fast_capture_waits_for_a_post_command_frame(monkeypatch):
    from hidagent.screen import Screen
    screen = Screen()
    seen = []

    async def fresh(since, timeout):
        seen.append((since, timeout))
        return b"jpeg"
    async def no_sleep(_): pass
    monkeypatch.setattr(screen, "fresh", fresh)
    monkeypatch.setattr("hidagent.screen.asyncio.sleep", no_sleep)
    assert asyncio.run(screen.after_action()) is True
    assert seen[0][1] == .6
