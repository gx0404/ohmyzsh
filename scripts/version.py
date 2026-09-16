#!/usr/bin/env python3
"""从 CHANGELOG 最大 SemVer 校验/同步显式登记的本项目版本。"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        raise SystemExit("版本检查需要 Python 3.11+，或项目环境已有 tomli；请使用项目环境入口。") from None

from dev_framework import config, within


def current_version() -> str:
    matches = re.findall(r"^##\s+(\d+)\.(\d+)\.(\d+)\s*\((?:TBD|\d{8}|\d{4}-\d{2}-\d{2})\)\s*$",
                         within("CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    if not matches:
        raise ValueError("CHANGELOG 缺少有效的 ## X.Y.Z(日期|TBD) 标题")
    return ".".join(map(str, max(tuple(map(int, match)) for match in matches)))


def replace_toml(body: str, kind: str, package: str | None, version: str) -> tuple[str, str]:
    parsed = tomllib.loads(body)
    if kind == "project-toml":
        old = parsed["project"]["version"]
        pattern = r"(?ms)^\[project\][ \t]*\n.*?(?=^\[|\Z)"
        blocks = list(re.finditer(pattern, body))
    else:
        blocks = [block for block in re.finditer(r"(?ms)^\[\[package\]\][ \t]*\n.*?(?=^\[\[package\]\]|\Z)", body)
                  if tomllib.loads(block.group())["package"][0].get("name") == package]
        if len(blocks) != 1:
            raise ValueError("uv.lock 必须恰有一个指定名称的本项目 package")
        old = tomllib.loads(blocks[0].group())["package"][0]["version"]
    if len(blocks) != 1 or not isinstance(old, str):
        raise ValueError("版本字段必须唯一且为字符串")
    block = blocks[0]
    updated, count = re.subn(r"(?m)^(version\s*=\s*)[\"'][^\"'\n]*[\"']",
                             lambda match: match[1] + json.dumps(version), block.group(), count=1)
    if count != 1:
        raise ValueError("版本字段形态不支持，请使用项目权威版本工具")
    return old, body[:block.start()] + updated + body[block.end():]


def plan(version: str) -> list[tuple[Path, str, str]]:
    output, seen = [], set()
    for target in config().get("version_targets", []):
        path = within(target["path"])
        if path in seen:
            raise ValueError("版本同步目标重复")
        seen.add(path)
        if path.name in {"dev-framework.json", "AGENTS.md", "CHANGELOG.md"}:
            raise ValueError("不能将框架配置或权威文档当作版本镜像")
        body = path.read_text(encoding="utf-8")
        kind = target["kind"]
        if kind == "json":
            data = json.loads(body)
            old = data["version"]
            if not isinstance(old, str):
                raise ValueError("JSON version 必须是字符串")
            data["version"] = version
            # 已一致时保留原始排版；写入时只改变结构化 version 字段。
            updated = body if old == version else json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        elif kind in {"project-toml", "uv-lock"}:
            package = target.get("package")
            if kind == "uv-lock" and not package:
                raise ValueError("uv-lock 必须显式声明本项目 package 名")
            old, updated = replace_toml(body, kind, package, version)
            if old == version:
                updated = body
        else:
            raise ValueError(f"不支持的版本镜像类型：{kind}")
        output.append((path, old, updated))
    return output


def write_one(path: Path, body: str) -> None:
    """逐文件原子替换，先完整校验所有镜像，再开始任何写入。"""
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix=".version-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        version = current_version()
        if not (args.check or args.write):
            print(version)
            return 0
        changes = plan(version)
        stale = [(path, old, body) for path, old, body in changes if old != version]
        if args.write:
            for path, _, body in stale:
                write_one(path, body)
            print(f"同步 {len(stale)} 个版本镜像 → {version}")
            return 0
        if stale:
            print("FAIL 版本镜像不一致：" + ", ".join(path.name for path, _, _ in stale), file=sys.stderr)
            return 1
        print(f"PASS 版本 {version}，镜像 {len(changes)} 个")
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
