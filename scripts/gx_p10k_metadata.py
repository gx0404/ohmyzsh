#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def runtime_identity(resources: Path, platform: str, zsh_binary_sha256: str) -> str:
    if platform not in {"windows-x64", "ubuntu-amd64"}:
        raise ValueError("unsupported P10k runtime platform")
    if not re.fullmatch(r"[0-9a-f]{64}", zsh_binary_sha256):
        raise ValueError("P10k runtime requires a verified Zsh binary digest")
    theme = resources / "gx/omz-custom/themes/powerlevel10k"
    required = {"powerlevel10k.zsh-theme", "internal/p10k.zsh", "gitstatus/gitstatus.plugin.zsh"}
    files = []
    for path in sorted(theme.rglob("*")):
        if path.is_symlink():
            raise ValueError("P10k packaged source must not contain links")
        if not path.is_file():
            continue
        name = path.relative_to(theme).as_posix()
        if name.endswith((".zwc", ".zwc.old")) or ".tmp." in path.name:
            raise ValueError("P10k packaged source contains runtime compilation output")
        data = path.read_bytes()
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
    if not required.issubset({item["path"] for item in files}):
        raise ValueError("P10k packaged source is incomplete")
    identity = {"schema_version": 1, "platform": platform, "zsh_binary_sha256": zsh_binary_sha256, "files": files}
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
