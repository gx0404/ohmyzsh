#!/usr/bin/env python3
"""make package 的离线入口；需要显式指定已核验的 GX_DEPENDENCY_BUNDLE。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def commands(environment: dict[str, str], platform: str, output: Path) -> list[list[str]]:
    bundle = environment.get("GX_DEPENDENCY_BUNDLE", "")
    if not bundle:
        raise ValueError("set GX_DEPENDENCY_BUNDLE to an assembled dependency bundle; see docs/RELEASE.md")
    if platform not in {"windows-x64", "ubuntu-amd64"}:
        raise ValueError("GX_PACKAGE_PLATFORM must be windows-x64 or ubuntu-amd64")
    dirty = environment.get("GX_PACKAGE_ALLOW_DIRTY", "0")
    if dirty not in {"0", "1"}:
        raise ValueError("GX_PACKAGE_ALLOW_DIRTY must be 0 or 1")
    script = str(ROOT / "scripts/gx_package.py")
    stage = [sys.executable, script, "stage", "--platform", platform,
             "--ref", environment.get("GX_PACKAGE_REF", "HEAD"), "--dependencies", bundle,
             "--output", str(output / "stage"), "--rustc", environment.get("GX_RUSTC", "rustc")]
    if dirty == "1":
        stage.append("--allow-dirty")
    build = [sys.executable, script, "build", "--stage", str(output / "stage"),
             "--output", str(output / "artifacts")]
    if platform == "windows-x64":
        iscc = environment.get("GX_ISCC", "")
        if not iscc:
            raise ValueError("set GX_ISCC to an existing Inno Setup compiler; this command does not install it")
        build.extend(["--iscc", iscc])
    else:
        build.extend(["--dpkg-deb", environment.get("GX_DPKG_DEB", "dpkg-deb")])
    return [stage, [sys.executable, script, "verify-stage", "--stage", str(output / "stage")], build]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print argv without reading dependencies or creating outputs")
    args = parser.parse_args(argv)
    try:
        default_platform = "windows-x64" if sys.platform == "win32" else "ubuntu-amd64" if sys.platform == "linux" else "unsupported"
        platform = os.environ.get("GX_PACKAGE_PLATFORM", default_platform)
        base = Path(os.environ.get("GX_PACKAGE_OUTPUT", str(ROOT / "dist/gx"))).resolve()
        batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        output = base / f"{platform}-{batch}"
        argv_list = commands(dict(os.environ), platform, output)
        if args.dry_run:
            print(json.dumps({"output": str(output), "commands": argv_list}, ensure_ascii=False, indent=2))
            return 0
        output.mkdir(parents=True, exist_ok=False)
        for command in argv_list:
            result = subprocess.run(command, cwd=ROOT, check=False)
            if result.returncode:
                return result.returncode
        print(f"Built artifacts: {output / 'artifacts'}")
        print("Installer/PTY validation is still required before release; nothing has been published.")
        return 0
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
