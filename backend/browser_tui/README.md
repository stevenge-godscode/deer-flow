# Native browser TUI

The browser hosts the existing DeerFlow Textual app through pinned `textual-serve` 1.1.3. This is an internal DeerFlow presentation component, not another SSO application or shell service.

A window is bound to the authenticated user and an existing conversation. The Gateway remains the sole authority for Project/Agent identity, thread history, run admission, tool permissions, goal mutation and cancellation. The adapter never opens an embedded default-user client, checkpoint connection or database. Business persistence stays in the existing Thread/Run model; socket/process state is ephemeral. Reload restores the server checkpoint. A thread requires an established server-authored agent binding before opening.

The normal and Custom Agent chat headers share `BrowserTuiTrigger`. Its link opens a new tab/window directly in the click gesture, preserving the main workspace. Only public model/mode/reasoning settings are carried in the URL; user identity, cookies and Project membership are not. Context-changing native commands redirect users to the main UI rather than switching the bound window.

HTTP and WebSocket admission both verify login and thread access; WebSocket checks exact Origin. Active connections revalidate every five seconds. One window per user/conversation and four total windows bound resource use; disconnect, quit and shutdown reap processes. Read-only accounts can inspect their bound state; running/cancelling requires the same Gateway permissions as the web app.

Run with existing DeerFlow dependencies plus the pinned browser-host dependencies, without upgrading the harness:

```sh
TUI_GATEWAY_URL=http://gateway.deerflow-dev.svc.cluster.local \
TUI_PUBLIC_ORIGIN=https://deerflow.example.com \
python -m browser_tui.server
```

Deployment must proxy `/tui/` and its WebSocket to this component on the same app origin. Do not expose an unauthenticated standalone textual-serve listener. Downloads stay in the existing authenticated web artifact UI. HTTP health only describes this hosting process, not business acceptance.

Focused contract tests: `python -m unittest browser_tui.test_client -v`. Mock values in these tests are negative/unit evidence only; actual DEV browser/API/security evidence is required separately. Closing this window is an interruption/disconnect request, not proof that an already executing remote tool has finished; the Gateway's run status is authoritative.
