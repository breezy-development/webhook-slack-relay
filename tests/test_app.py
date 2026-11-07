import httpx

from slack_relay.config import ConfigError, Settings

from .conftest import FakeSlack, post_event, sample

import pytest


def relay_store(client):
    return client.app.state.relay.store


def test_healthz_reports_mode(make_client):
    body = make_client().get("/healthz").json()
    assert body["ok"] and body["dry_run"]


def test_valid_push_is_delivered_to_slack(make_client, fake_slack):
    client = make_client(fake_slack)
    resp = post_event(client, "push", sample("push"))
    assert resp.status_code == 202 and resp.json() == {"status": "queued"}
    assert fake_slack.messages[0]["text"] == "2 new commits pushed to main in acme/storefront"
    d = relay_store(client).get("d-1")
    assert (d.status, d.attempts) == ("delivered", 1)


def test_bad_signature_is_rejected_and_not_recorded(make_client, fake_slack):
    client = make_client(fake_slack)
    resp = post_event(client, "push", sample("push"), secret="wrong")
    assert resp.status_code == 401
    assert fake_slack.requests == []
    assert relay_store(client).get("d-1") is None


def test_missing_headers_are_rejected(make_client):
    resp = make_client().post("/webhooks/github", content=b"{}")
    assert resp.status_code == 422


def test_redelivery_is_ignored(make_client, fake_slack):
    client = make_client(fake_slack)
    post_event(client, "push", sample("push"), delivery="same")
    resp = post_event(client, "push", sample("push"), delivery="same")
    assert resp.status_code == 200 and resp.json() == {"status": "duplicate"}
    assert len(fake_slack.requests) == 1


def test_ping_and_disabled_events(make_client, fake_slack):
    client = make_client(fake_slack, events=frozenset({"push"}))
    assert post_event(client, "ping", {"zen": "hi"}).json() == {"status": "pong"}
    assert post_event(client, "issues", sample("issues"), delivery="d-2").json()["status"] == "ignored"
    assert fake_slack.requests == []


def test_uninteresting_action_is_logged_as_skipped(make_client, fake_slack):
    client = make_client(fake_slack)
    resp = post_event(client, "pull_request", sample("pull_request") | {"action": "labeled"})
    assert resp.json() == {"status": "skipped"}
    assert relay_store(client).get("d-1").status == "skipped"
    assert fake_slack.requests == []


def test_malformed_payload_returns_400(make_client):
    client = make_client()
    assert post_event(client, "push", b"not json").status_code == 400
    resp = post_event(client, "pull_request", {"action": "opened"}, delivery="d-2")
    assert resp.status_code == 400
    assert relay_store(client).get("d-2") is None


def test_dry_run_records_without_sending(make_client):
    client = make_client()
    post_event(client, "release", sample("release"))
    assert relay_store(client).get("d-1").status == "dry_run"


def test_failed_delivery_is_kept_and_retry_succeeds(make_client):
    fake = FakeSlack(*[httpx.Response(500)] * 4)
    client = make_client(fake)
    post_event(client, "issues", sample("issues"))
    d = relay_store(client).get("d-1")
    assert (d.status, d.attempts) == ("failed", 4)
    assert "HTTP 500" in d.last_error

    assert client.app.state.relay.retry_failed() == {"delivered": 1}
    d = relay_store(client).get("d-1")
    assert (d.status, d.attempts, d.last_error) == ("delivered", 5, None)


def test_settings_from_env():
    s = Settings.from_env({"GITHUB_WEBHOOK_SECRET": "x", "RELAY_EVENTS": "push, issues"})
    assert s.dry_run and s.events == {"push", "issues"}
    with pytest.raises(ConfigError):
        Settings.from_env({})
    with pytest.raises(ConfigError):
        Settings.from_env({"GITHUB_WEBHOOK_SECRET": "x", "SLACK_WEBHOOK_URL": "http://evil.example"})
