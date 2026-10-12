"""Bounded source/public-surface brand gate. User content and legal notice are excluded."""
import ast
import hashlib
import json
import re
import sys
from pathlib import Path


def check(root):
    policy = json.loads((root / "branding/upstream-policy.json").read_text(encoding="utf-8"))
    provenance = json.loads((root / "branding/provenance.json").read_text(encoding="utf-8"))
    logo = root / "frontend/public/branding/genesis-logo.png"
    failures = []
    if hashlib.sha256(logo.read_bytes()).hexdigest() != provenance["logo"]["sha256"]:
        failures.append("official logo digest mismatch")
    for path in (root / "frontend/src").rglob("*"):
        if not path.is_file() or path.suffix not in {".tsx", ".ts"}:
            continue
        relative = path.relative_to(root).as_posix()
        if any(relative == prefix or relative.startswith(prefix + "/") for prefix in policy["allowed_source_exclusions"]):
            continue
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue
            for marker in policy.get("internal_literal_allowlist", {}).get(relative, []):
                line = line.replace(marker, "INTERNAL_PROTOCOL_MARKER")
            if re.search(r"DeerFlow|deerflow\.tech|github\.com/bytedance/deer-flow|/images/deer\.svg", line):
                failures.append(f"{relative}:{number}: upstream brand in business surface")
    for path in (root / "backend/browser_tui").glob("*.py"):
        if path.name.startswith("test_"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"DeerFlow|deerflow\.tech|github\.com/bytedance/deer-flow", node.value):
                failures.append(f"{path.relative_to(root)}:{node.lineno}: upstream brand in generated TUI surface")
    active_about = (root / "frontend/src/components/workspace/settings/about-settings-page.tsx").read_text(encoding="utf-8")
    home = (root / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
    if "about-content" in active_about or "components/landing" in home:
        failures.append("upstream marketing/legal module imported into business UI")
    legal = (root / "frontend/src/legal-notices.ts").read_text(encoding="utf-8")
    match = re.search(r"const notices\s*=\s*(.+?);", legal, flags=re.S)
    try:
        notice = ast.literal_eval(match.group(1).strip()) if match else ""
    except (SyntaxError, ValueError):
        notice = ""
    if not notice.endswith((root / "LICENSE").read_text(encoding="utf-8")):
        failures.append("required upstream copyright/permission notice changed")
    proxy = (root / "frontend/src/proxy.ts").read_text(encoding="utf-8")
    for route in ["/blog/:path*", "/:lang/docs/:path*", "/:lang/harness/:path*", "/showcase/:path*", "/github-stars"]:
        if route not in proxy:
            failures.append("missing upstream route redirect: " + route)
    return {"gate": "genesis-brand-source", "passed": not failures, "failures": failures, "logo_sha256": provenance["logo"]["sha256"], "policy_exclusions": policy["allowed_source_exclusions"], "scope": "owned UI chrome/source only; real page/translation/TUI checks are separate, user content is not rewritten"}


if __name__ == "__main__":
    result = check(Path(__file__).resolve().parents[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["passed"] else 1)
