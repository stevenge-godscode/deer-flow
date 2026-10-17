import { describe, expect, it } from "@rstest/core";

import { userSchema } from "@/core/auth/types";
describe("genuine optional OAuth contact", () => {
  it("accepts an ordinary verified server OAuth account without fake email", () => {
    expect(
      userSchema.safeParse({
        id: "id",
        email: null,
        system_role: "user",
        oauth_provider: "genesis-dev",
      }).success,
    ).toBe(true);
  });
  it("refuses email-less local/admin response shapes", () => {
    for (const x of [
      { system_role: "user" },
      { system_role: "admin", oauth_provider: "genesis-dev" },
    ]) {
      expect(
        userSchema.safeParse({ id: "id", email: null, ...x }).success,
      ).toBe(false);
    }
  });
});
