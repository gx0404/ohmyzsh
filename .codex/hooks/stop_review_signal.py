#!/usr/bin/env python3
"""Codex Stop 钩子：透传给共用复审提醒，不复制文案。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 按本文件位置定位共用提醒脚本，不依赖 cwd（同 pre_tool_use_policy.py）。
HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
NOTIFY = ["bash", (HOOKS / "notify_review.sh").as_posix()]

sys.exit(subprocess.run(NOTIFY, input=b"", check=False).returncode)
