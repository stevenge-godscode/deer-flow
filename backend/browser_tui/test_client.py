import unittest
from unittest.mock import Mock

import httpx

from browser_tui.client import (
    AccessDenied,
    Binding,
    GatewayClient,
    decode_sse,
    session_headers,
    validate_context,
)


class BrowserTuiContractTests(unittest.TestCase):
    def test_cookie_not_url_or_extra_identity(self):
        headers = session_headers(
            "access_token=synthetic-test; csrf_token=test-csrf; admin=1; other=value",
            "https://deerflow.test",
        )
        self.assertEqual(headers["Cookie"], "access_token=synthetic-test; csrf_token=test-csrf")
        self.assertEqual(headers["X-CSRF-Token"], "test-csrf")
        with self.assertRaises(AccessDenied):
            session_headers("admin=1", "https://deerflow.test")

    def test_context_allowlist(self):
        self.assertEqual(
            validate_context({"mode": "ultra", "model_name": "a"}),
            {
                "thinking_enabled": True,
                "is_plan_mode": True,
                "subagent_enabled": True,
                "model_name": "a",
            },
        )
        for context in [
            {"user_id": "victim"},
            {"agent_name": "other"},
            {"secrets": "x"},
            {"mode": "invalid"},
            {"model_name": [1]},
            {"__internal": True},
        ]:
            with self.subTest(context=context), self.assertRaises(AccessDenied):
                validate_context(context)

    def test_sse_multiline_heartbeat_and_eof(self):
        frames = list(
            decode_sse(
                iter(
                    [
                        ": heartbeat",
                        "",
                        "event: messages-tuple",
                        'data: [{"type":"ai",',
                        'data: "content":"ok"}, {}]',
                        "",
                        "event: end",
                        "data: {}",
                    ]
                )
            )
        )
        self.assertEqual(
            frames,
            [("messages-tuple", [{"type": "ai", "content": "ok"}, {}]), ("end", {})],
        )

    def test_gateway_stream_contract_and_native_events(self):
        import json

        bodies = []

        def handle(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text='event: messages\ndata: [{"type":"AIMessageChunk","content":"ok","id":"reply"}, {}]\n\nevent: end\ndata: {}\n\n')

        c = GatewayClient("http://gateway.test", {}, Binding("user", "owned", None, "__default__", {}, True))
        c.http.close()
        c.http = httpx.Client(base_url="http://gateway.test", transport=httpx.MockTransport(handle))
        c.revalidate = Mock(return_value={"permissions": ["runs:create", "runs:cancel"]})
        try:
            events = list(c.stream("hello", thread_id="owned"))
            self.assertEqual(events[0].type, "messages-tuple")
            self.assertEqual(events[0].data["type"], "ai")
            self.assertEqual(events[0].data["content"], "ok")
            self.assertNotIn("if_not_exists", bodies[0])
        finally:
            c.close()

    def test_cross_thread_is_rejected_before_http(self):
        c = GatewayClient(
            "http://gateway.test",
            {},
            Binding("user", "owned", None, "__default__", {}, True),
        )
        try:
            with self.assertRaises(AccessDenied):
                list(c.stream("hello", thread_id="other"))
        finally:
            c.close()

    def test_gateway_denials_are_not_success(self):
        for status in [401, 403, 404, 409, 500]:
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                GatewayClient.check(httpx.Response(status))

    def test_scope_and_permissions_are_revalidated(self):
        c = GatewayClient(
            "http://gateway.test",
            {},
            Binding("user", "owned", "project", "agent", {}, True),
        )
        c.request = Mock(
            side_effect=[
                {"id": "user", "permissions": ["threads:read"]},
                {"metadata": {"deerflow_project_id": "other"}},
            ]
        )
        try:
            with self.assertRaises(AccessDenied):
                c.revalidate()
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
