"""Slack incoming-webhook client with retries.

Retries on network errors, 429 (honouring Retry-After) and 5xx with exponential backoff.
Other 4xx responses (bad URL, revoked webhook, invalid blocks) fail immediately because
retrying cannot fix them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

log = logging.getLogger(__name__)


class SlackError(Exception):
    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts


class SlackClient:
    def __init__(
        self,
        webhook_url: str,
        max_attempts: int = 4,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.webhook_url = webhook_url
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep
        self._http = httpx.Client(timeout=10.0, transport=transport)

    def post(self, message: dict) -> int:
        """Send a message; returns the number of attempts it took."""
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self._http.post(self.webhook_url, json=message)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc.__class__.__name__}"
                delay = self._backoff(attempt)
            else:
                if resp.status_code == 200:
                    return attempt
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if resp.status_code == 429:
                    delay = self._retry_after(resp, attempt)
                elif resp.status_code >= 500:
                    delay = self._backoff(attempt)
                else:
                    raise SlackError(last_error, attempt)
            if attempt < self.max_attempts:
                log.warning("slack attempt %d failed (%s); retrying in %.1fs", attempt, last_error, delay)
                self._sleep(delay)
        raise SlackError(f"gave up after {self.max_attempts} attempts: {last_error}", self.max_attempts)

    def _backoff(self, attempt: int) -> float:
        return min(self.base_delay * 2 ** (attempt - 1), self.max_delay)

    def _retry_after(self, resp: httpx.Response, attempt: int) -> float:
        try:
            return min(float(resp.headers["Retry-After"]), self.max_delay)
        except (KeyError, ValueError):
            return self._backoff(attempt)
