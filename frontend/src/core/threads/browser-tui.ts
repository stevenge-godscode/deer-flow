export function browserTuiURL(
  threadId: string,
  context: Record<string, unknown>,
) {
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(threadId) || threadId === "new") {
    return null;
  }
  const publicContext: Record<string, unknown> = {};
  for (const key of ["model_name", "mode", "reasoning_effort"]) {
    const value = context[key];
    if (typeof value === "string" && value.length <= 200) {
      publicContext[key] = value;
    }
  }
  for (const key of ["thinking_enabled", "is_plan_mode", "subagent_enabled"]) {
    if (typeof context[key] === "boolean") publicContext[key] = context[key];
  }
  const query = new URLSearchParams({ context: JSON.stringify(publicContext) });
  return `/tui/${encodeURIComponent(threadId)}/?${query.toString()}`;
}
