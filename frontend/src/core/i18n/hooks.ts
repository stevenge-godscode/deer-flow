"use client";

import { useEffect, useMemo } from "react";

import { brandMessages } from "@/core/branding/config";
import { useBrand } from "@/core/branding/context";

import { useI18nContext } from "./context";
import { getLocaleFromCookie, setLocaleInCookie } from "./cookies";

import { detectLocale, normalizeLocale, type Locale } from "./index";

export function useI18n() {
  const { locale, setLocale, t } = useI18nContext();

  const brand = useBrand();
  const brandedTranslations = useMemo(
    () => brandMessages(t, brand.name),
    [t, brand.name],
  );

  const changeLocale = (newLocale: Locale) => {
    setLocale(newLocale);
    setLocaleInCookie(newLocale);
  };

  // Initialize locale on mount
  useEffect(() => {
    const saved = getLocaleFromCookie();
    if (saved) {
      const normalizedSaved = normalizeLocale(saved);
      setLocale(normalizedSaved);
      if (saved !== normalizedSaved) {
        setLocaleInCookie(normalizedSaved);
      }
      return;
    }

    const detected = detectLocale();
    setLocale(detected);
    setLocaleInCookie(detected);
  }, [setLocale]);

  return {
    locale,
    t: brandedTranslations,
    changeLocale,
  };
}
