import copy

import pytest

from slack_relay.formatters import MAX_COMMITS, esc, first_line, format_event

from .conftest import sample


def body_text(msg: dict) -> str:
    return msg["blocks"][0]["text"]["text"]


def test_push_lists_commits_with_links_and_escapes_text():
    msg = format_event("push", sample("push"))
    assert msg["text"] == "2 new commits pushed to main in acme/storefront"
    body = body_text(msg)
    assert "`main`" in body
    assert "<https://github.com/acme/storefront/commit/a3f9c2e1b7d04e8f9a6b5c4d3e2f1a0b9c8d7e6f|a3f9c2e>" in body
    assert "Add CSV export to the orders page — danalee" in body  # first line only
    assert "&lt;$1 items" in body  # "<" escaped for Slack mrkdwn
    assert msg["blocks"][0]["accessory"]["url"].startswith("https://github.com/acme/storefront/compare/")
    assert "acme/storefront" in msg["blocks"][1]["elements"][0]["text"]


def test_mentions_in_user_content_are_neutralised():
    p = sample("push")
    p["commits"][0]["message"] = "Deploy now <!channel> <@U123>"
    body = body_text(format_event("push", p))
    assert "<!channel>" not in body and "<@U123>" not in body
    assert "&lt;!channel&gt;" in body


def test_push_truncates_long_commit_lists():
    p = sample("push")
    p["commits"] = [copy.deepcopy(p["commits"][0]) for _ in range(MAX_COMMITS + 3)]
    assert "…and 3 more" in body_text(format_event("push", p))


@pytest.mark.parametrize("change", [{"commits": []}, {"deleted": True}])
def test_push_without_commits_or_branch_delete_is_skipped(change):
    p = sample("push") | change
    assert format_event("push", p) is None


def test_pull_request_opened_includes_branches_stats_and_summary():
    msg = format_event("pull_request", sample("pull_request"))
    body = body_text(msg)
    assert msg["text"] == "Pull request opened: #42 Nightly inventory sync from the supplier API"
    assert "`feature/inventory-sync` → `main`" in body
    assert "+214 −18 in 7 files" in body
    assert "> Pulls stock levels every night" in body


def test_pull_request_merged_vs_closed():
    p = sample("pull_request") | {"action": "closed"}
    p["pull_request"] = p["pull_request"] | {"merged": True}
    assert format_event("pull_request", p)["text"].startswith("Pull request merged")
    p["pull_request"]["merged"] = False
    assert format_event("pull_request", p)["text"].startswith("Pull request closed")


def test_pull_request_noise_is_skipped():
    assert format_event("pull_request", sample("pull_request") | {"action": "labeled"}) is None


def test_issue_with_labels():
    body = body_text(format_event("issues", sample("issues")))
    assert "Issue *opened*" in body
    assert "`bug`, `priority: high`" in body


def test_release_only_when_published():
    assert format_event("release", sample("release"))["text"] == "Release published: v2.4.0 — Faster checkout"
    assert format_event("release", sample("release") | {"action": "created"}) is None


def test_workflow_run_only_failures():
    msg = format_event("workflow_run", sample("workflow_run"))
    assert msg["text"] == "CI failed: tests #318 on feature/inventory-sync"
    ok = sample("workflow_run")
    ok["workflow_run"]["conclusion"] = "success"
    assert format_event("workflow_run", ok) is None


def test_unknown_event_returns_none():
    assert format_event("star", {}) is None


def test_helpers():
    assert esc("a & <b>") == "a &amp; &lt;b&gt;"
    assert first_line("\n  hello\nworld") == "hello"
    assert first_line(None) == ""
    assert len(first_line("x" * 200, limit=10)) == 10
