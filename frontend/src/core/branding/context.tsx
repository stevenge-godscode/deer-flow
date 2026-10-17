"use client";

import { createContext, useContext, type ReactNode } from "react";

import { defaultBrand, type Brand } from "./config";

const BrandContext = createContext<Brand>(defaultBrand);
export function BrandProvider({
  brand,
  children,
}: {
  brand: Brand;
  children: ReactNode;
}) {
  return (
    <BrandContext.Provider value={brand}>{children}</BrandContext.Provider>
  );
}
export function useBrand() {
  return useContext(BrandContext);
}
