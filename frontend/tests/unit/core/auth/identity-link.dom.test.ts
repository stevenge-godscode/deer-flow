import { describe, expect, it, rs, afterEach } from "@rstest/core";

import { beginIdentityLink } from "@/core/auth/identity-link";

afterEach(() => {
  rs.unstubAllGlobals();
  document.cookie = "csrf_token=; Max-Age=0";
});
describe("explicit identity association", () => {
  it("proves local credentials before sending a CSRF-protected server-derived link intent", async () => {
    document.cookie = "csrf_token=proof";
    const http = rs
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            authorization_url:
              "https://identity.example.com/authorize?state=nonce",
          }),
          { status: 200 },
        ),
      );
    rs.stubGlobal("fetch", http);
    const url = await beginIdentityLink({
      provider: "genesis-dev",
      email: "old@example.com",
      password: "only-in-memory",
      rememberMe: false,
      next: "/workspace",
    });
    expect(url).toContain("https://identity.example.com/");
    const first = http.mock.calls[0]!;
    expect(first[0]).toBe("/api/v1/auth/login/local");
    expect(
      ((first[1] as RequestInit).body as URLSearchParams).toString(),
    ).toContain("username=old%40example.com");
    const second = http.mock.calls[1]!;
    const request = second[1] as RequestInit;
    expect(request.headers).toEqual({
      "Content-Type": "application/json",
      "X-CSRF-Token": "proof",
    });
    expect(JSON.parse(request.body as string)).toEqual({
      password: "only-in-memory",
      next: "/workspace",
      remember_me: false,
    });
    expect(request.credentials).toBe("include");
  });
  it("never starts OIDC when local proof fails", async () => {
    const http = rs.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Incorrect password" }), {
        status: 401,
      }),
    );
    rs.stubGlobal("fetch", http);
    await expect(
      beginIdentityLink({
        provider: "genesis-dev",
        email: "old@example.com",
        password: "wrong",
        rememberMe: false,
        next: "/workspace",
      }),
    ).rejects.toThrow();
    expect(http).toHaveBeenCalledTimes(1);
  });
});
