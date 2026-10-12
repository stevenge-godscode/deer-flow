import Link from "next/link";

import { BrandLogo } from "@/components/brand-logo";
import { Button } from "@/components/ui/button";
import { loadBrand } from "@/core/branding/server";

export default async function LandingPage() {
  const brand = await loadBrand();
  return (
    <div className="bg-background min-h-screen">
      <header className="bg-card border-b">
        <nav className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <Link href={brand.website}>
            <BrandLogo />
          </Link>
          <Button asChild variant="outline">
            <Link href="/workspace">进入工作台</Link>
          </Button>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl space-y-10 px-6 py-20">
        <p className="text-primary font-semibold">
          {brand.company} · {brand.name}
        </p>
        <h1 className="max-w-4xl text-4xl leading-tight font-semibold tracking-tight sm:text-6xl">
          {brand.description}
        </h1>
        <p className="text-muted-foreground text-xl">
          为 AI 绘制可信的业务地图，让智能体在你的权限内完成工作。
        </p>
        <div className="flex flex-wrap gap-3">
          <Button asChild>
            <Link href="/workspace">打开智能体工作台</Link>
          </Button>
          <Button asChild variant="outline">
            <a href={brand.docs}>了解技术架构</a>
          </Button>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            ["业务上下文", "连接对象、事实、规则与工作方式。"],
            ["受控执行", "在当前用户与业务权限内调用工具。"],
            ["结果可追溯", "保留会话、运行与证据，验证实际结果。"],
          ].map(([title, text]) => (
            <section key={title} className="bg-card rounded-xl border p-6">
              <h2 className="mb-3 text-lg font-semibold">{title}</h2>
              <p className="text-muted-foreground">{text}</p>
            </section>
          ))}
        </div>
      </main>
      <footer className="text-muted-foreground mx-auto flex max-w-6xl flex-wrap gap-6 border-t px-6 py-6 text-sm">
        <span>
          {brand.company} · {brand.name}
        </span>
        <a href={brand.support}>联系我们</a>
        <Link href="/legal">开源声明</Link>
      </footer>
    </div>
  );
}
