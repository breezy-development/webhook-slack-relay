from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_EVENTS = ("push", "pull_request", "issues", "release", "workflow_run")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    github_secret: str
    slack_webhook_url: str | None = None
    db_path: str = "relay.db"
    events: frozenset[str] = field(default_factory=lambda: frozenset(DEFAULT_EVENTS))
    max_attempts: int = 4

    @property
    def dry_run(self) -> bool:
        return not self.slack_webhook_url

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        secret = env.get("GITHUB_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise ConfigError("GITHUB_WEBHOOK_SECRET is required (see .env.example)")
        url = env.get("SLACK_WEBHOOK_URL", "").strip() or None
        local = url and url.startswith(("http://127.0.0.1", "http://localhost"))
        if url and not (url.startswith("https://") or local):
            raise ConfigError("SLACK_WEBHOOK_URL must be an https:// URL")
        events = env.get("RELAY_EVENTS", "").strip()
        return cls(
            github_secret=secret,
            slack_webhook_url=url,
            db_path=env.get("RELAY_DB_PATH", "relay.db"),
            events=frozenset(e.strip() for e in events.split(",") if e.strip())
            if events
            else frozenset(DEFAULT_EVENTS),
            max_attempts=int(env.get("RELAY_MAX_ATTEMPTS", "4")),
        )
