from __future__ import annotations

import json
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from . import __version__
from .config import Settings
from .formatters import format_event
from .signature import verify
from .slack import SlackClient, SlackError
from .store import DeliveryStore

log = logging.getLogger("slack_relay")

MAX_BODY_BYTES = 5 * 1024 * 1024


class Relay:
    """Delivery logic shared by the HTTP app and the `retry-failed` command."""

    def __init__(self, settings: Settings, store: DeliveryStore, slack: SlackClient | None) -> None:
        self.settings = settings
        self.store = store
        self.slack = slack

    def deliver(self, delivery_id: str, message: dict) -> str:
        if self.slack is None:
            log.info("dry run %s: %s", delivery_id, message["text"])
            self.store.finish(delivery_id, "dry_run", 0)
            return "dry_run"
        try:
            attempts = self.slack.post(message)
        except SlackError as exc:
            log.error("delivery %s failed: %s", delivery_id, exc)
            self.store.finish(delivery_id, "failed", exc.attempts, str(exc))
            return "failed"
        log.info("delivered %s to Slack (%d attempt%s)", delivery_id, attempts, "s" * (attempts > 1))
        self.store.finish(delivery_id, "delivered", attempts)
        return "delivered"

    def retry_failed(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.store.by_status("failed"):
            result = self.deliver(d.id, d.message)
            counts[result] = counts.get(result, 0) + 1
        return counts


def create_app(settings: Settings, slack: SlackClient | None = None) -> FastAPI:
    store = DeliveryStore(settings.db_path)
    if slack is None and not settings.dry_run:
        slack = SlackClient(settings.slack_webhook_url, max_attempts=settings.max_attempts)
    relay = Relay(settings, store, slack)

    app = FastAPI(title="webhook-slack-relay", version=__version__, docs_url=None, redoc_url=None)
    app.state.relay = relay

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "dry_run": relay.slack is None, "events": sorted(settings.events)}

    @app.post("/webhooks/github", status_code=202)
    async def github_webhook(
        request: Request,
        background: BackgroundTasks,
        x_github_event: str = Header(...),
        x_github_delivery: str = Header(...),
        x_hub_signature_256: str | None = Header(None),
    ):
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "payload too large")
        if not verify(settings.github_secret, body, x_hub_signature_256):
            log.warning("rejected %s: bad signature", x_github_delivery)
            raise HTTPException(401, "invalid signature")

        if x_github_event == "ping":
            return {"status": "pong"}
        if x_github_event not in settings.events:
            return {"status": "ignored", "reason": f"event {x_github_event!r} not enabled"}

        try:
            payload = json.loads(body)
            message = format_event(x_github_event, payload)
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("rejected %s: malformed %s payload (%s)", x_github_delivery, x_github_event, exc)
            raise HTTPException(400, "malformed payload") from exc

        if not store.claim(x_github_delivery, x_github_event, message):
            log.info("duplicate %s ignored", x_github_delivery)
            return JSONResponse({"status": "duplicate"}, status_code=200)
        if message is None:
            action = payload.get("action")
            log.info("skipped %s (%s%s)", x_github_delivery, x_github_event, f".{action}" if action else "")
            return {"status": "skipped"}

        background.add_task(relay.deliver, x_github_delivery, message)
        log.info("accepted %s (%s): %s", x_github_delivery, x_github_event, message["text"])
        return {"status": "queued"}

    return app
