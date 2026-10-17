import { z } from "zod";

import defaults from "../../../../branding/site.json";

const color = z.string().regex(/^#[0-9a-fA-F]{6}$/);
const palette = z
  .object({
    background: color,
    foreground: color,
    surface: color,
    muted: color,
    mutedForeground: color,
    primary: color,
    primaryForeground: color,
    border: color,
  })
  .strict();
const text = z
  .string()
  .trim()
  .min(1)
  .max(120)
  .regex(/^[^<>\x00-\x1f]+$/);
const https = z
  .string()
  .url()
  .refine(
    (value) =>
      new URL(value).protocol === "https:" &&
      !new URL(value).username &&
      !new URL(value).password,
  );
const logo = z
  .object({
    size: z.number().int().min(20).max(64),
    compactSize: z.number().int().min(20).max(48),
    wordmarkSize: z.number().int().min(18).max(36),
    terminalSize: z.number().int().min(20).max(64),
  })
  .strict()
  .default({ size: 40, compactSize: 32, wordmarkSize: 28, terminalSize: 36 });
export const brandSchema = z
  .object({
    version: text,
    name: text,
    company: text,
    title: text,
    description: text,
    website: https,
    docs: https,
    support: z.string().regex(/^mailto:[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$/),
    logo,
    light: palette,
    dark: palette,
  })
  .strict();
export type Brand = z.infer<typeof brandSchema>;
export const defaultBrand = brandSchema.parse(defaults);

/** Presentation-only adapter; does not rewrite API identities, history or licenses. */
export function brandMessages<T>(value: T, name: string): T {
  if (typeof value === "string")
    return value.replace(/🦌\s*/g, "").replace(/DeerFlow/g, name) as T;
  if (typeof value === "function")
    return ((...args: unknown[]) => {
      const output = (value as (...args: unknown[]) => unknown)(...args);
      if (typeof output !== "string") return brandMessages(output, name);
      const strings: string[] = [];
      const collect = (item: unknown) => {
        if (typeof item === "string" && item) strings.push(item);
        else if (Array.isArray(item)) item.forEach(collect);
        else if (item && typeof item === "object")
          Object.values(item).forEach(collect);
      };
      args.forEach(collect);
      const protectedValues = [...new Set(strings)].sort(
        (a, b) => b.length - a.length,
      );
      let prefix = "\uE000GENESIS_ARG_";
      while (output.includes(prefix) || name.includes(prefix)) prefix += "_";
      const markers = protectedValues.map(
        (text, index) => [text, `${prefix}${index}\uE001`] as const,
      );
      const valuesToMarkers = new Map(markers);
      const pattern = protectedValues
        .map((text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
        .join("|");
      const protectedOutput = pattern
        ? output.replace(
            new RegExp(pattern, "g"),
            (text) => valuesToMarkers.get(text) ?? text,
          )
        : output;
      let result = brandMessages(protectedOutput, name);
      for (const [text, marker] of markers)
        result = result.replaceAll(marker, text);
      return result;
    }) as T;
  if (Array.isArray(value))
    return value.map((item) => brandMessages(item, name)) as T;
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        brandMessages(item, name),
      ]),
    ) as T;
  return value;
}

export function brandCSS(brand: Brand): string {
  const tokens = {
    background: "background",
    foreground: "foreground",
    card: "surface",
    "card-foreground": "foreground",
    popover: "surface",
    "popover-foreground": "foreground",
    primary: "primary",
    "primary-foreground": "primaryForeground",
    secondary: "muted",
    "secondary-foreground": "foreground",
    muted: "muted",
    "muted-foreground": "mutedForeground",
    accent: "muted",
    "accent-foreground": "foreground",
    border: "border",
    input: "border",
    ring: "primary",
    sidebar: "surface",
    "sidebar-foreground": "foreground",
    "sidebar-primary": "primary",
    "sidebar-primary-foreground": "primaryForeground",
    "sidebar-accent": "muted",
    "sidebar-accent-foreground": "foreground",
    "sidebar-border": "border",
    "sidebar-ring": "primary",
  } as const;
  return (
    (
      [
        [":root", brand.light],
        [".dark", brand.dark],
      ] as const
    )
      .map(
        ([selector, palette]) =>
          `${selector}{${Object.entries(tokens)
            .map(([token, key]) => `--${token}:${palette[key]}`)
            .join(";")}}`,
      )
      .join("\n") +
    '\nbody{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}.font-serif{font-family:inherit}'
  );
}
