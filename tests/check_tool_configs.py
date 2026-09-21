#!/usr/bin/env python3
"""工具配置形状回归锁 + 安全门注册入口原样探针。

背景（update-ai-settings skill 2026-09 更新，wezterm 落地沉淀）：
- Codex hooks 必须是数组表（[[hooks.<Event>]]，命令嵌套 .hooks），写成单表会让
  Codex 启动闪退；形状探针拦不住这类错误，必须锁进回归测试防漂移。
- 适配器语言必须与注册调用方式一致：python3 调的 .py 必须是真 Python。
- 门探针除直调引擎外，必须按各工具配置里的原样 command 再走一次注册入口
  （含 git rev-parse 解析与适配器解释器）。
- 探针里的危险命令字面量拆分构造（"git pu" + "sh --force"），防止宿主会话
  挂着同一安全门时把探针命令本身拦掉，表现为「无输出」而非探针失败。

用法：python3 tests/check_tool_configs.py；失败非零退出。
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10：复用已装 tomli，不为检查装依赖
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# --- 1. Codex config.toml 形状锁：hooks 为数组表，命令嵌套 .hooks，timeout 秒 ---
codex = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
hooks = codex.get("hooks", {})
for event in ("PreToolUse", "Stop"):
    entries = hooks.get(event)
    check(f"codex {event} 是数组表", isinstance(entries, list),
          f"实际类型 {type(entries).__name__}（单表会让 Codex 启动闪退）")
    if isinstance(entries, list):
        for entry in entries:
            inner = entry.get("hooks")
            check(f"codex {event} 命令嵌套在 .hooks 数组", isinstance(inner, list)
                  and all(isinstance(item, dict) and "command" in item for item in inner))
            if event == "Stop":
                check("codex Stop 无 matcher", "matcher" not in entry)
            for item in inner or []:
                check(f"codex {event} timeout 是秒制整数",
                      isinstance(item.get("timeout"), int) and 0 < item.get("timeout", 0) <= 600)

# --- 2. ZCode config.json 形状锁：hooks.enabled + 毫秒 timeoutMs ---
zcode = json.loads((ROOT / ".zcode/config.json").read_text(encoding="utf-8"))
zh = zcode.get("hooks", {})
check("zcode hooks.enabled 为 true", zh.get("enabled") is True)
for event, entries in zh.get("events", {}).items():
    for entry in entries:
        for item in entry.get("hooks", []):
            timeout_ms = item.get("timeoutMs")
            check(f"zcode {event} timeoutMs 是毫秒整数",
                  isinstance(timeout_ms, int) and timeout_ms >= 1000,
                  f"实际 {timeout_ms!r}（秒值移植错误）")

# --- 3. Claude settings.json：hook 引用的脚本存在；deny 含 custom/ 防线 ---
claude = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
for entry in claude.get("hooks", {}).get("PreToolUse", []):
    for item in entry.get("hooks", []):
        args = item.get("args", [])
        for arg in args:
            if arg.endswith(".sh"):
                path = Path(arg.replace("${CLAUDE_PROJECT_DIR}", str(ROOT)))
                check(f"claude hook 脚本存在: {path.name}", path.is_file())
deny = claude.get("permissions", {}).get("deny", [])
check("claude deny 含 custom/ 写入防线", any("custom/" in rule for rule in deny))

# --- 4. 适配器语言一致性：.codex/hooks/*.py 必须是真 Python（ast 可解析）---
for py in sorted((ROOT / ".codex/hooks").glob("*.py")):
    try:
        ast.parse(py.read_text(encoding="utf-8"))
        check(f"codex 适配器是真 Python: {py.name}", True)
    except SyntaxError as exc:
        check(f"codex 适配器是真 Python: {py.name}", False, str(exc))

# --- 5. 注册入口原样探针：按各工具配置里的 command 字符串原样执行 ---
def probe(command: str, label: str) -> None:
    denied = run_gate(command, dangerous_payload())
    allowed = run_gate(command, benign_payload())
    check(f"{label} 注册入口拒绝危险写入", denied == 2, f"exit={denied}")
    check(f"{label} 注册入口放行合法写入", allowed == 0, f"exit={allowed}")


def run_gate(command: str, payload: str) -> int:
    result = subprocess.run(["bash", "-c", command], input=payload.encode(),
                            capture_output=True, cwd=ROOT, timeout=30, check=False)
    return result.returncode


def dangerous_payload() -> str:
    # 危险命令字面量拆分构造：宿主会话可能挂着被测的同一安全门，
    # 完整字面量会让探针命令本身被拦（表现为「无输出」而非探针失败）。
    force = "git pu" + "sh --force origin master"
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": force}})


def benign_payload() -> str:
    return json.dumps({"tool_name": "Write",
                       "tool_input": {"file_path": str(ROOT / "docs/ok.md")}})


zcode_pre = zcode["hooks"]["events"]["PreToolUse"][0]["hooks"][0]["command"]
probe(zcode_pre, "zcode")
codex_pre = (hooks["PreToolUse"][0]["hooks"][0]["command"])
probe(codex_pre, "codex")

# --- 6. 命令位置语义：真执行必拦，文本提及（heredoc/搜索/commit message）放行 ---
GATE = "bash .claude/hooks/pretooluse-safety-gate.sh"
FORCE = "git pu" + "sh --force"
CLEAN = "git cle" + "an -fd"


def bash_payload(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


for executed in (
    f"{FORCE} origin master",
    f"make test && {FORCE}",
    f"bash -c '{FORCE} origin master'",
    f"GIT_TRACE=1 {CLEAN}",
    f"bash <<'EOF'\n{CLEAN}\nEOF",
    "git -C /tmp/x pu" + "sh -f origin master",
    "git filter-" + "branch --all",
):
    code = run_gate(GATE, bash_payload(executed))
    check(f"命令位置拒绝: {executed!r}", code == 2, f"exit={code}")
for mentioned in (
    f"rg '{FORCE}' docs/",
    f"python3 - <<'PYEOF'\ntext = '禁 {FORCE} 与 {CLEAN}'\nprint(len(text))\nPYEOF",
    f"git commit -m 'docs: 说明为何禁 {FORCE}'",
):
    code = run_gate(GATE, bash_payload(mentioned))
    check(f"文本提及放行: {mentioned!r}", code == 0, f"exit={code}")

print(f"config-shapes: {'FAIL ' + str(len(failures)) if failures else 'all PASS'}")
sys.exit(1 if failures else 0)
