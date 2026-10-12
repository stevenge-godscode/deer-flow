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
      aria-label={brand.name}
    >
      <Image
        src="/brand/logo"
        alt={`${brand.company} Logo`}
        width={compact ? 32 : 40}
        height={compact ? 32 : 40}
        unoptimized
        className={cn("rounded", compact ? "size-8" : "size-10")}
      />
      {!compact && <span>{brand.name}</span>}
    </span>
  );
}
