"""Shared validation for model actions (coordinates use the 0–1000 screen space)."""

import math

PARAMS = {
    "tap": ("x", "y"), "swipe": ("x1", "y1", "x2", "y2"), "circle": ("x", "y", "r"),
    "path": ("points",), "type": ("text",), "key": ("combo",), "home": (), "back": (),
    "wait": (), "replan": (), "done": ("answer",), "fail": ("reason",),
}


def validate_action(action: dict) -> dict:
    name = action.get("action")
    if name not in PARAMS:
        raise ValueError("unknown action")
    allowed = {*PARAMS[name], "action", "thought", "thought_zh"}
    if name == "tap":
        allowed.add("precise")
    if set(action) - allowed:
        raise ValueError("unexpected action arguments")
    for key in PARAMS[name]:
        value = action.get(key)
        if key in ("text", "combo", "answer", "reason"):
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise ValueError(f"invalid {key}")
            if key in ("text", "combo") and (not value.isascii() or any(ord(c) < 32 for c in value)):
                raise ValueError("keyboard input must be printable ASCII on one line")
        elif key == "points":
            if not isinstance(value, list) or not 2 <= len(value) <= 20:
                raise ValueError("path requires 2–20 points")
            for point in value:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise ValueError("path requires coordinate pairs")
                for coordinate in point:
                    _coordinate(coordinate)
        else:
            _coordinate(value)
    if "precise" in action and not isinstance(action["precise"], bool):
        raise ValueError("precise must be boolean")
    for key in ("thought", "thought_zh"):
        if key in action and (not isinstance(action[key], str) or len(action[key]) > 4000):
            raise ValueError(f"invalid {key}")
    return action


def _coordinate(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 1000):
        raise ValueError("coordinates must be finite numbers between 0 and 1000")


def action_tools() -> list[dict]:
    """Simple function schemas work with OpenAI-compatible vision tool callers."""
    result = []
    for name, keys in PARAMS.items():
        properties = {"thought": {"type": "string", "description": "Brief observation and reason for this action."}}
        for key in keys:
            if key in ("text", "combo", "answer", "reason"):
                properties[key] = {"type": "string", "minLength": 1, "maxLength": 4000}
            elif key == "points":
                properties[key] = {"type": "array", "minItems": 2, "maxItems": 20,
                                   "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                             "items": {"type": "number", "minimum": 0, "maximum": 1000}}}
            else:
                properties[key] = {"type": "number", "minimum": 0, "maximum": 1000}
        if name == "tap":
            properties["precise"] = {"type": "boolean"}
        result.append({"type": "function", "function": {"name": name, "description": f"iPhone action: {name}",
                       "parameters": {"type": "object", "properties": properties,
                                      "required": list(keys), "additionalProperties": False}}})
    return result
