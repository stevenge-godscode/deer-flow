import { pathOfThread } from "@/core/threads/utils";

export function projectChatPath(projectId: string, agentName?: string): string {
  return `${pathOfThread("new", agentName ? { agent_name: agentName } : undefined)}?project=${encodeURIComponent(projectId)}`;
}
