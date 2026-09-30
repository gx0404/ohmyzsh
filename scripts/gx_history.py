#!/usr/bin/env python3
"""只读分析扩展格式 Zsh 历史；标准输出仅含固定白名单命令与计数。

不执行历史、不输出原行、参数、时间戳或源路径。退出码：0 成功，2 输入不可用。
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys


# 输出词汇必须来自常量；禁止把任意参数靠黑名单替换后带入仓库。
COMMANDS = frozenset("""
cd pwd ls ll la l clear exit z zi git gst gss gl gp gd gds ga gaa gc gco gb
rg grep find cat less head tail mkdir cp mv rm ln chmod sudo ssh scp rsync
python python3 pip pip3 uv node npm npx pnpm yarn bun cargo rustc go make cmake
docker docker-compose systemctl journalctl ps top htop df du free uname which
code codex claude opencode kimi herdr zsh bash source echo printf history
curl wget tar unzip apt apt-get conda nvidia-smi tmux wezterm fzf atuin
""".split())
SEEDS = frozenset("""
pwd
ls
ls -la
ls -al
ll
la
l
cd ..
cd -
clear
git status
git status --short
git diff
git diff --stat
git diff --cached
git log --oneline
git branch
gst
gss
gd
gds
gb
df -h
free -h
uname -a
nvidia-smi
docker ps
docker ps -a
docker images
uv --version
python3 --version
node --version
npm --version
codex
codex resume
claude
claude --continue
claude --resume
opencode
kimi
herdr
tmux ls
""".strip().splitlines())
HEADER = re.compile(r"^: [0-9]+:[0-9]+;", re.MULTILINE)


def summarize(data: str) -> dict:
    """以扩展历史头划分事件，多行正文整条处理，不解析为 shell。"""
    headers = list(HEADER.finditer(data))
    if not headers or data[:headers[0].start()].strip():
        raise ValueError("需要 EXTENDED_HISTORY 格式；不猜测普通文本的事件边界")
    families: Counter = Counter()
    seeds: Counter = Counter()
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(data)
        command = data[header.end():end].rstrip("\n")
        # 仅统计行首已知工具，不输出其参数；复杂包装命令归入未分类。
        first = re.match(r"([A-Za-z0-9_-]+)(?:[ \t\n]|$)", command)
        if first and first[1] in COMMANDS:
            families[first[1]] += 1
        # 精选历史必须整条、逐字符匹配，不截取复合命令或多行中的片段。
        if command in SEEDS:
            seeds[command] += 1
    return {
        "schema_version": 1,
        "policy": "fixed-allowlist-v1",
        "events": len(headers),
        "unclassified_events": len(headers) - sum(families.values()),
        "command_counts": dict(sorted(families.items(), key=lambda item: (-item[1], item[0]))),
        "seed_counts": dict(sorted(seeds.items(), key=lambda item: (-item[1], item[0]))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path, help="显式指定输入历史文件（只读）")
    parser.add_argument("--format", choices=("json", "zsh"), default="json")
    args = parser.parse_args()
    try:
        result = summarize(args.history.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        # 异常可能携带私人文件名或原始内容，故只返回固定消息。
        print("无法读取扩展格式 Zsh 历史；未输出历史内容。", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 常用项排后，导入后更易从近期历史找到；无时间戳，避免伪造执行时间。
        for command in reversed(result["seed_counts"]):
            print(command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
