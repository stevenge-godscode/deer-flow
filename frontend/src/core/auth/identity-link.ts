import { readCsrfCookie } from "./csrf";
import { parseAuthError } from "./types";

/** Prove the local account before starting a separately verified OIDC login. */
export async function beginIdentityLink(input: {
  provider: string;
  email: string;
  password: string;
  rememberMe: boolean;
  next: string;
}): Promise<string> {
  const login = await fetch("/api/v1/auth/login/local", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      username: input.email,
      password: input.password,
      remember_me: String(input.rememberMe),
    }),
  });
  if (!login.ok) throw new Error(parseAuthError(await login.json()).message);
  const csrf = readCsrfCookie();
  if (!csrf)
    throw new Error(
      "Account ownership proof could not be initialized. Please retry.",
    );
  const response = await fetch(
    `/api/v1/auth/oauth/${encodeURIComponent(input.provider)}/link`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({
        password: input.password,
        next: input.next,
        remember_me: input.rememberMe,
      }),
    },
  );
  if (!response.ok)
    throw new Error(parseAuthError(await response.json()).message);
  const result = (await response.json()) as { authorization_url?: string };
  const destination = new URL(result.authorization_url ?? "");
  if (
    destination.protocol !== "https:" ||
    destination.username ||
    destination.password
  )
    throw new Error("Invalid identity authorization destination");
  return destination.href;
}
