"use client";

import Image from "next/image";

import { useBrand } from "@/core/branding/context";
import { cn } from "@/lib/utils";

export function BrandLogo({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
}) {
  const brand = useBrand();
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-2 font-semibold tracking-tight",
        className,
      )}
      aria-label={`${brand.company} · ${brand.name}`}
    >
      <Image
        src="/brand/logo"
        alt={`${brand.company} Logo`}
        width={28}
        height={28}
        unoptimized
        className="size-7 rounded"
      />
      {!compact && <span>{brand.name}</span>}
    </span>
  );
}
