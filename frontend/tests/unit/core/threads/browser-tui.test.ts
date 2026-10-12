import { describe, expect, it } from "@rstest/core";

import { browserTuiURL } from "@/core/threads/browser-tui";

describe("native browser TUI context", () => {
  it("binds an existing thread and only exports public model settings", () => {
    const path = browserTuiURL("owned-thread", {
      model_name: "model a&b",
      mode: "flash",
      reasoning_effort: "low",
      user_id: "other",
      agent_name: "other",
      secrets: "private",
    });
    const url = new URL(path!, "https://deerflow.test");
    expect(url.pathname).toBe("/tui/owned-thread/");
    expect(JSON.parse(url.searchParams.get("context")!)).toEqual({
      model_name: "model a&b",
      mode: "flash",
      reasoning_effort: "low",
    });
    expect(path).not.toContain("private");
  });
  it.each(["new", "../other", "x/y", "x?y", "x".repeat(65), ""])(
    "rejects noncanonical thread %s",
    (thread) => {
      expect(browserTuiURL(thread, {})).toBeNull();
    },
  );
});
