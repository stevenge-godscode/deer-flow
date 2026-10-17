import { describe, expect, it } from "@rstest/core";

import {
  brandCSS,
  brandMessages,
  brandSchema,
  defaultBrand,
} from "@/core/branding/config";

describe("runtime branding boundary", () => {
  it("changes presentation strings and function results without mutating locale source", () => {
    const source = {
      label: "🦌 DeerFlow",
      message: (n: number) => `DeerFlow retry ${n}`,
      id: "deerflow_project_id",
    };
    const result = brandMessages(source, "Genesis");
    expect(result.label).toBe("Genesis");
    expect(result.message(2)).toBe("Genesis retry 2");
    expect(result.id).toBe(source.id);
    expect(source.label).toBe("🦌 DeerFlow");
  });
  it("preserves user arguments while branding static translated function copy", () => {
    const source = {
      search: (query: string) => `DeerFlow searches for "${query}"`,
    };
    expect(brandMessages(source, "Genesis").search("DeerFlow issue 4027")).toBe(
      'Genesis searches for "DeerFlow issue 4027"',
    );
  });
  it("rejects CSS and URL injection rather than emitting untrusted style", () => {
    expect(() =>
      brandSchema.parse({
        ...defaultBrand,
        light: { ...defaultBrand.light, primary: "red; background:url(evil)" },
      }),
    ).toThrow();
    expect(() =>
      brandSchema.parse({ ...defaultBrand, website: "javascript:alert(1)" }),
    ).toThrow();
  });
  it("uses bounded numeric logo and wordmark sizes", () => {
    expect(defaultBrand.logo).toEqual({
      size: 28,
      compactSize: 28,
      wordmarkSize: 18,
      terminalSize: 36,
    });
    for (const wordmarkSize of [0, 100, "28px; color:red"]) {
      expect(() =>
        brandSchema.parse({
          ...defaultBrand,
          logo: { ...defaultBrand.logo, wordmarkSize },
        }),
      ).toThrow();
    }
    const legacy = { ...defaultBrand };
    Reflect.deleteProperty(legacy, "logo");
    expect(brandSchema.parse(legacy).logo).toEqual({
      size: 40,
      compactSize: 32,
      wordmarkSize: 28,
      terminalSize: 36,
    });
  });
  it("uses the same configured palette for shared controls in both themes", () => {
    const css = brandCSS(defaultBrand);
    expect(css).toContain(`--primary:${defaultBrand.light.primary}`);
    expect(css).toContain(`--sidebar-primary:${defaultBrand.dark.primary}`);
    expect(css).not.toContain("DeerFlow");
  });
});
