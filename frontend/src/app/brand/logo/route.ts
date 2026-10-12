import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const dynamic = "force-dynamic";
export async function GET() {
  const bytes = await readFile(
    process.env.GENESIS_BRAND_LOGO ??
      join(process.cwd(), "public/branding/genesis-logo.png"),
  );
  return new Response(bytes, {
    headers: {
      "Content-Type": "image/png",
      "Cache-Control": "no-cache",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
