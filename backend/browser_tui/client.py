from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from http.cookies import SimpleCookie

import httpx


class AccessDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class Binding:
    user_id: str
    thread_id: str
    project_id: str | None
    agent_name: str
    context: dict
    can_write: bool


def session_headers(cookie: str, origin: str) -> dict[str, str]:
    parsed = SimpleCookie()
    parsed.load(cookie)
    if not parsed.get("access_token"):
        raise AccessDenied("请先登录 DeerFlow。")
    # Only app authentication and double-submit cookies reach the Gateway.
    parts = [m.OutputString() for key, m in parsed.items() if key in {"access_token", "csrf_token", "deerflow_session_persistent"}]
    headers = {"Cookie": "; ".join(parts), "Origin": origin}
    if parsed.get("csrf_token"):
        headers["X-CSRF-Token"] = parsed["csrf_token"].value
    return headers


def validate_context(context: dict) -> dict:
    if not isinstance(context, dict) or len(json.dumps(context)) > 2048:
        raise AccessDenied("无效的会话设置。")
    result = {}
    for key, value in context.items():
        if value is None:
            continue
        if key == "model_name" and isinstance(value, str) and 0 < len(value) <= 200:
            result[key] = value
        elif key == "mode" and value in {"flash", "thinking", "pro", "ultra"}:
            result.update(
                thinking_enabled=value != "flash",
                is_plan_mode=value in {"pro", "ultra"},
                subagent_enabled=value == "ultra",
            )
        elif key == "reasoning_effort" and value in {
            "minimal",
            "low",
            "medium",
            "high",
        }:
            result[key] = value
        elif key in {"thinking_enabled", "is_plan_mode", "subagent_enabled"} and type(value) is bool:
            result[key] = value
        else:
            raise AccessDenied("不支持的会话设置。")
    return result


def decode_sse(lines: Iterator[str]):
    event, data = "", []
    for line in lines:
        if not line:
            if data:
                yield event or "message", json.loads("\n".join(data))
            event, data = "", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event or "message", json.loads("\n".join(data))


@dataclass
class Event:
    type: str
    data: object


