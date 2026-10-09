import { afterEach, expect, rs, test } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  create: rs.fn(),
  invalidate: rs.fn(),
  error: rs.fn(),
}));
rs.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidate }),
}));
rs.mock("@/core/threads/api", () => ({ createThread: mocks.create }));
rs.mock("@/core/threads/hooks", () => ({
  INFINITE_THREADS_QUERY_KEY_PREFIX: ["threads", "infinite"],
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: { projects: { projectUnavailable: "Unavailable" } } }),
}));
rs.mock("sonner", () => ({ toast: { error: mocks.error } }));

import { useProjectThreadCreation } from "@/core/projects/use-project-thread-creation";

afterEach(() => {
  cleanup();
  rs.resetAllMocks();
});

test("assigns project and selected agent before allowing submit", async () => {
  mocks.create.mockResolvedValue({});
  const { result } = renderHook(() =>
    useProjectThreadCreation("thread", "project", "specialist"),
  );
  await act(async () => {
    await result.current();
  });
  expect(mocks.create).toHaveBeenCalledWith("thread", "project", "specialist");
  expect(mocks.invalidate).toHaveBeenCalledTimes(1);
});

test("project failure rejects without unassigned fallback and permits retry", async () => {
  mocks.create
    .mockRejectedValueOnce(new Error("missing"))
    .mockResolvedValueOnce({});
  const { result } = renderHook(() =>
    useProjectThreadCreation("thread", "project", "specialist"),
  );
  await act(async () => {
    await expect(result.current()).rejects.toThrow("missing");
  });
  expect(mocks.error).toHaveBeenCalledWith("Unavailable");
  expect(mocks.invalidate).not.toHaveBeenCalled();
  await act(async () => {
    await result.current();
  });
  expect(mocks.create).toHaveBeenCalledTimes(2);
  expect(mocks.create).toHaveBeenLastCalledWith(
    "thread",
    "project",
    "specialist",
  );
});

test.each(["thread", "project", "agent"])(
  "fences pending creation when %s changes",
  async (field) => {
    let finish!: () => void;
    mocks.create.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const initial = { thread: "t1", project: "p1", agent: "a1" };
    const { result, rerender } = renderHook(
      (props) =>
        useProjectThreadCreation(props.thread, props.project, props.agent),
      { initialProps: initial },
    );
    const pending = result.current();
    rerender({ ...initial, [field]: "changed" });
    finish();
    await expect(pending).rejects.toThrow("thread-submission-stale");
  },
);

test("fences pending creation after unmount", async () => {
  let finish!: () => void;
  mocks.create.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const { result, unmount } = renderHook(() =>
    useProjectThreadCreation("thread", "project"),
  );
  const pending = result.current();
  unmount();
  finish();
  await expect(pending).rejects.toThrow("thread-submission-stale");
});

test("ordinary chats do not create or move a project binding", async () => {
  const { result } = renderHook(() =>
    useProjectThreadCreation("thread", null, "specialist"),
  );
  await result.current();
  expect(mocks.create).not.toHaveBeenCalled();
});
