import { NextResponse, type NextRequest } from "next/server";

import { loadBrand } from "@/core/branding/server";

// Upstream docs/showcases remain in source for merges; public business entry uses our documentation.
export async function proxy(request: NextRequest) {
  if (["/favicon.ico", "/images/deer.svg"].includes(request.nextUrl.pathname))
    return NextResponse.rewrite(new URL("/brand/logo", request.url));
  return NextResponse.redirect((await loadBrand()).docs, 307);
}
export const config = {
  matcher: [
    "/images/deer.svg",
    "/favicon.ico",
    "/blog/:path*",
    "/:lang/docs/:path*",
    "/:lang/harness/:path*",
    "/showcase/:path*",
    "/github-stars",
  ],
};
