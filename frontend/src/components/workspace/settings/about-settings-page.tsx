"use client";

import Link from "next/link";

import { BrandLogo } from "@/components/brand-logo";
import { Button } from "@/components/ui/button";
import { useBrand } from "@/core/branding/context";
import { APP_VERSION } from "@/version";

export function AboutSettingsPage() {
  const brand = useBrand();
  return (
    <section className="space-y-5">
      <BrandLogo className="text-xl" />
      <p>
        {brand.company} · {brand.description}
      </p>
      <p className="text-muted-foreground text-sm">品牌版本 {brand.version}</p>
      <Button variant="outline" asChild>
        <Link href="/updates">运行版本 {APP_VERSION} · 查看更新</Link>
      </Button>
      <div className="flex gap-5 text-sm">
        <a href={brand.website}>官方网站</a>
        <Link href="/legal">开源声明</Link>
      </div>
    </section>
  );
}
