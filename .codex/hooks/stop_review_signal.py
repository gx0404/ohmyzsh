#!/usr/bin/env python3
"""Codex Stop 钩子：透传给共用复审提醒，不复制文案。"""
from __future__ import annotations

import subprocess
import sys

NOTIFY = ["bash", ".claude/hooks/notify_review.sh"]

sys.exit(subprocess.run(NOTIFY, input=b"", check=False).returncode)
