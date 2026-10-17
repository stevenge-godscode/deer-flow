"use client";

import { useQuery } from "@tanstack/react-query";
import { SquareTerminal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { type LocalSettings } from "@/core/settings";
import { browserTuiURL } from "@/core/threads/browser-tui";
import { buildRunContext } from "@/core/threads/hooks";

export function BrowserTuiTrigger({
  threadId,
  context,
}: {
  threadId: string;
  context: LocalSettings["context"];
}) {
  const { user } = useAuth();
  const { locale } = useI18n();
  const capability = useQuery({
    queryKey: ["browser-tui-capability"],
    queryFn: async () => {
      const response = await fetch("/tui/health/ready", {
        credentials: "same-origin",
      });
      if (
        !response.ok ||
        !response.headers.get("content-type")?.includes("application/json")
      )
        return false;
      const data = (await response.json()) as { status?: string };
      return data.status === "ready";
    },
    staleTime: 60_000,
    retry: false,
    enabled: Boolean(user),
  });
  const url = browserTuiURL(
    threadId,
    buildRunContext({ settings: context, threadId }),
  );
  if (!url || !capability.data || !user?.permissions?.includes("threads:read"))
    return null;
  const label = locale.startsWith("zh") ? "打开 TUI" : "Open TUI";
  return (
    <Button variant="outline" size="sm" asChild>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={label}
        title={label}
      >
        <SquareTerminal />
        <span className="hidden sm:inline">{label}</span>
      </a>
    </Button>
  );
}
