import { expect, test } from "@playwright/test";

import { BRAND_DOCS } from "./utils/brand";

test.describe("Business documentation routes", () => {
  for (const path of [
    "/en/docs/introduction/core-concepts",
    "/zh/docs/application/quick-start",
    "/en/harness/overview",
  ]) {
    test(`${path} redirects to the company documentation`, async ({
      request,
    }) => {
      const response = await request.get(path, { maxRedirects: 0 });

      expect(response.status()).toBe(307);
      expect(response.headers().location).toBe(BRAND_DOCS);
    });
  }
});
