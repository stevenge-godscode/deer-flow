import { expect, test } from "@rstest/core";

import { projectChatPath } from "@/core/projects/chat-path";

test("generic and selected-agent routes preserve encoded project identity", () => {
  expect(projectChatPath("p/一")).toBe(
    "/workspace/chats/new?project=p%2F%E4%B8%80",
  );
  expect(projectChatPath("p/一", "a/b")).toBe(
    "/workspace/agents/a%2Fb/chats/new?project=p%2F%E4%B8%80",
  );
});