class GatewayClient:
    def __init__(self, base_url: str, headers: dict, binding: Binding | None = None):
        self.http = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(30, read=90),
            trust_env=False,
        )
        self.binding = binding
        self._cancelled = threading.Event()
        self._active_run: str | None = None

    def request(self, method: str, path: str, **kwargs):
        response = self.http.request(method, path, **kwargs)
        self.check(response)
        return response.json() if response.content else {}

    @staticmethod
    def check(response):
        if response.status_code in {401, 403, 404}:
            raise AccessDenied("登录已失效，或你无权访问此会话。")
        if response.status_code == 409:
            raise RuntimeError("当前会话正在运行或上下文发生变化，请返回网页处理。")
        if response.status_code >= 400:
            raise RuntimeError(f"DeerFlow 请求失败（HTTP {response.status_code}）。")

    def bind(self, thread_id: str, context: dict) -> Binding:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", thread_id):
            raise AccessDenied("无效的会话标识。")
        user = self.request("GET", "/api/v1/auth/me")
        if not user.get("id") or user["id"] == "default":
            raise AccessDenied("此入口需要真实登录用户。")
        thread = self.request("GET", f"/api/threads/{thread_id}")
        state = self.request("GET", f"/api/threads/{thread_id}/state")
        agent = state.get("metadata", {}).get("deerflow_agent_name")
        if not isinstance(agent, str) or not agent:
            raise AccessDenied("会话尚未建立可靠的智能体绑定，请先在网页完成一轮问答。")
        project = thread.get("metadata", {}).get("deerflow_project_id")
        if project:
            self.request("GET", f"/api/projects/{project}")
        resolved = validate_context(context)
        if resolved.get("model_name"):
            models = self.request("GET", "/api/models").get("models", [])
            if resolved["model_name"] not in {m.get("name") for m in models}:
                raise AccessDenied("所选模型不可用。")
        permissions = user.get("permissions") or []
        result = Binding(
            str(user["id"]),
            thread_id,
            project,
            agent,
            resolved,
            "runs:create" in permissions and "runs:cancel" in permissions,
        )
        if self.binding and result != self.binding:
            raise AccessDenied("会话归属、权限或上下文已变化，请重新打开 TUI。")
        self.binding = result
        return result

    def assert_thread(self, thread_id):
        if self.binding is None or thread_id != self.binding.thread_id:
            raise AccessDenied("此窗口仅绑定打开时的会话。")

    def revalidate(self):
        assert self.binding
        # bind expects the original public context, not translated private fields.
        user = self.request("GET", "/api/v1/auth/me")
        if str(user.get("id")) != self.binding.user_id:
            raise AccessDenied("登录身份已变化。")
        can_write = {"runs:create", "runs:cancel"}.issubset(user.get("permissions") or [])
        if can_write != self.binding.can_write:
            raise AccessDenied("会话权限已变化，请重新打开。")
        thread = self.request("GET", f"/api/threads/{self.binding.thread_id}")
        if thread.get("metadata", {}).get("deerflow_project_id") != self.binding.project_id:
            raise AccessDenied("Project 归属已变化。")
        if self.binding.project_id:
            self.request("GET", f"/api/projects/{self.binding.project_id}")
        state = self.request("GET", f"/api/threads/{self.binding.thread_id}/state")
        if state.get("metadata", {}).get("deerflow_agent_name") != self.binding.agent_name:
            raise AccessDenied("智能体绑定已变化。")
        return user

    def stream(self, message: str, *, thread_id=None, **kwargs):
        self.assert_thread(thread_id)
        user = self.revalidate()
        if not self.binding.can_write or not {"runs:create", "runs:cancel"}.issubset(user.get("permissions") or []):
            raise AccessDenied("当前权限仅允许查看。")
        self._cancelled.clear()
        context = dict(self.binding.context)
        if self.binding.agent_name != "__default__":
            context["agent_name"] = self.binding.agent_name
        body = {
            "assistant_id": "lead_agent",
            "input": {"messages": [{"type": "human", "content": message}]},
            "context": context,
            "stream_mode": ["messages-tuple", "values"],
            "multitask_strategy": "reject",
            "on_disconnect": "cancel",
        }
        try:
            with self.http.stream(
                "POST",
                f"/api/threads/{thread_id}/runs/stream",
                json=body,
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                self.check(response)
                self._active_run = response.headers.get("Content-Location", "").rsplit("/", 1)[-1] or None
                if self._cancelled.is_set():
                    self.cancel()
                    return
                for event, data in decode_sse(response.iter_lines()):
                    if self._cancelled.is_set():
                        return
                    if event in {"messages", "messages-tuple"}:
                        event = "messages-tuple"
                        if isinstance(data, list):
                            data = data[0]
                        if isinstance(data, dict) and data.get("type") in {"AIMessageChunk", "ToolMessageChunk"}:
                            data = {**data, "type": "ai" if data["type"] == "AIMessageChunk" else "tool"}
                    if event in {"error", "gap"}:
                        raise RuntimeError("运行失败或流中断，请返回网页查看运行详情。")
                    yield Event(event, data)
        finally:
            self._active_run = None

    def cancel(self):
        self._cancelled.set()
        run_id = self._active_run
        if run_id and self.binding:
            with httpx.Client(
                base_url=str(self.http.base_url),
                headers=self.http.headers,
                trust_env=False,
                timeout=15,
            ) as client:
                response = client.post(f"/api/threads/{self.binding.thread_id}/runs/{run_id}/cancel")
                self.check(response)

    def history(self):
        self.revalidate()
        return self.request("GET", f"/api/threads/{self.binding.thread_id}/state").get("values", {})

    def list_models(self):
        data = self.request("GET", "/api/models")
        if self.binding.context.get("model_name"):
            data["models"] = [m for m in data.get("models", []) if m.get("name") == self.binding.context["model_name"]]
        return data

    def list_skills(self, **kwargs):
        return self.request("GET", "/api/skills")

    def get_mcp_config(self):
        return self.request("GET", "/api/mcp/config")

    def get_memory(self):
        return self.request("GET", "/api/memory")

    def get_goal(self, thread_id):
        self.assert_thread(thread_id)
        return self.request("GET", f"/api/threads/{thread_id}/goal")

    def set_goal(self, thread_id, objective):
        self.assert_thread(thread_id)
        self.revalidate()
        return self.request("PUT", f"/api/threads/{thread_id}/goal", json={"objective": objective})

    def clear_goal(self, thread_id):
        self.assert_thread(thread_id)
        self.revalidate()
        return self.request("DELETE", f"/api/threads/{thread_id}/goal")

    def list_uploads(self, thread_id):
        self.assert_thread(thread_id)
        return self.request("GET", "/api/uploads/list", params={"thread_id": thread_id})

    def close(self):
        self.http.close()
