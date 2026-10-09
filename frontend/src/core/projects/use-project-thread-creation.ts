"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";
import { toast } from "sonner";

import { useI18n } from "@/core/i18n/hooks";
import { createThread } from "@/core/threads/api";
import { INFINITE_THREADS_QUERY_KEY_PREFIX } from "@/core/threads/hooks";

/** Create project membership before any run/goal, and fence abandoned submits. */
export function useProjectThreadCreation(
  threadId: string,
  projectId: string | null,
  agentName?: string,
) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  const epoch = useRef(0);
  useEffect(
    () => () => {
      epoch.current += 1;
    },
    [threadId, projectId, agentName],
  );

  return useCallback(async () => {
    const current = epoch.current;
    if (projectId) {
      try {
        await createThread(threadId, projectId, agentName);
        void queryClient.invalidateQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        });
      } catch (error) {
        if (current === epoch.current)
          toast.error(t.projects.projectUnavailable);
        throw error;
      }
    }
    if (current !== epoch.current) throw new Error("thread-submission-stale");
  }, [threadId, projectId, agentName, queryClient, t]);
}
