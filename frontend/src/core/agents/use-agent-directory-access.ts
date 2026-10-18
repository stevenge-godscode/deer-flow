"use client";
import { useQuery } from "@tanstack/react-query";

import { fetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { getBackendBaseURL } from "@/core/config";

export function useAgentDirectoryAccess() {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["agent-directory-access", user?.id],
    enabled: !!user,
    staleTime: 0,
    refetchOnWindowFocus: true,
    queryFn: async ({ signal }): Promise<{ can_manage: boolean }> => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/agent-directory/access`,
        { signal },
      );
      if (!response.ok) throw new Error("Agent directory access unavailable");
      return response.json() as Promise<{ can_manage: boolean }>;
    },
  });
}
