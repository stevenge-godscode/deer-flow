import Link from "next/link";

import { BrandLogo } from "@/components/brand-logo";
import { SafeStreamdown } from "@/core/streamdown/components";

import notices from "../../legal-notices";

export default function LegalPage() {
  return (
    <main className="bg-background mx-auto max-w-4xl space-y-8 p-8">
      <Link href="/workspace">
        <BrandLogo />
      </Link>
      <h1 className="text-2xl font-semibold">
        开源软件声明 / Third-party notices
      </h1>
      <SafeStreamdown>{notices}</SafeStreamdown>
    </main>
  );
}
