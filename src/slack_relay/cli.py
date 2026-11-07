from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from importlib import resources

import httpx

from . import __version__
from .config import ConfigError, Settings
from .signature import sign

SAMPLE_EVENTS = ("push", "pull_request", "issues", "release", "workflow_run")


def load_sample(event: str) -> bytes:
    return resources.files("slack_relay.samples").joinpath(f"{event}.json").read_bytes()


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from .app import create_app

    mode = "DRY RUN (no SLACK_WEBHOOK_URL)" if settings.dry_run else "posting to Slack"
    logging.getLogger("slack_relay").info(
        "listening on http://%s:%d/webhooks/github, %s", args.host, args.port, mode
    )
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_send_sample(args: argparse.Namespace, settings: Settings) -> int:
    body = load_sample(args.event)
    secret = "wrong-secret" if args.bad_signature else settings.github_secret
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": args.event,
        "X-GitHub-Delivery": args.delivery_id or str(uuid.uuid4()),
        "X-Hub-Signature-256": sign(secret, body),
    }
    resp = httpx.post(args.url, content=body, headers=headers, timeout=10)
    print(f"{resp.status_code} {resp.text}")
    return 0 if resp.is_success else 1


def cmd_retry_failed(args: argparse.Namespace, settings: Settings) -> int:
    from .app import Relay
    from .slack import SlackClient
    from .store import DeliveryStore

    if settings.dry_run:
        print("SLACK_WEBHOOK_URL is not set; nothing to retry against.", file=sys.stderr)
        return 1
    relay = Relay(
        settings,
        DeliveryStore(settings.db_path),
        SlackClient(settings.slack_webhook_url, max_attempts=settings.max_attempts),
    )
    print(json.dumps(relay.retry_failed() or {"failed": 0}))
    return 0


def cmd_deliveries(args: argparse.Namespace, settings: Settings) -> int:
    from .store import DeliveryStore

    for d in DeliveryStore(settings.db_path).recent(args.limit):
        error = f"  {d.last_error}" if d.last_error else ""
        print(f"{d.received_at}  {d.status:<9} {d.event:<13} {d.id}{error}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="slack-relay", description="Relay GitHub webhooks to Slack.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the webhook receiver")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("send-sample", help="POST a signed sample event to a running relay")
    s.add_argument("event", choices=SAMPLE_EVENTS)
    s.add_argument("--url", default="http://127.0.0.1:8080/webhooks/github")
    s.add_argument("--delivery-id", help="reuse an id to test duplicate handling")
    s.add_argument("--bad-signature", action="store_true", help="sign with the wrong secret")
    s.set_defaults(func=cmd_send_sample)

    s = sub.add_parser("retry-failed", help="re-send deliveries that failed")
    s.set_defaults(func=cmd_retry_failed)

    s = sub.add_parser("deliveries", help="show the delivery log")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_deliveries)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    return args.func(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
