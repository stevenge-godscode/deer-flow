import { readFile } from "node:fs/promises";

import { brandSchema, defaultBrand } from "./config";

export async function loadBrand() {
  const path = process.env.GENESIS_BRAND_CONFIG;
  return path
    ? brandSchema.parse(JSON.parse(await readFile(path, "utf8")))
    : defaultBrand;
}
