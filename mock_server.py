import time
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Lock

RATE_LIMIT = 20
WINDOW_SIZE = 1.0

request_timestamps = []
timestamps_lock = Lock()


class RateLimitedHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return  # keep stdout clean, we don't need per-request access logs

    def do_POST(self):
        auth_header = self.headers.get('Authorization')

        if not auth_header or not auth_header.startswith("Bearer "):
            self._respond(401, {"error": "Unauthorized"})
            return

        if self._rate_limited():
            self._respond(429, {"error": "Rate limit exceeded"})
            return

        self._respond(201, {"status": "created", "id": "record-ingested"})

    def _rate_limited(self):
        global request_timestamps
        now = time.time()
        with timestamps_lock:
            request_timestamps = [t for t in request_timestamps if now - t < WINDOW_SIZE]

            if len(request_timestamps) >= RATE_LIMIT:
                return True

            request_timestamps.append(now)
            return False

    def _respond(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


def run(port=8080):
    httpd = ThreadingHTTPServer(('', port), RateLimitedHandler)
    print(f"[*] Mock Server active on http://localhost:{port} (Limit: {RATE_LIMIT} req/sec)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server stopped.")


if __name__ == '__main__':
    run()