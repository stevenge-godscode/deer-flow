from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlencode

import aiohttp_jinja2
import jinja2
from aiohttp import WSMsgType, web
from textual_serve.app_service import AppService
from textual_serve.server import Server

from .branding import brand_template, load_brand
from .client import AccessDenied, GatewayClient, session_headers


class BoundAppService(AppService):
    def __init__(self, *args, payload, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload = payload

    async def _open_app_process(self, width=80, height=24):
        # Never interpolate browser input into command text or inherit credentials.
        environment = self._build_environment(width, height)
        environment = {
            k: v
            for k, v in environment.items()
            if k
            in {
                "PATH",
                "PYTHONPATH",
                "HOME",
                "LANG",
                "TUI_GATEWAY_URL",
                "GENESIS_BRAND_CONFIG",
                "TEXTUAL_DRIVER",
                "TEXTUAL_FPS",
                "TEXTUAL_COLOR_SYSTEM",
                "TERM_PROGRAM",
                "TERM_PROGRAM_VERSION",
                "COLUMNS",
                "ROWS",
            }
        }
        self._process = process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "browser_tui.app",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        self._stdin = process.stdin
        self._stdin.write(json.dumps(self.payload).encode() + b"\n")
        await self._stdin.drain()
        self.payload = None
        return process

    async def stop(self):
        if self._task is not None:
            try:
                await asyncio.wait_for(super().stop(), timeout=5)
            except (TimeoutError, ConnectionError, RuntimeError):
                pass
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=3)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()


