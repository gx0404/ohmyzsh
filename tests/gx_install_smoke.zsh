#!/usr/bin/env zsh
# gx 安装器隔离演练：mktemp HOME 中真实执行 gx/install.sh（本地模式），
# 断言部署物就位、隔离 zsh 可加载、幂等重装不产生新备份、
# 既有配置被备份、--uninstall 可恢复、自定义 ZSH 路径正确改写 zshrc。
# 用法：zsh tests/gx_install_smoke.zsh
# 失败输出 FAIL 行并以非零退出；只写 mktemp 临时目录，不碰真实 $HOME。
set -u

repo_root=${0:A:h:h}
installer="$repo_root/gx/install.sh"

fail() { print -u2 "FAIL $*"; exit 1; }
[ -f "$installer" ] || fail "installer missing: $installer"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/gx-smoke.XXXXXX")
trap 'rm -rf "$tmp"' EXIT

# 在隔离 HOME+ZDOTDIR 中起交互 zsh，执行 inner 断言并回读标记。
load_check() {
  local home=$1; shift
  local inner="$1"
  env -u GIT_DIR -u GIT_CEILING_DIRECTORIES HOME="$home" ZDOTDIR="$home" \
    timeout 90 zsh -i -c "$inner" > "$tmp/load.out" 2> "$tmp/load.err"
  local code=$?
  if [ $code -ne 0 ]; then
    print -u2 "FAIL isolated load exited $code"
    print -u2 "--- stderr ---"; cat "$tmp/load.err" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------- 场景 A：全新安装

home_a="$tmp/home-a"
sh "$installer" --home "$home_a" --skip-apt --skip-chsh --unattended \
  > "$tmp/inst-a.out" 2> "$tmp/inst-a.err"
[ $? -eq 0 ] || { cat "$tmp/inst-a.err" >&2; fail "scenario A install exited non-zero"; }

zsh_a="$home_a/.oh-my-zsh"
[ -f "$home_a/.zshrc" ] || fail ".zshrc not deployed"
cmp -s "$repo_root/gx/config/zshrc" "$home_a/.zshrc" || fail ".zshrc differs from gx/config/zshrc"
[ -f "$home_a/.zshenv" ] || fail ".zshenv not deployed"
[ -f "$home_a/.zshrc.local" ] || fail ".zshrc.local not deployed"
[ -f "$home_a/.p10k.zsh" ] || fail ".p10k.zsh not deployed"
[ -f "$zsh_a/oh-my-zsh.sh" ] || fail "omz entry not deployed"
[ -f "$zsh_a/.gx-managed" ] || fail ".gx-managed marker missing in \$ZSH"
[ -f "$zsh_a/custom/themes/powerlevel10k/powerlevel10k.zsh-theme" ] || fail "p10k theme not deployed"
[ -x "$home_a/.cache/gitstatus/gitstatusd-linux-x86_64" ] || fail "gitstatusd not deployed"
[ -x "$home_a/.local/bin/zoxide" ] || fail "zoxide not deployed"
[ -f "$home_a/.config/wezterm/wezterm.lua" ] || fail "wezterm config not deployed"
[ -f "$home_a/.config/wezterm/.gx-managed" ] || fail "wezterm marker missing"
fonts=("$home_a"/.local/share/fonts/JetBrainsMonoNerd/*.ttf(N))
[ $#fonts -eq 4 ] || fail "expected 4 font files, got $#fonts"

# 隔离加载：omz+p10k+插件+别名 全链路就位（p10k 会真实拉起 vendored gitstatusd）。
load_check "$home_a" '
[[ -f "$ZSH/oh-my-zsh.sh" ]] || { print -u2 "FAIL: ZSH entry missing"; exit 1; }
[[ "$ZSH_THEME" == "powerlevel10k/powerlevel10k" ]] || { print -u2 "FAIL: theme not set"; exit 1; }
(( $+functions[p10k] )) || { print -u2 "FAIL: p10k not loaded"; exit 1; }
(( $+aliases[gco] )) || { print -u2 "FAIL: git plugin alias gco missing"; exit 1; }
(( $+aliases[ll] )) || { print -u2 "FAIL: alias ll missing"; exit 1; }
[[ -x "$HOME/.local/bin/zoxide" ]] || { print -u2 "FAIL: zoxide missing"; exit 1; }
v=$(omz version 2>/dev/null); [[ -n "$v" ]] || { print -u2 "FAIL: omz version empty"; exit 1; }
print -r -- "GX-SMOKE-OK zsh=${ZSH:t}"
'
grep -q "GX-SMOKE-OK" "$tmp/load.out" || fail "load marker absent in stdout"

# ---------------------------------------------------------------- 场景 B：幂等重装 + 既有配置备份

echo "# legacy config" > "$home_a/.zshrc"
sh "$installer" --home "$home_a" --skip-apt --skip-chsh --unattended \
  > "$tmp/inst-b.out" 2> "$tmp/inst-b.err"
[ $? -eq 0 ] || { cat "$tmp/inst-b.err" >&2; fail "scenario B reinstall exited non-zero"; }
backup=("$home_a"/.zshrc.pre-gx-*(N))
[ $#backup -ge 1 ] || fail "legacy .zshrc not backed up"
grep -q "legacy config" "$backup[1]" || fail "backup content mismatch"
cmp -s "$repo_root/gx/config/zshrc" "$home_a/.zshrc" || fail ".zshrc not restored from repo copy"

# ---------------------------------------------------------------- 场景 C：--uninstall 恢复备份

sh "$installer" --home "$home_a" --skip-apt --uninstall --unattended \
  > "$tmp/inst-c.out" 2> "$tmp/inst-c.err"
[ $? -eq 0 ] || { cat "$tmp/inst-c.err" >&2; fail "scenario C uninstall exited non-zero"; }
grep -q "legacy config" "$home_a/.zshrc" || fail "uninstall did not restore legacy .zshrc"
[ ! -e "$home_a/.config/wezterm" ] || fail "uninstall left managed wezterm dir"
[ ! -e "$zsh_a/custom/themes/powerlevel10k" ] || fail "uninstall left managed p10k dir"
[ -f "$zsh_a/.gx-managed" ] || fail "uninstall should keep \$ZSH (with marker)"

# ---------------------------------------------------------------- 场景 D：自定义 ZSH 路径改写

home_d="$tmp/home-d"
zsh_d="$home_d/omz-custom-location"
sh "$installer" --home "$home_d" --zsh "$zsh_d" --skip-apt --skip-chsh --unattended \
  > "$tmp/inst-d.out" 2> "$tmp/inst-d.err"
[ $? -eq 0 ] || { cat "$tmp/inst-d.err" >&2; fail "scenario D install exited non-zero"; }
grep -q "^export ZSH=\"$zsh_d\"$" "$home_d/.zshrc" || fail "export ZSH line not rewritten"
load_check "$home_d" '
[[ "$ZSH" == "'"$zsh_d"'" ]] || { print -u2 "FAIL: ZSH mismatch in loaded shell"; exit 1; }
(( $+functions[p10k] )) || { print -u2 "FAIL: p10k not loaded (custom ZSH path)"; exit 1; }
print -r -- "GX-SMOKE-OK-CUSTOM"
'
grep -q "GX-SMOKE-OK-CUSTOM" "$tmp/load.out" || fail "custom-path load marker absent"

print -r -- "GX-INSTALL-SMOKE-OK"
exit 0
