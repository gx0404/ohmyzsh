#!/usr/bin/env python3
"""Codex PreToolUse 策略钩子：透传 stdin 给共用安全门，保持策略单一真源。

Codex 的工具事件形状与 Claude 不同（如 apply_patch 无 file_path 字段），
安全门内部按键名宽容提取；本钩子只做协议桥接，不复制判定逻辑。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 按本文件位置（<组件>/.codex/hooks/）定位共用安全门，不依赖 cwd：单仓内会话 cwd 可能是
# 单仓根或任意子目录。as_posix 让 Windows 上的 bash 拿到正斜杠路径。
HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
GATE = ["bash", (HOOKS / "pretooluse-safety-gate.sh").as_posix()]

sys.exit(subprocess.run(GATE, input=sys.stdin.buffer.read(), check=False).returncode)
