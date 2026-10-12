"""Prepare an isolated upstream merge candidate; never update integration or deploy."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=check)


def prepare(root, revision, output):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("use an exact upstream commit SHA")
    if git(root, "status", "--porcelain").stdout.strip():
        raise ValueError("protect dirty source; commit or preserve it before preparing a candidate")
    if output.exists() or not output.parent.is_dir():
        raise ValueError("choose a new worktree path under an existing persistent directory")
    remote = git(root, "remote", "get-url", "upstream", check=False)
    expected = "https://github.com/bytedance/deer-flow.git"
    if remote.returncode or remote.stdout.strip() != expected:
        raise ValueError("configure the verified official upstream remote first")
    if git(root, "cat-file", "-e", revision + "^{commit}", check=False).returncode:
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not proxy:
            raise ValueError("approved execution-environment HTTPS proxy required before source fetch")
        git(root, "-c", "http.proxy=" + proxy, "fetch", "--filter=blob:none", "upstream", revision)
    current = git(root, "rev-parse", "HEAD").stdout.strip()
    branch = "codex/upstream-" + revision[:12] + "-" + current[:8]
    git(root, "worktree", "add", "-b", branch, str(output), current)
    merge = git(output, "merge", "--no-commit", "--no-ff", revision, check=False)
    conflicts = git(output, "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
    report = {"integration_head": current, "upstream_head": revision, "candidate_branch": branch, "candidate_path": str(output), "merge_returncode": merge.returncode, "conflicts": conflicts, "integration_unchanged": git(root, "rev-parse", "HEAD").stdout.strip() == current, "next": "review conflicts; run source brand, frontend checks and affected TUI/permission checks; commit candidate only after gates; no automatic integration merge/push/deploy"}
    (output / "upstream-candidate.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", required=True)
    parser.add_argument("--worktree", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(Path(__file__).resolve().parents[1], args.revision, args.worktree), indent=2))
