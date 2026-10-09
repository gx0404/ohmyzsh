#!/bin/sh
# gx/bundle.sh — 将当前工作树打包为离线安装包（tar.gz，含未提交改动）。
# 排除范围与 gx/install.sh 的部署范围一致（.git 与开发态目录）。
# 用法: sh gx/bundle.sh [输出文件]
# 产物解包后执行: sh gx/install.sh
# 退出码: 0 成功；非 0 失败。
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
branch=$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo snapshot)
out=${1:-"gx-ohmyzsh-$branch-$(date +%Y%m%d).tar.gz"}

tar -czf "$out" -C "$repo" \
  --exclude=./.git \
  --exclude=./.build \
  --exclude=./.playwright \
  --exclude=./.playwright-mcp \
  --exclude=./.graphify-memory \
  --exclude=./graphify-out \
  --exclude=./test-results \
  --exclude=./__pycache__ \
  --exclude=./cache \
  --exclude=./log \
  .

printf 'bundle 已生成: %s\n解包后执行: sh gx/install.sh\n' "$out"
