#!/usr/bin/env bash
# 开发冒烟：一次性 ZDOTDIR/HOME 中启动交互 zsh 加载本仓库，
# 打印 omz version / 主题 / 代表性别名后退出。用于快速验证"能否用"。
set -uo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)

# 构建边界：临时数据不出项目（.build/ 已 gitignored）。
build_tmp="$repo_root/.build/tmp"; mkdir -p "$build_tmp"
tmp=$(mktemp -d "$build_tmp/omz-dev.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home" "$tmp/zdotdir"
cat > "$tmp/zdotdir/.zshrc" <<ZRC
zstyle ':omz:update' mode disabled
export ZSH="$repo_root"
plugins=(git)
ZSH_THEME=robbyrussell
source "\$ZSH/oh-my-zsh.sh"
ZRC

env -u GIT_DIR HOME="$tmp/home" ZDOTDIR="$tmp/zdotdir" \
  timeout 60 zsh -i -c '
    omz version
    print -r -- "theme=$ZSH_THEME"
    print -r -- "gco=${aliases[gco]:-<missing>}"
    print -r -- "prompt=$(print -P -- "$PS1" | head -c 120)"
  '
code=$?
[ $code -eq 0 ] || { echo "FAIL dev shell exited $code" >&2; }
exit $code
