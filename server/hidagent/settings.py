"""Host-local provider settings. Secrets never appear in read responses."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(max_length=2000)
    model: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=4000)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if (url.scheme not in ("http", "https") or not url.hostname or url.username
                or url.password or url.query or url.fragment):
            raise ValueError("base URL must be HTTP(S), without credentials, query or fragment")
        return value.rstrip("/")


class Decision(Provider):
    protocol: Literal["typesafe", "openai"] = "typesafe"
    min_confidence: float = Field(default=.9, ge=0, le=1, allow_inf_nan=False)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: Provider
    planner: Provider
    jev: Decision

    def public(self):
        return {name: {**provider.model_dump(exclude={"api_key"}), "key_set": bool(provider.api_key)}
                for name, provider in (("actor", self.actor), ("planner", self.planner), ("jev", self.jev))}


def settings_path():
    return Path(os.environ.get("HIDAGENT_DATA", Path.home() / ".hidagent")) / "providers.json"


def load_settings():
    def vision(role):
        def env(key, default=""):
            return os.environ.get(f"{role}_{key}") or os.environ.get(f"LLM_{key}", default)
        return Provider(base_url=env("BASE_URL", "http://localhost:8000/v1"),
                        model=env("MODEL"), api_key=env("API_KEY"))
    value = Settings(actor=vision("ACTOR"), planner=vision("PLANNER"), jev=Decision(
        base_url=os.environ.get("JEV_BASE_URL", "https://api.typesafe.ai/v1"),
        model=os.environ.get("JEV_MODEL", "jev-latest"), api_key=os.environ.get("TYPESAFE_API_KEY", ""),
        protocol=os.environ.get("JEV_PROTOCOL", "typesafe"),
        min_confidence=float(os.environ.get("JEV_MIN_CONFIDENCE", ".9"))))
    if settings_path().exists():
        value = Settings.model_validate_json(settings_path().read_text())
    return value


def update_settings(patch: dict):
    if set(patch) - {"actor", "planner", "jev"}:
        raise ValueError("unknown provider")
    value = load_settings().model_dump()
    for name, fields in patch.items():
        if not isinstance(fields, dict):
            raise ValueError("provider settings must be objects")
        if "base_url" in fields and not isinstance(fields["base_url"], str):
            raise ValueError("base_url must be a string")
        if ("base_url" in fields and fields["base_url"].rstrip("/") != value[name]["base_url"].rstrip("/")
                and "api_key" not in fields):
            value[name]["api_key"] = ""  # do not forward a retained key to a different endpoint
        value[name].update(fields)
    return Settings.model_validate(value)


def save_settings(value):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(temp, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value.model_dump(), f)
    temp.replace(path)
