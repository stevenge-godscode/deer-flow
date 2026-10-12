from __future__ import annotations

import json
import os

from deerflow.tui.app import DeerFlowTUI
from deerflow.tui.cli import LaunchPlan
from deerflow.tui.view_state import AssistantRow, SystemMessage, UserRow

from .branding import brand_header, brand_rendered_text, load_brand
from .client import Binding, GatewayClient


class BoundSession:
    writer = None  # Gateway owns persistence; never write default-user metadata.

    def __init__(self, client):
        self.client = client

    def resolve_thread(self, plan):
        return self.client.binding.thread_id

    def recent_threads(self, **kwargs):
        return [{"thread_id": self.client.binding.thread_id, "title": "当前绑定会话"}]

    def resolve_ref(self, ref):
        self.client.assert_thread(ref)
        return ref


class BrowserTUI(DeerFlowTUI):
    def __init__(self, *args, **kwargs):
        self.brand = load_brand()
        super().__init__(*args, **kwargs)
        self.title = self.brand["title"]
        p = self.brand["dark"]
        self.stylesheet.add_source(f"""Screen {{ background: {p["background"]}; color: {p["foreground"]}; }}
        #scroll {{ background: {p["background"]}; }}
        #header, #status, #composer, #palette {{ background: {p["surface"]}; color: {p["foreground"]}; }}
        #composer {{ border: solid {p["border"]}; }}
        #composer:focus {{ border: solid {p["primary"]}; }}""")

    def _refresh_header(self):
        self.query_one("#header").update(brand_header(self.brand, self._model, self._thread_label()))

    def _refresh_transcript(self):
        super()._refresh_transcript()
        from deerflow.tui.render import render_transcript

        self.query_one("#transcript").update(brand_rendered_text(render_transcript(self.state), self.brand))

    def _refresh_status(self):
        super()._refresh_status()
        from deerflow.tui.render import render_status

        self.query_one("#status").update(brand_rendered_text(render_status(self.state, model=self._model, thread_label=self._thread_label(), spinner=""), self.brand))

    def on_mount(self):
        super().on_mount()
        self.query_one("#composer").placeholder = f"Message {self.brand['name']}…   ( / for commands )"
        client = self.session.client
        values = client.history()
        rows = []
        for message in values.get("messages", []):
            if message.get("additional_kwargs", {}).get("hide_from_ui"):
                continue
            content = message.get("content", "")
            if isinstance(content, list):
                content = "".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
            if message.get("type") == "human" and content:
                rows.append(UserRow(str(content)))
            elif message.get("type") == "ai" and content:
                rows.append(AssistantRow(str(content), message.get("id")))
        from dataclasses import replace

        self.state = replace(self.state, rows=tuple(rows))
        self._dispatch(SystemMessage("已绑定当前登录用户与会话。操作通过当前用户的应用权限执行；返回网页切换 Project、智能体或模型。"))
        if not client.binding.can_write:
            self.query_one("#composer").disabled = True
            self._dispatch(SystemMessage("当前权限仅允许查看。"))

    def _open_palette(self, items):
        blocked = {"new", "threads", "switch", "resume", "model"}
        super()._open_palette([item for item in items if item.name not in blocked])

    def _handle_builtin(self, name, args):
        if name in {"new", "threads", "switch", "resume", "model"}:
            self._dispatch(SystemMessage("此窗口绑定当前会话，请返回网页切换后重新打开 TUI。"))
            return
        if name == "config":
            b = self.session.client.binding
            self._dispatch(SystemMessage(f"会话: {b.thread_id} · Project: {b.project_id or '未分组'} · 智能体: {b.agent_name}"))
            return
        if name == "help":
            self._dispatch(SystemMessage("/help /clear /goal /skills /tools /mcp /memory /uploads /usage /config /quit\nEnter 发送 · Esc 停止运行 · Ctrl+C 停止或退出。会话/模型切换在网页完成。"))
            return
        super()._handle_builtin(name, args)

    def _interrupt_run(self):
        try:
            self.session.client.cancel()
        except Exception:
            self._dispatch(SystemMessage("停止请求未确认，请在网页运行详情中检查。", tone="error"))
        super()._interrupt_run()


def main():
    # Parent sends private connection context on stdin before the web driver starts.
    # Avoid buffered stdin consuming the web driver's first packet.
    payload_bytes = bytearray()
    while len(payload_bytes) < 65536:
        byte = os.read(0, 1)
        if byte == b"\n":
            break
        if not byte:
            raise RuntimeError("Missing connection context")
        payload_bytes.extend(byte)
    else:
        raise RuntimeError("Connection context too large")
    payload = json.loads(payload_bytes)
    binding = Binding(**payload["binding"])
    client = GatewayClient(os.environ["TUI_GATEWAY_URL"], payload["headers"], binding)
    try:
        app = BrowserTUI(
            BoundSession(client),
            LaunchPlan(mode="tui", thread_id=binding.thread_id, forced_tui=True),
        )
        app.run()
    finally:
        client.close()


if __name__ == "__main__":
    main()