class BrowserServer(Server):
    def __init__(self, gateway_url, public_url, **kwargs):
        self.brand = load_brand()
        super().__init__(
            self.brand["name"] + " 终端工作台",
            public_url=public_url,
            title=self.brand["title"],
            **kwargs,
        )
        self.gateway_url = gateway_url
        self.public_url = public_url.rstrip("/")
        self.active = {}
        self.limit = 4

    async def identify(self, request):
        raw_context = request.query.get("context", "{}")
        if len(raw_context) > 2048:
            raise web.HTTPBadRequest(text="会话设置过长。")
        if request.headers.get("Origin") not in {None, self.public_url}:
            raise web.HTTPForbidden(text="不允许跨站访问。")
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise web.HTTPForbidden(text="不允许跨站访问。")
        try:
            context = json.loads(raw_context)
            headers = session_headers(request.headers.get("Cookie", ""), self.public_url)
            client = GatewayClient(self.gateway_url, headers)
            try:
                binding = await asyncio.to_thread(client.bind, request.match_info["thread_id"], context)
            finally:
                client.close()
        except (AccessDenied, ValueError, TypeError):
            raise web.HTTPForbidden(text="请登录并确认你有权访问当前会话。") from None
        except Exception:
            raise web.HTTPServiceUnavailable(text="无法确认会话，请返回工作台检查。") from None
        return headers, binding

    async def _make_app(self):
        app = web.Application(client_max_size=8192)
        # Reuse upstream renderer and template; remove the external font request.
        template = (Path(self.templates_path) / "app_index.html").read_text()
        template = template.replace(
            '    <link\n      rel="stylesheet"\n      href="https://fonts.googleapis.com/css?family=Roboto%20Mono"\n    />',
            "",
        )
        template = brand_template(template, self.brand)
        template = template.replace(
            "</body>",
            """<script>
(() => {
  const expectedUser = {{ binding_user_id | tojson }};
  let checking = false;
  async function checkIdentity() {
    if (checking) return;
    checking = true;
    try {
      const response = await fetch('/api/v1/auth/me', {
        credentials: 'same-origin', cache: 'no-store',
        signal: AbortSignal.timeout(5000)
      });
      if (!response.ok) throw new Error('session');
      const current = await response.json();
      if (current.id !== expectedUser || !current.permissions?.includes('threads:read')) {
        throw new Error('identity');
      }
    } catch (_) {
      window.location.replace('/workspace/chats');
    } finally { checking = false; }
  }
  window.addEventListener('focus', checkIdentity);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) checkIdentity();
  });
  setInterval(checkIdentity, 5000);
  checkIdentity();
})();
</script>
</body>""",
        )
        aiohttp_jinja2.setup(app, loader=jinja2.DictLoader({"app_index.html": template}))
        app.add_routes(
            [
                web.get("/tui/health/ready", self.health),
                web.get("/tui/{thread_id}/", self.handle_index),
                web.get("/tui/{thread_id}/ws", self.handle_websocket),
                web.static("/tui/static", self.statics_path, show_index=False),
            ]
        )
        app.on_shutdown.append(self.on_shutdown)
        return app

    async def health(self, request):
        return web.json_response(
            {
                "status": "ready",
                "active_connections": len(self.active),
                "version": "0.1.0-dev",
            }
        )

    @aiohttp_jinja2.template("app_index.html")
    async def handle_index(self, request):
        _, binding = await self.identify(request)
        thread_id = request.match_info["thread_id"]
        # Upstream appends ?width=...; reserve a viewport parameter so this
        # suffix cannot become part of the context JSON.
        query = urlencode({"context": request.query.get("context", "{}")})
        return {
            "font_size": 16,
            "binding_user_id": binding.user_id,
            "app_websocket_url": self.public_url.replace("https:", "wss:").replace("http:", "ws:") + f"/tui/{thread_id}/ws?{query}&viewport=",
            "config": {"static": {"url": self.public_url + "/tui/static/"}},
            "application": {"name": self.title},
        }

    async def handle_websocket(self, request):
        if request.headers.get("Origin") != self.public_url:
            raise web.HTTPForbidden(text="不允许跨站连接。")
        headers, binding = await self.identify(request)
        key = (binding.user_id, binding.thread_id)
        # One interactive view per conversation prevents competing local controls.
        if key in self.active or len(self.active) >= self.limit:
            raise web.HTTPConflict(text="会话已有 TUI 窗口或终端资源繁忙。")
        websocket = web.WebSocketResponse(heartbeat=15, max_msg_size=8192)
        self.active[key] = websocket
        service = None
        guard = None
        try:
            await websocket.prepare(request)
            service = BoundAppService(
                "unused",
                payload={"headers": headers, "binding": asdict(binding)},
                write_bytes=websocket.send_bytes,
                write_str=websocket.send_str,
                close=websocket.close,
                download_manager=self.download_manager,
            )
            await service.start(120, 30)
            guard = asyncio.create_task(self.revalidate(websocket, headers, binding))
            async for message in websocket:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    envelope = json.loads(message.data)
                    if not isinstance(envelope, list) or len(envelope) not in {1, 2}:
                        raise ValueError()
                    kind = envelope[0]
                    data = envelope[1] if len(envelope) == 2 else None
                    if kind == "stdin" and isinstance(data, str) and len(data) <= 4096:
                        await service.send_bytes(data.encode())
                    elif kind == "resize" and isinstance(data, dict):
                        width, height = data.get("width"), data.get("height")
                        if type(width) is not int or type(height) is not int or not 20 <= width <= 300 or not 5 <= height <= 100:
                            raise ValueError()
                        await service.set_terminal_size(width, height)
                    elif kind == "ping":
                        await websocket.send_json(["pong", data])
                    elif kind == "blur":
                        await service.blur()
                    elif kind == "focus":
                        await service.focus()
                    else:
                        raise ValueError()
                except (ValueError, TypeError, KeyError):
                    await websocket.close(code=1008)
                    break
        finally:
            if guard:
                guard.cancel()
                await asyncio.gather(guard, return_exceptions=True)
            if service:
                await service.stop()
            self.active.pop(key, None)
        return websocket

    async def revalidate(self, websocket, headers, binding):
        client = GatewayClient(self.gateway_url, headers, binding)
        try:
            while not websocket.closed:
                await asyncio.sleep(5)
                await asyncio.to_thread(client.revalidate)
        except Exception:
            await websocket.close(code=1008, message="登录或权限已变化。".encode())
        finally:
            client.close()

    async def on_shutdown(self, app):
        await asyncio.gather(
            *(socket.close(code=1001) for socket in list(self.active.values())),
            return_exceptions=True,
        )


def main():
    logging.basicConfig(level=logging.WARNING)
    server = BrowserServer(
        os.environ["TUI_GATEWAY_URL"],
        os.environ["TUI_PUBLIC_ORIGIN"],
        host="0.0.0.0",
        port=int(os.environ.get("TUI_PORT", "8003")),
    )
    web.run_app(
        server._make_app(),
        host=server.host,
        port=server.port,
        access_log=None,
        print=None,
    )


if __name__ == "__main__":
    main()
