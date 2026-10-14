import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import { zhCN } from "@/core/i18n/locales/zh-CN";

const mocks = rs.hoisted(() => ({ error: null as string | null }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  useSearchParams: () => ({
    get: (key: string) => (key === "error" ? mocks.error : null),
  }),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/components/brand-logo", () => ({
  BrandLogo: () => <span>Genesis</span>,
}));
rs.mock("@/components/ui/flickering-grid", () => ({
  FlickeringGrid: () => null,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
rs.mock("@/core/auth/setup", () => ({
  fetchSetupStatus: async () => ({ needs_setup: false }),
  canCreateRegularAccount: () => false,
}));
rs.mock("@/core/auth/remember-login", () => ({
  loadRememberLoginPreference: () => ({ rememberMe: true, email: "" }),
  saveRememberLoginPreference: rs.fn(),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: zhCN }) }));
beforeEach(() => {
  mocks.error = null;
  rs.stubGlobal(
    "fetch",
    rs
      .fn()
      .mockResolvedValue({
        json: async () => ({
          providers: [
            { id: "genesis-dev", display_name: "统一账号登录", type: "oidc" },
          ],
        }),
      }),
  );
});
afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
});
describe("compact login choices (view tests, not real authentication)", () => {
  it("shows one primary action and keeps session preference across method changes", async () => {
    render(<LoginPage />);
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: "登录", exact: true }).length,
      ).toBe(1),
    );
    expect(screen.queryByLabelText("邮箱")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "保持登录" }));
    fireEvent.click(screen.getByRole("button", { name: "邮箱密码登录" }));
    expect(
      screen.getAllByRole("button", { name: "登录", exact: true }).length,
    ).toBe(1);
    expect(screen.getByLabelText("邮箱")).toBeTruthy();
    expect(screen.getByLabelText("密码")).toBeTruthy();
    expect(screen.getAllByRole("checkbox").length).toBe(1);
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
      false,
    );
    fireEvent.click(screen.getByRole("button", { name: "其他登录方式" }));
    expect(screen.queryByLabelText("邮箱")).toBeNull();
    expect(
      screen.getAllByRole("button", { name: "登录", exact: true }).length,
    ).toBe(1);
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
      false,
    );
  });
  it("existing-account linking shows only verification and a return option", async () => {
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "关联已有账号" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "关联已有账号" }));
    expect(screen.getByRole("button", { name: "验证并关联" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "登录", exact: true }),
    ).toBeNull();
    expect(screen.getAllByRole("checkbox").length).toBe(1);
  });
  it("a callback failure stays visible when the password form is collapsed", async () => {
    mocks.error = "sso_failed";
    render(<LoginPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "登录", exact: true }),
      ).toBeTruthy(),
    );
    expect(screen.getByRole("alert").textContent).toBe("登录失败，请重试。");
    expect(screen.queryByLabelText("密码")).toBeNull();
  });
});
