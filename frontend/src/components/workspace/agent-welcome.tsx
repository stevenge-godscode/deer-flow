"use client";

import { BotIcon } from "lucide-react";
import Link from "next/link";

import { type Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function AgentWelcome({
  className,
  agent,
  agentName,
}: {
  className?: string;
  agent: Agent | null | undefined;
  agentName: string;
}) {
  const { locale } = useI18n();
  const connections = (agent?.mcp_plugins ?? []).filter((id) =>
    id.startsWith("template:"),
  );
  const displayName = agent?.display_name?.length
    ? agent.display_name
    : (agent?.name ?? agentName);
  const description = agent?.description;

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-8 py-4 text-center",
        className,
      )}
    >
      <div className="bg-primary/10 flex h-12 w-12 items-center justify-center rounded-full">
        <BotIcon className="text-primary h-6 w-6" />
      </div>
      <div className="text-2xl font-bold">{displayName}</div>
      {connections.map((connection) => (
        <Link
          key={connection}
          href={`/workspace/capabilities?tab=plugins&plugin=${encodeURIComponent(connection.slice("template:".length))}`}
          className="text-primary rounded-lg border px-4 py-2 text-sm underline"
        >
          {locale === "zh-CN"
            ? "配置我的业务账号连接"
            : "Connect my business account"}
        </Link>
      ))}
      {description && (
        <p className="text-muted-foreground max-w-sm text-sm">{description}</p>
      )}
    </div>
  );
}
