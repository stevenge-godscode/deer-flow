import { expect, test } from "@playwright/test";

import { BRAND_DESCRIPTION, BRAND_NAME } from "./utils/brand";
import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Landing page", () => {
  test("renders the header and hero section", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.locator("header").first().getByText(BRAND_NAME, { exact: true }),
    ).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toContainText(BRAND_DESCRIPTION);

    await expect(
      page.getByRole("link", { name: "打开智能体工作台" }),
    ).toBeVisible();
  });

  for (const width of [320, 375, 390]) {
    test(`does not overflow at ${width}px width`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto("/");

      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width);
      await expect(page.locator("main").first()).toBeInViewport();
    });
  }

  test("workspace link navigates to a new chat", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/");

    const getStarted = page.getByRole("link", { name: "打开智能体工作台" });
    await getStarted.click();

    // Should redirect to /workspace/chats/new
    await page.waitForURL("**/workspace/chats/new");
    await expect(page).toHaveURL(/\/workspace\/chats\/new/);
  });
});
