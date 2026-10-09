"use client";

import { BotIcon, ChevronDown } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAgents } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { projectChatPath } from "@/core/projects/chat-path";

function AgentItems({ projectId }: { projectId: string }) {
  const { agents, isLoading, error } = useAgents();
  const { t } = useI18n();
  if (isLoading)
    return <DropdownMenuItem disabled>{t.common.loading}</DropdownMenuItem>;
  if (error)
    return (
      <DropdownMenuItem disabled>
        {t.agents.nameStepNetworkError}
      </DropdownMenuItem>
    );
  if (!agents.length)
    return <DropdownMenuItem disabled>{t.agents.emptyTitle}</DropdownMenuItem>;
  return agents.map((agent) => (
    <DropdownMenuItem asChild key={agent.name}>
      <Link href={projectChatPath(projectId, agent.name)}>
        <BotIcon />
        {agent.display_name ?? agent.name}
      </Link>
    </DropdownMenuItem>
  ));
}

export function ProjectAgentChatMenu({ projectId }: { projectId: string }) {
  const { t } = useI18n();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          aria-label={`${t.projects.newChat} · ${t.agents.title}`}
        >
          <BotIcon />
          {t.agents.title}
          <ChevronDown />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-80">
        <AgentItems projectId={projectId} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
