"""Turn GitHub webhook payloads into Slack Block Kit messages.

Each formatter returns a Slack payload ({"text": fallback, "blocks": [...]}) or None when the
event isn't worth a notification (e.g. a pull request label change).
"""

from __future__ import annotations

from collections.abc import Callable

Payload = dict
Message = dict

MAX_COMMITS = 5


def format_event(event: str, payload: Payload) -> Message | None:
    formatter = FORMATTERS.get(event)
    return formatter(payload) if formatter else None


def esc(text: str) -> str:
    """Escape the three characters Slack mrkdwn treats specially."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url: str, label: str) -> str:
    return f"<{url}|{esc(label)}>"


def first_line(text: str | None, limit: int = 80) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


def message(text: str, body: str, context: str, button: tuple[str, str] | None = None) -> Message:
    section: dict = {"type": "section", "text": {"type": "mrkdwn", "text": body}}
    if button:
        label, url = button
        section["accessory"] = {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "url": url,
        }
    return {
        "text": text,
        "blocks": [section, {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]}],
    }


def repo_context(payload: Payload) -> str:
    repo = payload["repository"]
    sender = payload.get("sender", {}).get("login", "someone")
    return f"{link(repo['html_url'], repo['full_name'])} · by {esc(sender)}"


def format_push(p: Payload) -> Message | None:
    commits = p.get("commits") or []
    if not commits or p.get("deleted"):
        return None
    branch = p["ref"].removeprefix("refs/heads/")
    repo = p["repository"]["full_name"]
    noun = "commit" if len(commits) == 1 else "commits"
    lines = [
        f"• {link(c['url'], c['id'][:7])} {esc(first_line(c['message']))}"
        f" — {esc(c['author'].get('username') or c['author']['name'])}"
        for c in commits[:MAX_COMMITS]
    ]
    if len(commits) > MAX_COMMITS:
        lines.append(f"_…and {len(commits) - MAX_COMMITS} more_")
    header = f":arrow_up: *{len(commits)} new {noun}* pushed to `{esc(branch)}`"
    if p.get("forced"):
        header += " (force-push)"
    return message(
        text=f"{len(commits)} new {noun} pushed to {branch} in {repo}",
        body=header + "\n" + "\n".join(lines),
        context=repo_context(p),
        button=("Compare", p["compare"]),
    )


def format_pull_request(p: Payload) -> Message | None:
    pr = p["pull_request"]
    action = p["action"]
    if action == "closed":
        action, emoji = ("merged", ":tada:") if pr.get("merged") else ("closed", ":x:")
    elif action in ("opened", "reopened", "ready_for_review"):
        emoji = ":large_green_circle:"
    else:
        return None
    title = f"#{pr['number']} {pr['title']}"
    stats = f"+{pr.get('additions', 0)} −{pr.get('deletions', 0)} in {pr.get('changed_files', 0)} files"
    body = (
        f"{emoji} Pull request *{action}*: {link(pr['html_url'], title)}\n"
        f"`{esc(pr['head']['ref'])}` → `{esc(pr['base']['ref'])}` · {stats}"
    )
    if action in ("opened", "ready_for_review") and pr.get("body"):
        body += f"\n> {esc(first_line(pr['body'], 140))}"
    return message(
        text=f"Pull request {action}: {title}",
        body=body,
        context=repo_context(p),
        button=("View PR", pr["html_url"]),
    )


def format_issues(p: Payload) -> Message | None:
    if p["action"] not in ("opened", "closed", "reopened"):
        return None
    issue = p["issue"]
    emoji = {"opened": ":memo:", "closed": ":white_check_mark:", "reopened": ":recycle:"}[p["action"]]
    title = f"#{issue['number']} {issue['title']}"
    labels = ", ".join(f"`{esc(lbl['name'])}`" for lbl in issue.get("labels", []))
    body = f"{emoji} Issue *{p['action']}*: {link(issue['html_url'], title)}"
    if labels:
        body += f"\nLabels: {labels}"
    return message(
        text=f"Issue {p['action']}: {title}",
        body=body,
        context=repo_context(p),
        button=("View issue", issue["html_url"]),
    )


def format_release(p: Payload) -> Message | None:
    if p["action"] != "published":
        return None
    rel = p["release"]
    name = rel.get("name") or rel["tag_name"]
    kind = "Pre-release" if rel.get("prerelease") else "Release"
    return message(
        text=f"{kind} published: {name}",
        body=f":rocket: {kind} *{link(rel['html_url'], name)}* published (`{esc(rel['tag_name'])}`)",
        context=repo_context(p),
        button=("Release notes", rel["html_url"]),
    )


def format_workflow_run(p: Payload) -> Message | None:
    run = p["workflow_run"]
    if p["action"] != "completed" or run.get("conclusion") not in ("failure", "timed_out"):
        return None  # only failures are worth waking people up for
    title = f"{run['name']} #{run['run_number']}"
    return message(
        text=f"CI failed: {title} on {run['head_branch']}",
        body=(
            f":rotating_light: *CI {run['conclusion'].replace('_', ' ')}*: "
            f"{link(run['html_url'], title)} on `{esc(run['head_branch'])}`\n"
            f"Commit `{run['head_sha'][:7]}`: {esc(first_line(run.get('display_title')))}"
        ),
        context=repo_context(p),
        button=("View run", run["html_url"]),
    )


FORMATTERS: dict[str, Callable[[Payload], Message | None]] = {
    "push": format_push,
    "pull_request": format_pull_request,
    "issues": format_issues,
    "release": format_release,
    "workflow_run": format_workflow_run,
}
