import { readFileSync } from "node:fs";

const site = JSON.parse(
  readFileSync(
    new URL("../../../../branding/site.json", import.meta.url),
    "utf8",
  ),
) as { name: string; description: string; docs: string };

export const BRAND_NAME = site.name;
export const BRAND_DESCRIPTION = site.description;
export const BRAND_DOCS = site.docs;
