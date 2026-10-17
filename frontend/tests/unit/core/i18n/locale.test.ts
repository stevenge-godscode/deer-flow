import { describe, expect, it } from "@rstest/core";

import { detectLocale, normalizeLocale } from "@/core/i18n/locale";
describe("Genesis default language", () => {
  it("uses Chinese for an unset or invalid preference", () => {
    for (const preference of [undefined, null, "", "invalid"]) {
      expect(normalizeLocale(preference)).toBe("zh-CN");
    }
    expect(detectLocale()).toBe("zh-CN");
  });
  it("preserves explicit supported language choices", () => {
    expect(normalizeLocale("en-US")).toBe("en-US");
    expect(normalizeLocale("zh-CN")).toBe("zh-CN");
  });
});
