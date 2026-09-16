#!/usr/bin/env python3
"""Codex PreToolUse 策略钩子：透传 stdin 给共用安全门，保持策略单一真源。

Codex 的工具事件形状与 Claude 不同（如 apply_patch 无 file_path 字段），
安全门内部按键名宽容提取；本钩子只做协议桥接，不复制判定逻辑。
"""
from __future__ import annotations

import subprocess
import sys

GATE = ["bash", ".claude/hooks/pretooluse-safety-gate.sh"]

sys.exit(subprocess.run(GATE, input=sys.stdin.buffer.read(), check=False).returncode)
