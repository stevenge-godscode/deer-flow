# Genesis branding and upstream maintenance

Business chrome uses the official 神典信息 / Genesis logo and site tokens. `branding/site.json` is the shared typed public presentation contract. No managed business state, schema or permissions change. Official asset URLs/checksums and the adapted dark palette are recorded in provenance.json.

Web: root server loader (`GENESIS_BRAND_CONFIG`) validates runtime JSON, derives metadata/theme and supplies one BrandProvider. BrandLogo, About, auth and workspace reuse existing primitives. The i18n presentation adapter brands both string and function values without changing upstream locale sources or API/middleware identifiers. `/brand/logo` reads `GENESIS_BRAND_LOGO` at runtime. Immutable versioned ConfigMap plus readonly public logo mount can change these values without a new frontend image; restart only affected frontend/TUI to bind the config revision. Invalid config fails before render. Do not mount executable source into the business frontend or inject arbitrary CSS/JS.

Native TUI: browser_tui subclass reads the same config, replaces only header/composer/generated labels and maps upstream Rich colors locally. No site-packages/harness fork or text rewrite of user history. Public renderer uses the same official logo. All operations continue through existing authenticated APIs; readonly controls and owner/origin checks remain intact.

`/legal` preserves the upstream MIT copyright and permission text. Historical docs/marketing are retained in source for merges; their public routes redirect to official company documentation. User messages, model answers about upstream software, existing files and technical identities are not rewritten. Business chrome does not advertise upstream. Existing technical service and API names remain compatible.

## Upstream candidates

Accepted upstream base: `345f08be00c8a9495079b732a39b46aa9af1584e`. Keep official upstream history and own patches separately identified. `upstream` points only to the official repository; the current accepted branch is not reset to upstream/main.

From a clean persistent DEV worktree:

```
python scripts/prepare_upstream.py --revision <exact-40-char-upstream-SHA> --worktree /workspace/repos/upstream-candidate-<version>
```

The script prepares an isolated branch and merge, reports conflicts, never pushes/deploys/updates integration, and requires the approved environment proxy before a missing upstream commit is fetched. No guessed/latest ref is automatically accepted. Existing old tests/artifact identities are reused only for unchanged boundaries.

Candidate gates: `python scripts/check_branding.py`; frontend optimized build + check + full unit checks at stable HEAD; browser chrome/favicon/About/legal/docs redirects and EN/ZH strings; native TUI header/composer/theme; actual auth/owner/readonly regression when their affected components change. Static scanning is only one layer. Brand-source check has explicit technical/legal/unexposed-source exclusions in upstream-policy.json; never allow a new visible brand string merely to pass a gate. Keep merge conflicts/manual exclusions in the candidate report. General source CI and environment release permissions remain separate.

No functional upstream upgrade, main merge or STG/PROD promotion is part of this branding implementation.

DEV business entry: https://agents.dev.godscode.com.cn (same application/client and existing DEV FRP route). Old technical host redirects at the external DEV edge; IdP client ID, issuer, scopes and roles stay unchanged. Only callback/frontend origin and app display metadata change. New-domain cookies require native login; no cookies are copied between origins.

CI source workflow runs the same brand gate and requires GENESIS_CI_HTTP_PROXY / GENESIS_CI_HTTPS_PROXY / GENESIS_CI_NO_PROXY repository variables before checkout/tool downloads. This fork currently has no registered self-hosted runners; manual DEV gates are actual evidence, not a claim that GitHub-hosted CI or its proxy connectivity has passed. Do not silently fall back to direct source/download requests.

2026-10-12 display decision: use Genesis only in active web, TUI and app-login chrome. Official source-company provenance is retained internally. Shared web logo is 40px (32px in compact navigation); terminal renderer logo is 36px.

The logo object contains bounded numeric icon, compact icon, wordmark and terminal sizes. The shared BrandLogo uses one centered row, the official system font and a 40px icon / 28px wordmark default. Existing configs without logo sizes use compatible defaults; no arbitrary CSS is admitted. Icon/wordmark balance can be changed by a new config revision, without another frontend rebuild.
