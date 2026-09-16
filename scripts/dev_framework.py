#!/usr/bin/env python3
"""开发命令与证据目录入口；配置完整与实际运行分别验证。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "docs/dev-framework.json"


def within(raw: str, *, allow_root: bool = False) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError("路径必须是仓库相对路径")
    parts = PurePosixPath(raw)
    if parts.is_absolute() or ".." in parts.parts or (raw == "." and not allow_root):
        raise ValueError("路径不得越出仓库")
    target = ROOT / raw
    current = target
    while current != ROOT:
        if current.is_symlink():
            raise ValueError("不允许经符号链接访问框架文件或证据")
        current = current.parent
    if not target.resolve().is_relative_to(ROOT):
        raise ValueError("路径解析后越出仓库")
    return target


def config() -> dict:
    data = json.loads(within(CONFIG).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("commands"), dict):
        raise ValueError("开发框架配置版本或 commands 无效")
    if not isinstance(data.get("project"), dict):
        raise ValueError("project 必须是对象")
    evidence_root = data.get("evidence_root")
    if (not isinstance(evidence_root, str) or not re.fullmatch(r"\.[a-zA-Z0-9_-]+", evidence_root)
            or evidence_root in {".git", ".claude", ".codex", ".agents", ".kimi-code", ".zcode", ".venv"}):
        raise ValueError("evidence_root 必须是独立的隐藏证据目录，不能指向业务或工具目录")
    if not isinstance(data.get("ci"), list) or not data["ci"]:
        raise ValueError("ci 必须声明检查入口")
    for target in data["ci"]:
        if not isinstance(target, str) or target in {"setup", "dev", "build", "package", "graph", "kb"}:
            raise ValueError("CI 不可包含安装、服务启动、生成写入或打包目标")
        if target not in data["commands"]:
            raise ValueError(f"CI 引用了未登记目标：{target}")
    for name, item in data["commands"].items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or not isinstance(item, dict):
            raise ValueError("命令名或声明无效")
        state = item.get("status")
        if state not in {"configured", "pending", "not-applicable"}:
            raise ValueError(f"{name} 缺少有效状态")
        if state == "configured":
            argv = item.get("argv")
            if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x or "\0" in x for x in argv):
                raise ValueError(f"{name} 必须使用非空 argv 数组")
            if not within(item.get("cwd", "."), allow_root=True).is_dir():
                raise ValueError(f"{name} 工作目录不存在")
        elif not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError(f"{name} 必须解释 pending / N/A 的原因")
        if name in {"lint", "test"} and state == "not-applicable":
            raise ValueError(f"{name} 是基本质量门，不能 N/A")
    for name in ("lint", "test"):
        if name not in data["commands"] or name not in data["ci"]:
            raise ValueError(f"缺少基础质量门：{name}")
    within(data["evidence_root"])
    return data


def ready(data: dict) -> None:
    pending = [name for name, item in data["commands"].items() if item["status"] == "pending"]
    if data.get("project", {}).get("reviewed") is not True:
        pending.append("项目轮廓与领域规则尚未核实")
    if pending:
        raise ValueError("PENDING: " + ", ".join(pending))


def run(data: dict, target: str) -> int:
    if target not in data["commands"]:
        raise ValueError(f"未知命令：{target}")
    item = data["commands"][target]
    if item["status"] == "pending":
        raise ValueError(f"PENDING {target}: {item['reason']}")
    if item["status"] == "not-applicable":
        print(f"N/A {target}: {item['reason']}")
        return 0
    # 仅显式 run/ci 执行已审阅命令；不使用 shell 拼接和自动重试。
    return subprocess.run(item["argv"], cwd=within(item.get("cwd", "."), allow_root=True),
                          check=False).returncode


def branch() -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    def read(*args: str) -> str:
        result = subprocess.run(["git", "-C", str(ROOT), *args], env=env,
                                capture_output=True, text=True, timeout=3, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    try:
        name = read("branch", "--show-current")
        if name:
            return name
        commit = read("rev-parse", "--short", "HEAD")
        return "detached-" + commit if commit else "no-git"
    except (OSError, subprocess.TimeoutExpired):
        return "no-git"


def component(value: str) -> str:
    # 保留中文；百分号与斜杠编码，避免两个不同分支共用目录。
    text = "".join(ch if ch.isalnum() or ch in "_.-" else quote(ch, safe="") for ch in value)
    if text in {".", ".."}:
        text = text.replace(".", "%2E")
    if len(text.encode()) > 160:
        text = text.encode()[:140].decode(errors="ignore") + "--" + hashlib.sha256(value.encode()).hexdigest()[:12]
    return text or "no-git"


def evidence(data: dict, task: str) -> None:
    if not re.fullmatch(r"[^\W_][\w.-]{0,100}", task):
        raise ValueError("任务名仅限文字、数字、点、下划线和横线")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    branch_name = branch()
    relative = f"{data['evidence_root']}/{component(branch_name)}/{task}/{run_id}"
    folder = within(relative)
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", "--quiet", relative + "/result.json"],
                                env=env, capture_output=True, timeout=3, check=False)
        if result.returncode == 1:
            raise ValueError("证据目录尚未被 Git 忽略，拒绝写入")
        if result.returncode not in {0, 128}:
            raise ValueError("无法确定证据目录的 Git 忽略状态")
    except FileNotFoundError:
        pass  # 无 Git 的候选目录仍可分配证据，不能据此声称跟踪边界已验证。
    folder.mkdir(parents=True, exist_ok=False)
    for name in ("results", "report"):
        (folder / name).mkdir()
    (folder / "result.json").write_text(json.dumps({"status": "PENDING", "task": task,
        "branch": branch_name, "run": run_id, "screenshots": [], "images_reviewed": False,
        "note": "只分配证据目录；尚未运行 UI、截图或读图"}, ensure_ascii=False, indent=2) + "\n")
    print(relative)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["help", "check", "ready", "run", "ci", "doctor", "evidence"])
    parser.add_argument("target", nargs="?")
    args = parser.parse_args()
    try:
        data = config()
        if args.action == "help":
            print("make framework-check / framework-ready / ai-doctor / ci-check")
            print("make version / version-check / version-write / evidence")
            for name, item in data["commands"].items():
                print(f"make {name}: {item['status']}")
            return 0
        elif args.action == "check":
            return subprocess.run([sys.executable, str(ROOT / "scripts/resolve_agent_rules.py"), "--check"], check=False).returncode
        if args.action == "ready":
            ready(data)
            print("PASS 配置完整；实际命令结果须另行验证")
        elif args.action == "run":
            return run(data, args.target or "")
        elif args.action == "ci":
            ready(data)
            for argv in ([sys.executable, str(ROOT / "scripts/resolve_agent_rules.py"), "--check"],
                         [sys.executable, str(ROOT / "scripts/version.py"), "--check"]):
                result = subprocess.run(argv, check=False)
                if result.returncode:
                    return result.returncode
            for target in data["ci"]:
                code = run(data, target)
                if code:
                    return code
        elif args.action == "evidence":
            evidence(data, args.target or "")
        else:
            failed = False
            for name, item in data["commands"].items():
                state = item["status"]
                if state == "configured":
                    cwd = within(item.get("cwd", "."), allow_root=True)
                    executable = item["argv"][0]
                    found = os.access(cwd / executable, os.X_OK) if "/" in executable else bool(shutil.which(executable))
                    print(f"{'FOUND' if found else 'MISSING'} {name}: 可执行文件；未运行")
                    failed |= not found
                else:
                    print(f"{state.upper()} {name}: {item['reason']}")
            print("INFO 此诊断只检查命令入口；已选客户端/MCP/读图能力按 AI_TOOLS 分项验证，未启用项记 N/A。")
            return int(failed)
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
