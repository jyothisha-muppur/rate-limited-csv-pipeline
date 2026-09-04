# Rate-Limited CSV Ingestion Pipeline

A small CLI tool that reads a CSV of records and pushes them to an HTTP API as
JSON, while staying under a server-side rate limit. Built with only the
Python standard library — no `requests`, no `aiohttp`, nothing to `pip
install`.

Comes with a mock API server so you can try it out without any real backend.

## How it works

- `main.py` reads the CSV, builds a JSON payload per row, and fires it off as
  a `POST` with a Bearer token in the `Authorization` header.
- Requests are rate-limited on the client side using a token bucket (20
  tokens/sec by default), so it doesn't outrun the server's limit.
- Failed requests get retried with exponential backoff, but only for
  transient stuff (5xx, connection errors) — a 401 or a bad request isn't
  going to fix itself on retry, so those fail immediately.
- At the end it prints a summary: how many of each response code came back,
  and total time taken.

## Running it

You need Python 3.8+, that's it.

**Terminal 1** — start the mock server:

```bash
python mock_server.py
```

**Terminal 2** — set your token and run the pipeline:

```bash
export BEARER_TOKEN=whatever-token-you-want
python main.py data/sample_100.csv
```

(On Windows PowerShell: `$env:BEARER_TOKEN="whatever-token-you-want"`)

The mock server doesn't actually validate the token value — it just checks
that the `Authorization` header is present and starts with `Bearer `. That's
enough to demo the auth flow without needing real credentials.

You'll see output like:

```
[*] Starting ingestion for 100 records against http://localhost:8080...
[*] Processed 20/100 records...
[*] Processed 40/100 records...
...
--- FINAL REPORT ---
{
  "responses": {
    "201": 100
  },
  "time_taken": 4.982
}
```

## CSV format

`data/sample_100.csv` (or whatever file you point it at) needs two columns:

| Column      | Description                 |
|-------------|------------------------------|
| `user_id`   | Unique ID for the record     |
| `code`      | Some payload/verification code |

## Configuration

Both of these can be set as environment variables or in a `.env` file
(see `.env.example`):

- `BEARER_TOKEN` — required. The pipeline exits immediately if this isn't set.
- `API_ENDPOINT` — optional, defaults to `http://localhost:8080`.

Copy the example file and fill in your own values:

```bash
cp .env.example .env
```

Actual environment variables always take priority over `.env` — so you can
still override things at the shell without editing the file.

## Tests

```bash
python -m unittest discover tests
```

Covers the token bucket (fills, drains, blocks correctly) and the
request/retry logic (retries on 5xx, gives up after `MAX_RETRIES`, doesn't
retry on 401).

## Why a token bucket instead of just sleeping between batches

An earlier version of this just sent batches of 20 requests and slept for a
second between batches. That works, but it wastes time — if a batch finishes
in 0.3s, you're still sleeping the full remaining 0.7s before starting the
next one, even though you could've kept sending. A token bucket refills
continuously instead of in fixed chunks, so throughput stays closer to the
actual rate limit instead of the "burst, then idle" pattern.

## Known limitations

- The retry logic is per-request, not batched — if you're ingesting a huge
  file and want checkpointing/resume support, that's not here.
- The `.env` parser is intentionally minimal (no quoting edge cases, no
  multiline values, no variable interpolation). Fine for simple key/value
  config, not a replacement for `python-dotenv` if your needs get fancier.