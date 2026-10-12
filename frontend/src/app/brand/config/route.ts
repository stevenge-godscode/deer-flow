import { loadBrand } from "@/core/branding/server";

export const dynamic = "force-dynamic";
export async function GET() {
  return Response.json(await loadBrand(), {
    headers: { "Cache-Control": "no-store" },
  });
}
