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
        开发版本 {APP_VERSION} · 品牌配置 {brand.version}
      </p>
      <section className="bg-card space-y-3 rounded-xl border p-6">
        <h2 className="font-semibold">2026-10-12 · DEV 开发中</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li>统一Genesis 官网 Logo、网页与终端主题。</li>
          <li>运行时品牌配置、开源声明及品牌回归检查。</li>
          <li>网页新窗口终端工作台，沿用当前用户、会话与只读权限。</li>
        </ul>
        <p className="text-muted-foreground text-sm">
          记录对应本次 DEV 候选，不代表 STG / PROD 已发布。
        </p>
      </section>
    </main>
  );
}
