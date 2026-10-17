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
  const size = compact ? brand.logo.compactSize : brand.logo.size;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-2 font-semibold tracking-tight",
        className,
      )}
      aria-label={brand.name}
      style={{ fontSize: brand.logo.wordmarkSize, lineHeight: 1 }}
    >
      <Image
        src="/brand/logo"
        alt={`${brand.company} Logo`}
        width={size}
        height={size}
        unoptimized
        className="rounded"
        style={{ width: size, height: size }}
      />
      {!compact && <span>{brand.name}</span>}
    </span>
  );
}
