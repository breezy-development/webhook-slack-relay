"""Local stand-in for a Slack incoming webhook, for demos and manual testing.

Answers the first request with 429 (Retry-After: 1) to show the relay's retry logic, then 200.
Prints each message's fallback text.

    python scripts/mock_slack.py 9999
    SLACK_WEBHOOK_URL=http://127.0.0.1:9999/hook slack-relay serve
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

state = {"requests": 0}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        state["requests"] += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if state["requests"] == 1:
            self.send_response(429)
            self.send_header("Retry-After", "1")
            self.end_headers()
            self.wfile.write(b"rate_limited")
            print("mock-slack: 429 rate_limited", flush=True)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
        print(f"mock-slack: 200 {body['text']!r}", flush=True)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
