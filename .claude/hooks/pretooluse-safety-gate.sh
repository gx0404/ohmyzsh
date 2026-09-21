#!/usr/bin/env bash
# PreToolUse 安全门：Claude Code 与 ZCode 共用的策略真源（Codex 经包装脚本复用）。
# 协议适配：从 stdin JSON 提取 tool_input.file_path / tool_input.command；
# file_path 可能是绝对路径，先相对化到仓库根再判定。
# 拒绝 → stderr 输出原因并 exit 2（阻断）；放行 → 静默 exit 0。
set -euo pipefail

payload=$(cat)

fields=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # 非 JSON 输入不阻断，交给工具自身报错
tool_input = data.get("tool_input") or {}
if not isinstance(tool_input, dict):
    sys.exit(0)
file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
command = tool_input.get("command") or tool_input.get("cmd") or tool_input.get("script") or ""
print(json.dumps({"file_path": str(file_path), "command": str(command)}))
')
[ -n "$fields" ] || exit 0

file_path=$(printf '%s' "$fields" | python3 -c 'import json,sys; print(json.load(sys.stdin)["file_path"])')
command=$(printf '%s' "$fields" | python3 -c 'import json,sys; print(json.load(sys.stdin)["command"])')

repo_root=$(git rev-parse --show-toplevel 2>/dev/null || exit 0)
rel=${file_path#"$repo_root"/}

# 运行时用户层与仓库内部状态：不可作为编辑目标
case "$rel" in
  custom/*|cache/*|log/*|.git/*)
    echo "deny: $rel 位于运行时目录（custom/cache/log/.git），不属于框架可写面；定制请走插件或 docs/。" >&2
    exit 2
    ;;
esac

# 高破坏性 Git 操作
# 只在命令位置命中（行首、; & | ( ` $( 之后，或 sudo/xargs/bash -c 等包装之后）：
# 文本提及（heredoc 正文、搜索关键字、commit message）不是执行，不得误拦。
hit=$(printf '%s' "$command" | python3 -c '
import re, sys
command = sys.stdin.read()
position = (
    r"(?m)(?:^|[;&|({`]|\$\(|\b(?:sudo|xargs|exec|nohup|env|timeout|then|do|else|bash|sh|zsh|eval)\b"
    r"[^\n;&|]*?[\s\x27\x22])\s*(?:\w+=\S*\s+)*"
)
patterns = (
    r"git(?:\s+-{1,2}[\w-]+(?:[= ]\S+)?)*?\s+push\b[^\n;&|]*\s(?:--force|-f\b)",
    r"git(?:\s+-{1,2}[\w-]+(?:[= ]\S+)?)*?\s+clean\b[^\n;&|]*\s-\w*f",
    r"git(?:\s+-{1,2}[\w-]+(?:[= ]\S+)?)*?\s+filter-(?:branch|repo)\b",
)
print("1" if any(re.search(position + p, command) for p in patterns) else "")
')
if [ -n "$hit" ]; then
  echo "deny: 命令含历史重写或强推模式（$command）；需发布或清理时由用户显式执行。" >&2
  exit 2
fi

exit 0
