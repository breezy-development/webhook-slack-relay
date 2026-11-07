import json
from importlib import resources

import httpx
import pytest
from fastapi.testclient import TestClient

from slack_relay.app import create_app
from slack_relay.config import Settings
from slack_relay.signature import sign
from slack_relay.slack import SlackClient

SECRET = "test-secret"
SLACK_URL = "https://hooks.slack.test/services/T000/B000/XXXX"


def sample(event: str) -> dict:
    return json.loads(resources.files("slack_relay.samples").joinpath(f"{event}.json").read_text())


class FakeSlack:
    """httpx transport that replays scripted responses and records requests."""

    def __init__(self, *responses: httpx.Response | Exception):
        self.script = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        nxt = self.script.pop(0) if self.script else httpx.Response(200, text="ok")
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    @property
    def messages(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def fake_slack():
    return FakeSlack()


@pytest.fixture
def make_client(tmp_path):
    def _make(fake: FakeSlack | None = None, **overrides) -> TestClient:
        settings = Settings(
            github_secret=SECRET,
            slack_webhook_url=None if fake is None else SLACK_URL,
            db_path=str(tmp_path / "relay.db"),
            **overrides,
        )
        slack = (
            SlackClient(SLACK_URL, transport=httpx.MockTransport(fake), sleep=lambda s: None)
            if fake is not None
            else None
        )
        return TestClient(create_app(settings, slack=slack))

    return _make


def post_event(client: TestClient, event: str, payload: dict | bytes, delivery: str = "d-1", secret=SECRET):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": sign(secret, body),
        },
    )
