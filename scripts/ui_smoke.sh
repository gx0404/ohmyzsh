#!/usr/bin/env bash
# 终端证据 smoke（ohmyzsh 的 "UI" 是终端提示符/主题渲染）：
#   场景 A：默认主题 robbyrussell 在临时 git 仓库中的提示符渲染（断言分支名出现）
#   场景 B：agnoster 主题 build_prompt 渲染（断言分支名出现）
#   场景 C：omz version 子命令输出
# 产物写入 make evidence 分配的批次目录（gitignored）；本脚本断言文本内容，
# 截图/读回是后续人工或 agent 步骤（result.json 的 images_reviewed 由读回后置位）。
set -uo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root" || exit 2

evidence_dir=$(python3 scripts/dev_framework.py evidence ui-smoke) || exit 2
echo "evidence: $evidence_dir"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/omz-ui.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home" "$tmp/zdotdir" "$tmp/repo"
git -C "$tmp/repo" init -q
# git 2.28 之前不支持 `init -b`；用 symbolic-ref 设初始分支（兼容 git 2.25）
git -C "$tmp/repo" symbolic-ref HEAD refs/heads/smoke-branch
git -C "$tmp/repo" -c user.email=smoke@local -c user.name=smoke \
  commit -q --allow-empty -m "smoke seed"

render_theme() { # theme, 输出文件, 渲染表达式
  local theme=$1 outfile=$2 expr=$3
  cat > "$tmp/zdotdir/.zshrc" <<ZRC
zstyle ':omz:update' mode disabled
# 渲染断言用同步 git 段：async 模式下 git_prompt_info 读异步缓存，
# 非真实终端（zsh -i -c）中缓存未就绪会得到空段（lib/git.zsh:177 的开关）
zstyle ':omz:alpha:lib:git' async-prompt no
export ZSH="$repo_root"
plugins=(git)
ZSH_THEME=$theme
source "\$ZSH/oh-my-zsh.sh"
cd "$tmp/repo"
ZRC
  env -u GIT_DIR HOME="$tmp/home" ZDOTDIR="$tmp/zdotdir" \
    timeout 90 zsh -i -c "$expr" > "$outfile" 2>&1
}

overall=0

# 场景 A：robbyrussell —— git_prompt_info 直接暴露分支段
render_theme robbyrussell "$evidence_dir/results/robbyrussell.txt" \
  'print -r -- "prompt=$(git_prompt_info)"; print -r -- "PS1=$(print -P -- "$PS1")"'
if grep -q "smoke-branch" "$evidence_dir/results/robbyrussell.txt"; then
  echo "PASS A robbyrussell 渲染含分支名"
else
  echo "FAIL A robbyrussell 渲染缺分支名"; overall=1
fi

# 场景 B：agnoster —— build_prompt 组装完整提示符
render_theme agnoster "$evidence_dir/results/agnoster.txt" \
  '(( $+functions[build_prompt] )) && print -r -- "prompt=$(build_prompt)" || print -r -- "NO build_prompt"'
if grep -q "smoke-branch" "$evidence_dir/results/agnoster.txt"; then
  echo "PASS B agnoster 渲染含分支名"
else
  echo "FAIL B agnoster 渲染缺分支名"; overall=1
fi

# 场景 C：omz 子命令输出
cat > "$tmp/zdotdir/.zshrc" <<ZRC
zstyle ':omz:update' mode disabled
export ZSH="$repo_root"
plugins=(git)
ZSH_THEME=robbyrussell
source "\$ZSH/oh-my-zsh.sh"
ZRC
env -u GIT_DIR HOME="$tmp/home" ZDOTDIR="$tmp/zdotdir" \
  timeout 60 zsh -i -c 'omz version' > "$evidence_dir/results/omz-version.txt" 2>&1
if [ -s "$evidence_dir/results/omz-version.txt" ]; then
  echo "PASS C omz version 有输出"
else
  echo "FAIL C omz version 无输出"; overall=1
fi

# 可选：tmux 文本捕获（有则留档，无则跳过，不算失败）
if command -v tmux >/dev/null 2>&1; then
  tmux -f /dev/null new-session -d -s omz-ui-smoke \
    "env HOME=$tmp/home ZDOTDIR=$tmp/zdotdir ZSH=$repo_root zsh -i" 2>/dev/null || true
  if tmux has-session -t omz-ui-smoke 2>/dev/null; then
    sleep 3
    tmux capture-pane -p -t omz-ui-smoke > "$evidence_dir/results/tmux-capture.txt" 2>/dev/null || true
    tmux kill-session -t omz-ui-smoke 2>/dev/null || true
    echo "INFO tmux 捕获留档：$evidence_dir/results/tmux-capture.txt"
  fi
else
  echo "INFO tmux 未安装，跳过 pane 捕获（文本断言已覆盖）"
fi

python3 - "$evidence_dir" "$overall" <<'PY'
import json, sys
from pathlib import Path
folder, overall = Path(sys.argv[1]), sys.argv[2] == "0"
summary = {
    "task": "ui-smoke",
    "status": "PASS" if overall else "FAIL",
    "scenarios": ["robbyrussell-render", "agnoster-render", "omz-version"],
    "note": "文本断言已完成；截图读回与 result.json 的 images_reviewed 置位是独立后续步骤",
}
(folder / "report" / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "result: $([ $overall -eq 0 ] && echo PASS || echo FAIL)（读回 $evidence_dir/results/ 后置位 images_reviewed）"
exit "$overall"
