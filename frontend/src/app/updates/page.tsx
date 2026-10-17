import Link from "next/link";

import { BrandLogo } from "@/components/brand-logo";
import { loadBrand } from "@/core/branding/server";
import { APP_VERSION } from "@/version";

export default async function UpdatesPage() {
  const brand = await loadBrand();
  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/workspace">
        <BrandLogo />
      </Link>
      <h1 className="text-2xl font-semibold">版本与更新</h1>
      <p className="text-muted-foreground">
        运行版本 {APP_VERSION} · 品牌配置 {brand.version}
      </p>
      <section className="bg-card space-y-3 rounded-xl border p-6">
        <h2 className="font-semibold">2026-10-13 · DEV 账号关联</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li>统一账号首次登录自动创建个人工作台账号。</li>
          <li>关联已有账号须验证原密码和统一身份，保留原账号及项目归属。</li>
          <li>关联与解绑后撤销旧会话，并保留身份变更记录。</li>
        </ul>
        <p className="text-muted-foreground text-sm">
          DEV 验证版本；企业业务权限和本体验证独立验收。
        </p>
        <Link
          href="https://github.com/stevenge-godscode/deer-flow/pull/10"
          className="text-sm underline"
        >
          查看变更与验证记录
        </Link>
      </section>
      <section className="bg-card space-y-3 rounded-xl border p-6">
        <h2 className="font-semibold">2026-10-12 · Genesis 品牌与终端工作台</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li>统一Genesis 官网 Logo、网页与终端主题。</li>
          <li>运行时品牌配置、开源声明及品牌回归检查。</li>
          <li>网页新窗口终端工作台，沿用当前用户、会话与只读权限。</li>
        </ul>
        <p className="text-muted-foreground text-sm">
          本页展示当前运行版本的更新内容。
        </p>
      </section>
    </main>
  );
}
