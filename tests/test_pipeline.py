import sys
import os
import time
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main


class TokenBucketTests(unittest.TestCase):
    def test_starts_full(self):
        bucket = main.TokenBucket(rate=10, capacity=10)
        self.assertEqual(bucket.tokens, 10)

    def test_acquire_drains_tokens(self):
        bucket = main.TokenBucket(rate=10, capacity=5)
        for _ in range(5):
            bucket.acquire()
        self.assertLess(bucket.tokens, 1)

    def test_blocks_until_refill(self):
        bucket = main.TokenBucket(rate=100, capacity=1)
        bucket.acquire()  # drains the only token
        start = time.monotonic()
        bucket.acquire()  # has to wait for a refill this time
        elapsed = time.monotonic() - start
        self.assertGreater(elapsed, 0)


class SendRequestTests(unittest.TestCase):
    def setUp(self):
        self.bucket = main.TokenBucket(rate=1000, capacity=1000)
        self.headers = {"Authorization": "Bearer test", "Content-Type": "application/json"}
        self.row = {"user_id": "usr_1", "code": "code_1"}

    @patch("main.urllib.request.urlopen")
    def test_success_returns_status_code(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = main.send_request("http://fake", self.headers, self.row, self.bucket)
        self.assertEqual(result, "201")

    @patch("main.urllib.request.urlopen")
    def test_retries_on_5xx_then_succeeds(self, mock_urlopen):
        fail = urllib.error.HTTPError("http://fake", 503, "Service Unavailable", {}, None)

        success_resp = MagicMock()
        success_resp.status = 201
        success_cm = MagicMock()
        success_cm.__enter__.return_value = success_resp

        mock_urlopen.side_effect = [fail, success_cm]

        with patch("main.time.sleep"):
            result = main.send_request("http://fake", self.headers, self.row, self.bucket)

        self.assertEqual(result, "201")
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("main.urllib.request.urlopen")
    def test_gives_up_after_max_retries(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://fake", 503, "Service Unavailable", {}, None
        )

        with patch("main.time.sleep"):
            result = main.send_request("http://fake", self.headers, self.row, self.bucket)

        self.assertEqual(result, "503")
        self.assertEqual(mock_urlopen.call_count, main.MAX_RETRIES)

    @patch("main.urllib.request.urlopen")
    def test_does_not_retry_401(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://fake", 401, "Unauthorized", {}, None
        )

        result = main.send_request("http://fake", self.headers, self.row, self.bucket)

        self.assertEqual(result, "401")
        self.assertEqual(mock_urlopen.call_count, 1)


class LoadTokenTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_token_exits(self):
        with self.assertRaises(SystemExit):
            main.load_token()

    @patch.dict(os.environ, {"BEARER_TOKEN": '  "abc123"  '})
    def test_strips_whitespace_and_quotes(self):
        self.assertEqual(main.load_token(), "abc123")


if __name__ == "__main__":
    unittest.main()