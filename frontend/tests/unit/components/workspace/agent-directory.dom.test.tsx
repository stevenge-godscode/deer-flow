import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import AgentDirectoryPage from "@/app/workspace/agent-directory/page";

const state = rs.hoisted(() => ({
  role: "admin",
  manager: false,
  fetch: rs.fn(),
}));
rs.mock("@/core/agents/use-agent-directory-access", () => ({
  useAgentDirectoryAccess: () => ({
    data: { can_manage: state.role === "admin" || state.manager },
  }),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: state.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "administrator", system_role: state.role } }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ locale: "zh-CN" }) }));
const directory = {
  revision: 7,
  profiles: {
    cmdb: {
      label: "CMDB只读",
      role: "agent-directory-cmdb",
      permission_ids: ["cmdb"],
    },
  },
  accounts: [
    {
      id: "ordinary",
      email: "person@example.com",
      profiles: [],
      available: true,
    },
  ],
  sources: [],
  agents: [],
  audit: [],
  accounts_truncated: false,
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AgentDirectoryPage />
    </QueryClientProvider>,
  );
  return client;
}
afterEach(() => {
  cleanup();
  rs.resetAllMocks();
  state.role = "admin";
  state.manager = false;
});
describe("Agent directory account authority", () => {
  it("ordinary users cannot fetch administrator data", () => {
    state.role = "user";
    const client = mount();
    expect(screen.getByText("仅管理员可管理智能体与账号授权。")).not.toBeNull();
    expect(state.fetch).not.toHaveBeenCalled();
    client.clear();
  });
  it("allows a scoped manager without elevating the system role", async () => {
    state.role = "user";
    state.manager = true;
    state.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(directory),
    });
    const client = mount();
    await screen.findByText("person@example.com");
    expect(state.role).toBe("user");
    expect(screen.queryByText("仅管理员可管理智能体与账号授权。")).toBeNull();
    client.clear();
  });
  it("binds a grant to actor and revision, and retains denied status after conflict", async () => {
    state.fetch.mockImplementation(
      (_url: string, options?: { method?: string }) =>
        Promise.resolve(
          options?.method
            ? { ok: false, status: 409 }
            : { ok: true, json: () => Promise.resolve(directory) },
        ),
    );
    const client = mount();
    await screen.findByText("person@example.com");
    fireEvent.change(screen.getByLabelText("账号"), {
      target: { value: "ordinary" },
    });
    fireEvent.click(screen.getByRole("button", { name: "分配角色" }));
    await screen.findByRole("alert");
    const call = state.fetch.mock.calls.find(
      (entry) => entry[1]?.method === "PUT",
    );
    expect(call?.[0]).toBe("/api/agent-directory/memberships");
    expect(call?.[1]?.headers["X-Expected-User-Id"]).toBe("administrator");
    expect(JSON.parse(call?.[1]?.body)).toEqual({
      expected_revision: 7,
      profile: "cmdb",
      account_id: "ordinary",
      enabled: true,
    });
    await waitFor(() => expect(screen.getByText("未授权")).not.toBeNull());
    expect(screen.queryByText("已授权")).toBeNull();
    client.clear();
  });
  it("retains source identity across insertion and refuses a removed source", async () => {
    const a = { owner: "owner-a", name: "a", display_name: "A" };
    const b = { owner: "owner-b", name: "b", display_name: "B" };
    const x = { owner: "owner-x", name: "x", display_name: "X" };
    let sources = [a, b];
    state.fetch.mockImplementation(
      (_url: string, options?: { method?: string }) =>
        Promise.resolve(
          options?.method
            ? { ok: true }
            : {
                ok: true,
                json: () => Promise.resolve({ ...directory, sources }),
              },
        ),
    );
    const client = mount();
    const select = await screen.findByLabelText("我的源智能体");
    fireEvent.change(select, {
      target: { value: JSON.stringify([b.owner, b.name]) },
    });
    fireEvent.change(
      screen.getByLabelText("新版本标识（小写字母、数字、连字符）"),
      { target: { value: "shared-v2" } },
    );
    sources = [x, a, b];
    await client.invalidateQueries();
    fireEvent.click(screen.getByRole("button", { name: "发布" }));
    await waitFor(() =>
      expect(
        state.fetch.mock.calls.some((call) => call[1]?.method === "POST"),
      ).toBe(true),
    );
    const call = state.fetch.mock.calls.find(
      (call) => call[1]?.method === "POST",
    );
    expect(JSON.parse(call?.[1]?.body)).toMatchObject({
      source_owner: b.owner,
      source_name: b.name,
    });
    sources = [x, a];
    await client.invalidateQueries();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "发布" }).hasAttribute("disabled"),
      ).toBe(true),
    );
    client.clear();
  });
});
