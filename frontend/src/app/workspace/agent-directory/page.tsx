"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";

interface Directory {
  revision: number;
  profiles: Record<
    string,
    { label: string; role: string; permission_ids: string[] }
  >;
  accounts: {
    id: string;
    email: string | null;
    profiles: string[];
    available: boolean;
  }[];
  accounts_truncated: boolean;
  sources: { owner: string; name: string; display_name: string | null }[];
  agents: {
    name: string;
    display_name: string | null;
    profile: string;
    enabled: boolean;
    digest: string;
  }[];
  audit: {
    revision: number;
    at: string;
    actor: string;
    action: string;
    name?: string;
    account?: string;
    profile?: string;
  }[];
}

export default function AgentDirectoryPage() {
  const { user } = useAuth();
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const queryClient = useQueryClient();
  const [source, setSource] = useState("");
  const [version, setVersion] = useState("");
  const [profile, setProfile] = useState("");
  const [account, setAccount] = useState("");
  const [error, setError] = useState("");
  const key = ["agent-directory", user?.id];
  const base = `${getBackendBaseURL()}/api/agent-directory`;
  const admin = user?.system_role === "admin";
  const query = useQuery({
    queryKey: key,
    enabled: admin,
    queryFn: async ({ signal }): Promise<Directory> => {
      const response = await fetch(base, { signal });
      if (!response.ok)
        throw new Error(
          zh
            ? "无法加载智能体管理，请刷新重试。"
            : "Agent management could not be loaded. Refresh to retry.",
        );
      return response.json() as Promise<Directory>;
    },
  });
  const mutation = useMutation({
    mutationFn: async ({
      path,
      method,
      body,
    }: {
      path: string;
      method: string;
      body: Record<string, unknown>;
    }) => {
      if (!user || !query.data) throw new Error("Reload required");
      const response = await fetch(`${base}${path}`, {
        method,
        headers: {
          "Content-Type": "application/json",
          "X-Expected-User-Id": user.id,
        },
        body: JSON.stringify({
          ...body,
          expected_revision: query.data.revision,
        }),
      });
      if (!response.ok) {
        throw new Error(
          response.status === 409
            ? zh
              ? "配置或登录账号已变化，请刷新后重试。"
              : "The directory or signed-in account changed. Refresh and retry."
            : zh
              ? "保存失败，未确认授权结果。请刷新后检查。"
              : "Save failed. Refresh to verify the assignment.",
        );
      }
    },
    onMutate: () => setError(""),
    onError: (failure) => setError(failure.message),
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: key });
    },
  });
  if (!admin)
    return (
      <p className="p-6">
        {zh
          ? "仅管理员可管理智能体与账号授权。"
          : "An administrator session is required."}
      </p>
    );
  const data = query.data;
  const activeProfile = profile || (Object.keys(data?.profiles ?? {})[0] ?? "");
  const selectedAccount = data?.accounts.find((item) => item.id === account);
  const assigned = selectedAccount?.profiles.includes(activeProfile) ?? false;
  const busy = mutation.isPending || query.isFetching;
  const selectStyle =
    "border-input bg-background w-full rounded-md border p-2 text-sm";
  const actionLabel = (action: string) =>
    ({
      publish: zh ? "发布版本" : "Publish",
      enable: zh ? "启用版本" : "Enable",
      disable: zh ? "停用版本" : "Disable",
      grant: zh ? "授权成功" : "Granted",
      revoke: zh ? "撤销成功" : "Revoked",
      "grant-request": zh ? "请求授权" : "Grant requested",
      "revoke-request": zh ? "请求撤销" : "Revoke requested",
      "identity-update-failed": zh
        ? "身份服务更新失败"
        : "Identity update failed",
    })[action] ?? action;

  return (
    <main className="mx-auto w-full max-w-5xl space-y-8 overflow-y-auto p-6">
      <header className="space-y-2">
        <Link
          href="/workspace/agents"
          className="text-muted-foreground text-sm"
        >
          ← {zh ? "智能体" : "Agents"}
        </Link>
        <h1 className="text-2xl font-semibold">
          {zh ? "智能体与账号管理" : "Agent and account management"}
        </h1>
        <p className="text-muted-foreground text-sm">
          {zh
            ? "发布共享版本，通过身份角色分配使用权。每个账号的会话、文件和项目保持独立。"
            : "Publish shared versions and assign access through identity roles. Each account keeps its own chats, files and projects."}
        </p>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => {
            void query.refetch();
          }}
        >
          {zh ? "刷新" : "Refresh"}
        </Button>
      </header>
      {(error || query.error) && (
        <p role="alert" className="text-destructive">
          {error || query.error?.message}
        </p>
      )}
      {query.isLoading && <p role="status">{zh ? "正在加载…" : "Loading…"}</p>}
      {data && (
        <>
          <section className="space-y-3 rounded-lg border p-4">
            <h2 className="text-lg font-medium">
              {zh ? "账号与业务角色" : "Accounts and business roles"}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1 text-sm">
                {zh ? "业务角色" : "Business role"}
                <select
                  className={selectStyle}
                  value={activeProfile}
                  disabled={busy}
                  onChange={(event) => setProfile(event.target.value)}
                >
                  {Object.entries(data.profiles).map(([id, value]) => (
                    <option key={id} value={id}>
                      {value.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm">
                {zh ? "账号" : "Account"}
                <select
                  className={selectStyle}
                  value={account}
                  disabled={busy}
                  onChange={(event) => setAccount(event.target.value)}
                >
                  <option value="">
                    {zh ? "选择已登录平台的账号" : "Select a platform account"}
                  </option>
                  {data.accounts.map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                      disabled={!item.available}
                    >
                      {item.email ?? item.id}
                      {!item.available
                        ? zh
                          ? "（不可用）"
                          : " (unavailable)"
                        : ""}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {selectedAccount && (
              <div className="flex items-center gap-3">
                <span role="status">
                  {assigned
                    ? zh
                      ? "已授权"
                      : "Assigned"
                    : zh
                      ? "未授权"
                      : "Not assigned"}
                </span>
                <Button
                  disabled={busy || !selectedAccount.available}
                  variant={assigned ? "outline" : "default"}
                  onClick={() =>
                    mutation.mutate({
                      path: "/memberships",
                      method: "PUT",
                      body: {
                        profile: activeProfile,
                        account_id: account,
                        enabled: !assigned,
                      },
                    })
                  }
                >
                  {assigned
                    ? zh
                      ? "撤销角色"
                      : "Revoke role"
                    : zh
                      ? "分配角色"
                      : "Assign role"}
                </Button>
              </div>
            )}
            {data.accounts_truncated && (
              <p role="status">
                {zh
                  ? "当前显示前 500 个账号。"
                  : "Showing the first 500 accounts."}
              </p>
            )}
            <p className="text-muted-foreground text-sm">
              {zh
                ? "角色同时控制共享智能体、已批准的工具和数据访问。撤销后，新的运行与后续工具调用会重新检查权限。"
                : "Roles govern published Agents and approved tool/data access. New runs and subsequent tool calls check live authority."}
            </p>
          </section>
          <section className="space-y-3 rounded-lg border p-4">
            <h2 className="text-lg font-medium">
              {zh ? "发布新版本" : "Publish a version"}
            </h2>
            <label className="block space-y-1 text-sm">
              {zh ? "已固化的源智能体" : "Immutable source Agent"}
              <select
                className={selectStyle}
                value={source}
                disabled={busy}
                onChange={(event) => setSource(event.target.value)}
              >
                <option value="">
                  {zh ? "选择源版本" : "Select source version"}
                </option>
                {data.sources.map((item) => (
                  <option
                    key={`${item.owner}/${item.name}`}
                    value={JSON.stringify([item.owner, item.name])}
                  >
                    {item.display_name ?? item.name} ·{" "}
                    {data.accounts.find((a) => a.id === item.owner)?.email ??
                      item.owner}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1 text-sm">
              {zh
                ? "新版本标识（小写字母、数字、连字符）"
                : "New version ID (lowercase letters, digits, hyphens)"}
              <Input
                value={version}
                disabled={busy}
                onChange={(event) => setVersion(event.target.value)}
                placeholder="cmdb-operations-v1"
              />
            </label>
            <p className="text-muted-foreground text-sm">
              {zh
                ? "使用上方选中的业务角色；发布后的内容不可修改，更新时发布一个新版本。"
                : "Uses the business role selected above. Published contents are immutable; publish a new version for updates."}
            </p>
            <Button
              disabled={
                busy ||
                !data.sources.some(
                  (item) => JSON.stringify([item.owner, item.name]) === source,
                ) ||
                !/^[a-z0-9-]{1,100}$/.test(version) ||
                !activeProfile
              }
              onClick={() => {
                const selected = data.sources.find(
                  (item) => JSON.stringify([item.owner, item.name]) === source,
                );
                if (selected)
                  mutation.mutate({
                    path: "/versions",
                    method: "POST",
                    body: {
                      name: version,
                      source_owner: selected.owner,
                      source_name: selected.name,
                      profile: activeProfile,
                    },
                  });
              }}
            >
              {zh ? "发布" : "Publish"}
            </Button>
          </section>
          <section className="space-y-3">
            <h2 className="text-lg font-medium">
              {zh ? "已发布版本" : "Published versions"}
            </h2>
            {data.agents.length === 0 && (
              <p>{zh ? "尚无共享版本。" : "No published versions."}</p>
            )}
            {data.agents.map((agent) => (
              <div
                key={agent.name}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4"
              >
                <div>
                  <p className="font-medium">
                    {agent.display_name ?? agent.name}
                  </p>
                  <p className="text-muted-foreground text-sm">
                    {agent.name} · {data.profiles[agent.profile]?.label} ·{" "}
                    {agent.enabled
                      ? zh
                        ? "已启用"
                        : "Enabled"
                      : zh
                        ? "已停用"
                        : "Disabled"}
                  </p>
                  <code
                    title={agent.digest}
                    className="text-muted-foreground text-xs"
                  >
                    {agent.digest.slice(0, 12)}
                  </code>
                </div>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    mutation.mutate({
                      path: `/versions/${encodeURIComponent(agent.name)}`,
                      method: "PATCH",
                      body: { enabled: !agent.enabled },
                    })
                  }
                >
                  {agent.enabled
                    ? zh
                      ? "停用"
                      : "Disable"
                    : zh
                      ? "启用"
                      : "Enable"}
                </Button>
              </div>
            ))}
          </section>
          <section className="space-y-3">
            <h2 className="text-lg font-medium">
              {zh ? "最近操作记录" : "Recent audit history"}
            </h2>
            <ol className="space-y-2 text-sm">
              {[...data.audit].reverse().map((event) => (
                <li key={event.revision} className="rounded border p-3">
                  <span>
                    {new Date(event.at).toLocaleString(locale)} ·{" "}
                    {actionLabel(event.action)}
                  </span>
                  <p className="text-muted-foreground">
                    {data.accounts.find((a) => a.id === event.actor)?.email ??
                      event.actor}{" "}
                    ·{" "}
                    {event.name ??
                      data.accounts.find((a) => a.id === event.account)
                        ?.email ??
                      event.account}{" "}
                    {event.profile &&
                      `· ${data.profiles[event.profile]?.label ?? event.profile}`}
                  </p>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </main>
  );
}
