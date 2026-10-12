import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from browser_tui.server import BrowserServer


class BrowserHostingGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = BrowserServer("http://gateway.test", "https://deerflow.test")
        self.client = TestClient(TestServer(await self.server._make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_no_login_page_denied(self):
        response = await self.client.get("/tui/owned/")
        self.assertEqual(response.status, 403)
        self.assertEqual(len(self.server.active), 0)

    async def test_foreign_origin_denied_before_gateway(self):
        with patch("browser_tui.server.GatewayClient") as gateway:
            response = await self.client.get(
                "/tui/owned/",
                headers={
                    "Origin": "https://attacker.test",
                    "Cookie": "access_token=synthetic",
                },
            )
            self.assertEqual(response.status, 403)
            gateway.assert_not_called()

    async def test_cross_site_page_denied(self):
        response = await self.client.get("/tui/owned/", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status, 403)

    async def test_websocket_requires_exact_origin_and_session(self):
        for headers in [
            {},
            {"Origin": "https://attacker.test"},
            {"Origin": "https://deerflow.test"},
        ]:
            with self.subTest(headers=headers):
                response = await self.client.get(
                    "/tui/owned/ws",
                    headers={
                        **headers,
                        "Upgrade": "websocket",
                        "Connection": "Upgrade",
                    },
                )
                self.assertEqual(response.status, 403)
        self.assertEqual(len(self.server.active), 0)

    async def test_real_renderer_query_and_single_focus_frames(self):
        from unittest.mock import AsyncMock
        from urllib.parse import quote

        from browser_tui.client import Binding

        binding = Binding("user", "owned", None, "__default__", {}, True)
        with patch("browser_tui.server.GatewayClient") as gateway, patch("browser_tui.server.BoundAppService") as service:
            gateway.return_value.bind.return_value = binding
            child = service.return_value
            child.start = AsyncMock()
            child.stop = AsyncMock()
            child.focus = AsyncMock()
            child.blur = AsyncMock()
            # The unchanged upstream renderer appends ?width to this suffix.
            path = "/tui/owned/ws?context=" + quote('{"model_name":"a"}') + "&viewport=?width=150&height=35"
            ws = await self.client.ws_connect(path, headers={"Origin": "https://deerflow.test", "Cookie": "access_token=synthetic"})
            await ws.send_json(["focus"])
            await ws.send_json(["blur"])
            await ws.send_json(["ping", "probe"])
            self.assertEqual(await ws.receive_json(), ["pong", "probe"])
            self.assertEqual(gateway.return_value.bind.call_args.args[1], {"model_name": "a"})
            child.focus.assert_awaited_once()
            child.blur.assert_awaited_once()
            await ws.close()
            await __import__("asyncio").sleep(0)

    async def test_health_is_not_business_completion(self):
        response = await self.client.get("/tui/health/ready")
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["active_connections"], 0)

    async def test_large_context_rejected_before_authentication(self):
        with patch("browser_tui.server.GatewayClient") as gateway:
            response = await self.client.get("/tui/owned/", params={"context": "x" * 2049})
            self.assertEqual(response.status, 400)
            gateway.assert_not_called()


if __name__ == "__main__":
    unittest.main()
