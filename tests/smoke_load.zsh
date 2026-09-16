#!/usr/bin/env zsh
# 隔离加载 smoke：在一次性 ZDOTDIR/HOME 中加载本仓库 oh-my-zsh.sh，
# 断言核心函数/别名就位、omz CLI 可用、退出码 0。
# 用法：zsh tests/smoke_load.zsh [--plugins git,docker,kubectl]
#   默认插件集 git；--plugins 指定组合（集成变体）。
# 失败输出 FAIL 行并以非零退出；不写任何仓库目录。
set -u

repo_root=${0:A:h:h}
plugin_list="git"
while [ $# -gt 0 ]; do
  case "$1" in
    --plugins) plugin_list="$2"; shift 2 ;;
    *) print -u2 "usage: $0 [--plugins a,b,c]"; exit 2 ;;
  esac
done

# 每插件一个已知符号（来自对应 *.plugin.zsh 的真实定义，勿凭记忆改）
typeset -A known_symbol=( git gco docker dbl kubectl k )
assert_symbols=()
for p in ${(s:,:)plugin_list}; do
  if [ -f "$repo_root/plugins/$p/$p.plugin.zsh" ] || [ -f "$repo_root/plugins/$p/_$p" ]; then
    [ -n "${known_symbol[$p]:-}" ] && assert_symbols+=("$p:${known_symbol[$p]}")
  else
    print -u2 "FAIL plugin '$p' not found under plugins/"
    exit 1
  fi
done

tmp=$(mktemp -d "${TMPDIR:-/tmp}/omz-smoke.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home" "$tmp/zdotdir"

# 已验证符号断言拼装（zsh 语法，运行在目标 shell 内）
symbol_checks=''
for pair in "${assert_symbols[@]:-}"; do
  [ -z "$pair" ] && continue
  plugin=${pair%%:*}; sym=${pair##*:}
  symbol_checks+="print -r -- \"ASSERT-PLUGIN $plugin\"; (( \$+aliases[$sym] )) || { print -u2 \"FAIL alias $sym (plugin $plugin) missing\"; exit 1; }; "
done

# 注意：heredoc 内的 ${(s:,:)...} 不会拆分（实测 zsh 5.8 行为，与双引号上下文不同），
# 必须先拆成空格分隔字符串再写入 .zshrc。
plugin_spaced="${(j: :)${(s:,:)plugin_list}}"

cat > "$tmp/zdotdir/.zshrc" <<ZRC
zstyle ':omz:update' mode disabled
export ZSH="$repo_root"
plugins=($plugin_spaced)
ZSH_THEME=robbyrussell
source "\$ZSH/oh-my-zsh.sh"
ZRC

inner='
(( $+functions[_omz::version] )) || { print -u2 "FAIL function _omz::version missing (lib/cli.zsh)"; exit 1; }
(( $+functions[git_prompt_info] )) || { print -u2 "FAIL function git_prompt_info missing (lib/prompt_info_functions.zsh)"; exit 1; }
[[ -n "$ZSH_CACHE_DIR" && -d "$ZSH_CACHE_DIR" ]] || { print -u2 "FAIL ZSH_CACHE_DIR invalid: $ZSH_CACHE_DIR"; exit 1; }
v=$(omz version 2>/dev/null); [[ -n "$v" ]] || { print -u2 "FAIL omz version empty"; exit 1; }
print -r -- "OMZ-VERSION $v"
'"$symbol_checks"'
print -r -- "SMOKE-OK plugins=${(j:,:)plugins}"
'

env -u GIT_DIR HOME="$tmp/home" ZDOTDIR="$tmp/zdotdir" \
  timeout 90 zsh -i -c "$inner" > "$tmp/stdout" 2> "$tmp/stderr"
code=$?

if [ $code -ne 0 ]; then
  print -u2 "FAIL isolated load exited $code (plugins=$plugin_list)"
  print -u2 "--- stderr ---"; cat "$tmp/stderr" >&2
  exit 1
fi
if grep -q "plugin .* not found" "$tmp/stderr"; then
  print -u2 "FAIL plugin-not-found warning during load"
  cat "$tmp/stderr" >&2
  exit 1
fi

cat "$tmp/stdout"
exit 0
