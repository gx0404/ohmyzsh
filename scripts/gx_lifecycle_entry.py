#!/usr/bin/env python3
"""make test-heavy：仅在可丢弃环境中验收显式指定的真实安装包。"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = os.environ.get("GX_PACKAGE_MANIFEST")
    if not manifest:
        print("FAIL: GX_PACKAGE_MANIFEST must name the real package manifest; no installer was run", file=sys.stderr)
        return 2
    if not (os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and os.environ.get("GITHUB_REPOSITORY") == "gx0404/ohmyzsh"):
        print("FAIL: make test-heavy requires a GitHub-hosted disposable runner. For an explicitly authorized disposable VM, use scripts/gx_lifecycle.py directly.", file=sys.stderr)
        return 2
    batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    evidence = Path(os.environ.get("GX_LIFECYCLE_EVIDENCE", str(ROOT / "dist/gx-lifecycle" / batch))).resolve()
    command = [sys.executable, str(ROOT / "scripts/gx_lifecycle.py"), "--manifest", manifest,
               "--evidence", str(evidence)]
    for variable, option in (("GX_UPGRADE_INSTALLER", "--upgrade-installer"),
                             ("GX_UPGRADE_MANIFEST", "--upgrade-manifest"),
                             ("GX_LIFECYCLE_USER", "--run-as-user")):
        if os.environ.get(variable):
            command.extend([option, os.environ[variable]])
    evidence.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
