import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import arianet
from arianet import ErrorCode


class MockServer:
    """Answers each request with the next scripted reply and records it."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else ""
                server.seen.append({
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                })
                if not server.replies:
                    self.send_response(500)
                    self.end_headers()
                    return
                status, payload, headers = server.replies.pop(0)
                if status is None:  # drop the connection
                    self.connection.close()
                    return
                data = payload.encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def reply(status, body="{}", **headers):
    return (status, body, {k.replace("_", "-"): v for k, v in headers.items()})


class ClientTest(unittest.TestCase):
    def make(self, *replies, **kwargs):
        self.server = MockServer(replies)
        self.addCleanup(self.server.close)
        client = arianet.Client("tok_123", base_url=self.server.url, **kwargs)
        self.waits = []
        client._sleep = self.waits.append
        return client

    def test_auth_headers_path_and_query(self):
        client = self.make(reply(200, '{"data": [{"id": 1}], "meta": {}}'))
        result = client.cloud.list_servers(page=2, label_selector="env=prod")
        seen = self.server.seen[0]
        self.assertEqual(seen["headers"]["authorization"], "Bearer tok_123")
        self.assertTrue(seen["headers"]["user-agent"].startswith("arianet-python/"))
        self.assertEqual(seen["method"], "GET")
        self.assertEqual(seen["path"], "/cloud/v1/servers?label_selector=env%3Dprod&page=2")
        self.assertEqual(result["data"][0]["id"], 1)

    def test_token_from_environment(self):
        self.server = MockServer([reply(200, '{"success": true, "data": {}}')])
        self.addCleanup(self.server.close)
        with mock.patch.dict(os.environ, {"ARIANET_TOKEN": "env_tok"}):
            client = arianet.Client(base_url=self.server.url)
        client.core.get_me()
        self.assertEqual(self.server.seen[0]["headers"]["authorization"], "Bearer env_tok")

    def test_path_params_are_escaped(self):
        client = self.make(reply(200))
        client.core.get_invoice("INV/1 2")
        self.assertEqual(self.server.seen[0]["path"], "/api/v1/invoices/INV%2F1%202")

    def test_retry_on_429_honors_retry_after(self):
        client = self.make(reply(429, '{"code": "rate_limited", "message": "slow down"}', Retry_After="7"), reply(200))
        client.sms.send_message({"to": ["0912"]})
        self.assertEqual(len(self.server.seen), 2)
        self.assertEqual(self.waits, [7.0])
        self.assertEqual(self.server.seen[0]["body"], self.server.seen[1]["body"])

    def test_retry_on_429_uses_ratelimit_reset(self):
        client = self.make(reply(429, RateLimit_Reset="3"), reply(200))
        client.cloud.list_datacenters()
        self.assertEqual(self.waits, [3.0])

    def test_retry_after_longer_than_max_raises(self):
        client = self.make(reply(429, '{"success": false, "error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many"}}', Retry_After="3600"))
        with self.assertRaises(arianet.RateLimitError) as ctx:
            client.core.list_regions()
        self.assertEqual(ctx.exception.code, ErrorCode.RATE_LIMIT_EXCEEDED)
        self.assertEqual(ctx.exception.retry_after, 3600.0)
        self.assertEqual(self.waits, [])
        self.assertEqual(len(self.server.seen), 1)

    def test_retries_are_bounded(self):
        client = self.make(reply(503), reply(503), reply(503), max_retries=2)
        with self.assertRaises(arianet.InternalServerError):
            client.cloud.list_volumes()
        self.assertEqual(len(self.server.seen), 3)

    def test_unsafe_request_not_retried_on_503(self):
        client = self.make(reply(503, '{"error": "busy", "code": "core_unavailable"}'))
        with self.assertRaises(arianet.APIError) as ctx:
            client.cloud.create_volume({"size": 10})
        self.assertEqual(ctx.exception.code, ErrorCode.CORE_UNAVAILABLE)
        self.assertEqual(len(self.server.seen), 1)

    def test_idempotent_operation_keeps_key_across_retries(self):
        client = self.make(reply(502), reply(202, '{"success": true, "data": {"id": 9}}'))
        client.core.create_server({"plan_id": 1})
        keys = [s["headers"].get("idempotency-key") for s in self.server.seen]
        self.assertEqual(len(keys), 2)
        self.assertTrue(keys[0])
        self.assertEqual(keys[0], keys[1])

    def test_explicit_idempotency_key(self):
        client = self.make(reply(200))
        client.cloud.create_volume({}, idempotency_key="k-1")
        self.assertEqual(self.server.seen[0]["headers"]["idempotency-key"], "k-1")

    def test_connection_error_retried_for_reads(self):
        client = self.make(reply(None), reply(200))
        client.cloud.list_images()
        self.assertEqual(len(self.server.seen), 2)

    def test_error_shapes(self):
        cases = [
            (402, '{"success": false, "error": {"code": "INSUFFICIENT_BALANCE", "message": "Not enough balance"}}',
             arianet.PaymentRequiredError, ErrorCode.INSUFFICIENT_BALANCE, "Not enough balance", None),
            (403, '{"error": "Verify your identity", "code": "identity_needed", "reason": "identity_hold"}',
             arianet.PermissionDeniedError, ErrorCode.IDENTITY_NEEDED, "Verify your identity", "identity_hold"),
            (404, '{"code": "not_found", "message": "No such server"}',
             arianet.NotFoundError, ErrorCode.NOT_FOUND, "No such server", None),
            (400, "<html>bad</html>", arianet.BadRequestError, "unexpected_response", "request failed with HTTP 400", None),
        ]
        for status, body, cls, code, message, reason in cases:
            with self.subTest(status=status):
                client = self.make(reply(status, body, X_Request_Id="req-1"))
                with self.assertRaises(cls) as ctx:
                    client.hosting.list_accounts()
                err = ctx.exception
                self.assertEqual((err.status_code, err.code, err.message, err.reason, err.request_id),
                                 (status, code, message, reason, "req-1"))

    def test_success_false_with_200_is_an_error(self):
        client = self.make(reply(200, '{"success": false, "error": {"code": "NO_DEFAULT_WALLET", "message": "No wallet"}}'))
        with self.assertRaises(arianet.APIError) as ctx:
            client.core.get_balance()
        self.assertEqual(ctx.exception.code, ErrorCode.NO_DEFAULT_WALLET)

    def test_region_header(self):
        client = self.make(reply(200), reply(200))
        client.regional_vps.with_region("iran-1").list_servers()
        client.regional_vps.list_servers(headers={"Arianet-Region": "iran-2"})
        self.assertEqual(self.server.seen[0]["headers"]["arianet-region"], "iran-1")
        self.assertEqual(self.server.seen[1]["headers"]["arianet-region"], "iran-2")

    def test_redirect_is_not_followed(self):
        other = MockServer([])
        self.addCleanup(other.close)
        client = self.make(reply(302, "", Location=other.url + "/steal"))
        with self.assertRaises(arianet.APIError) as ctx:
            client.core.get_me()
        self.assertEqual(ctx.exception.status_code, 302)
        self.assertEqual(other.seen, [])

    def test_base_url_must_be_https(self):
        with self.assertRaises(arianet.ArianetError):
            arianet.Client("t", base_url="http://api.example.com")

    def test_request_for_ungenerated_paths(self):
        client = self.make(reply(200, '{"ok": true}'))
        self.assertEqual(client.request("GET", "/cloud/v1/something-new", query={"a": True}), {"ok": True})
        self.assertEqual(self.server.seen[0]["path"], "/cloud/v1/something-new?a=true")

    def test_body_is_json(self):
        client = self.make(reply(201))
        client.cloud.create_volume({"name": "data", "size": 10})
        self.assertEqual(json.loads(self.server.seen[0]["body"]), {"name": "data", "size": 10})
        self.assertEqual(self.server.seen[0]["headers"]["content-type"], "application/json")


if __name__ == "__main__":
    unittest.main()
