import "@/styles/globals.css";

import { type Metadata } from "next";

import { ThemeProvider } from "@/components/theme-provider";
import { brandCSS } from "@/core/branding/config";
import { BrandProvider } from "@/core/branding/context";
import { loadBrand } from "@/core/branding/server";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";

export const dynamic = "force-dynamic";
export async function generateMetadata(): Promise<Metadata> {
  const brand = await loadBrand();
  return {
    title: { default: brand.title, template: `%s · ${brand.name}` },
    description: brand.description,
    applicationName: brand.name,
    icons: { icon: "/brand/logo", apple: "/brand/logo" },
  };
}
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const brand = await loadBrand();
  return (
    <html
      lang={DEFAULT_LOCALE}
      suppressContentEditableWarning
      suppressHydrationWarning
    >
      <head>
        <style id="genesis-brand-theme">{brandCSS(brand)}</style>
      </head>
      <body>
        <BrandProvider brand={brand}>
          <ThemeProvider
            attribute="class"
            enableSystem
            disableTransitionOnChange
          >
            {children}
          </ThemeProvider>
        </BrandProvider>
      </body>
    </html>
  );
}
