import sys
import csv
import time
import json
import urllib.request
import urllib.error
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.5  # seconds, doubles each retry
WORKERS = 20


def load_env_file(path=".env"):
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Real environment variables always win — this only fills in gaps, it
    doesn't override anything you've already set in the shell.
    """
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


class TokenBucket:
    """Classic token bucket: refills `rate` tokens/sec, holds at most `capacity`.

    Using this instead of sleeping between fixed-size batches means we
    actually saturate the rate limit instead of leaving gaps in the timeline.
    """

    def __init__(self, rate, capacity):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_refill = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return

            time.sleep(0.01)


def send_request(api_url, headers, row, bucket):
    bucket.acquire()

    payload = json.dumps({"user_id": row["user_id"], "code": row["code"]}).encode("utf-8")

    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return str(resp.status)
        except urllib.error.HTTPError as e:
            # only retry server-side failures, not auth/rate-limit responses
            if e.code >= 500 and attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
                continue
            return str(e.code)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
                continue
            return f"error: {type(e).__name__}"

    return "error: max_retries_exceeded"


def load_token():
    token = os.environ.get("BEARER_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        print("Error: BEARER_TOKEN environment variable is missing.")
        print("Set it before running, e.g. $env:BEARER_TOKEN='your-token'")
        sys.exit(1)
    return token


def run_pipeline(csv_path):
    api_url = os.environ.get("API_ENDPOINT", "http://localhost:8080")
    token = load_token()

    if not os.path.exists(csv_path):
        print(f"Error: File '{csv_path}' not found.")
        sys.exit(1)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    with open(csv_path, mode="r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"[*] Starting ingestion for {len(rows)} records against {api_url}...")

    bucket = TokenBucket(rate=WORKERS, capacity=WORKERS)
    response_counts = {}
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(send_request, api_url, headers, row, bucket) for row in rows]

        completed = 0
        for future in as_completed(futures):
            code = future.result()
            response_counts[code] = response_counts.get(code, 0) + 1
            completed += 1
            if completed % WORKERS == 0 or completed == len(rows):
                print(f"[*] Processed {completed}/{len(rows)} records...")

    total_time = round(time.time() - start_time, 3)

    summary = {
        "responses": response_counts,
        "time_taken": total_time,
    }

    print("\n--- FINAL REPORT ---")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <path_to_csv>")
        sys.exit(1)

    load_env_file()
    run_pipeline(sys.argv[1])