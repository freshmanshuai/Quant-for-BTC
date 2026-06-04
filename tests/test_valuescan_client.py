import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch


class ValuescanClientTest(unittest.TestCase):
    def test_post_headers_sign_timestamp_plus_exact_raw_body(self):
        from serve.valuescan_client import ValuescanClient

        client = ValuescanClient(
            api_key="ak_test",
            secret_key="sk_test",
            base_url="https://api.valuescan.ai/api",
        )
        raw_body = '{"search":"BTC"}'

        headers = client.build_post_headers(raw_body, timestamp="1775734240000")

        expected = hmac.new(
            b"sk_test",
            b'1775734240000{"search":"BTC"}',
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(headers["X-API-KEY"], "ak_test")
        self.assertEqual(headers["X-TIMESTAMP"], "1775734240000")
        self.assertEqual(headers["X-SIGN"], expected)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Accept"], "*/*")

    def test_json_body_is_compact_and_preserves_field_order(self):
        from serve.valuescan_client import ValuescanClient

        client = ValuescanClient(api_key="ak", secret_key="sk")

        raw_body = client.json_body({"page": 1, "pageSize": 10})

        self.assertEqual(raw_body, '{"page":1,"pageSize":10}')

    def test_missing_credentials_raise_clear_error(self):
        from serve.valuescan_client import ValuescanClient, ValuescanConfigError

        with patch.dict(os.environ, {}, clear=True):
            client = ValuescanClient()

        with self.assertRaisesRegex(ValuescanConfigError, "VS_OPEN_API_KEY"):
            client.build_post_headers("{}")

    def test_post_uses_signed_headers_and_raw_body(self):
        from serve.valuescan_client import ValuescanClient

        calls = []

        def transport(url, headers, body, timeout):
            calls.append((url, headers, body, timeout))
            return {"code": 200, "message": "success", "data": [{"id": 1}]}

        client = ValuescanClient(
            api_key="ak",
            secret_key="sk",
            base_url="https://api.valuescan.ai/api",
            transport=transport,
        )

        result = client.post("/open/v1/vs-token/list", {"search": "BTC"})

        self.assertEqual(result["data"], [{"id": 1}])
        self.assertEqual(calls[0][0], "https://api.valuescan.ai/api/open/v1/vs-token/list")
        self.assertEqual(calls[0][2], b'{"search":"BTC"}')
        self.assertIn("X-SIGN", calls[0][1])

    def test_build_signal_stream_url_signs_timestamp_and_nonce(self):
        from serve.valuescan_client import ValuescanClient

        client = ValuescanClient(
            api_key="ak",
            secret_key="sk",
            stream_base_url="https://stream.valuescan.ai",
        )

        url = client.build_stream_url(
            "signal",
            timestamp="1775734240000",
            nonce="abc123",
            tokens="1,2",
        )

        expected_sign = hmac.new(
            b"sk",
            b"1775734240000abc123",
            hashlib.sha256,
        ).hexdigest()
        self.assertTrue(url.startswith("https://stream.valuescan.ai/stream/signal/subscribe?"))
        self.assertIn("apiKey=ak", url)
        self.assertIn("timestamp=1775734240000", url)
        self.assertIn("nonce=abc123", url)
        self.assertIn("tokens=1%2C2", url)
        self.assertIn("sign=" + expected_sign, url)


if __name__ == "__main__":
    unittest.main()
