#!/usr/bin/env zsh
# gx 安装器隔离演练：mktemp HOME 中真实执行 gx/install.sh（本地模式），
# 断言部署物就位、隔离 zsh 可加载、幂等重装不产生新备份、
# 既有配置被备份、--uninstall 可恢复、自定义 ZSH 路径正确改写 zshrc。
# 用法：zsh tests/gx_install_smoke.zsh
# 失败输出 FAIL 行并以非零退出；只写 mktemp 临时目录，不碰真实 $HOME。
set -u

# 安装器接受外部 ZSH 和 gitstatus 缓存路径；演练必须清除，避免写入当前 Shell 环境。
unset ZSH ZSH_CUSTOM ZSH_CACHE_DIR ZSH_COMPDUMP GX_HOME GITSTATUS_CACHE_DIR

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

# PTY 真交互验证：zsh -i -c 无 tty 时 gitstatus 无法拉起（harness 伪影，非缺陷），
# 必须用伪终端让提示符真实渲染，断言 VCS 状态由部署的 gitstatusd 填充。
if command -v script >/dev/null 2>&1; then
  git_dir="$tmp/probe-repo"
  git init -q "$git_dir"
  { sleep 5; printf 'cd %s\n' "$git_dir"; sleep 4
    printf 'print -r -- PTY-VCS=${VCS_STATUS_LOCAL_BRANCH:-unset}\n'; sleep 2
    printf 'exit\n'; } \
    | env HOME="$home_a" ZDOTDIR="$home_a" timeout 45 script -qec "zsh -i" /dev/null \
      > "$tmp/pty.out" 2>&1
  tr -d '\r' < "$tmp/pty.out" | grep -aq 'PTY-VCS=' \
    || fail "PTY probe produced no output (interactive session failed to start)"
  tr -d '\r' < "$tmp/pty.out" | grep -aq 'PTY-VCS=unset' \
    && fail "PTY interactive session: VCS status not populated by gitstatusd"
fi

# 交互加载后只允许 omz 的 .zcompdump-<host>-<ver> 一族：出现无后缀 .zcompdump 说明
# ~/.zshenv 的 skip_global_compinit 没有拦住 Ubuntu /etc/zsh/zshrc 的全局 compinit。
dumps=("$home_a"/.zcompdump*(N))
[ $#dumps -ge 1 ] || fail "no .zcompdump-* produced by omz compinit"
for dump in "${dumps[@]}"; do
  [[ "${dump:t}" == .zcompdump-* ]] || fail "unexpected compdump ${dump:t} (global compinit not skipped)"
done

# ---------------------------------------------------------------- 场景 B：幂等重装 + 既有配置备份 + 忙二进制原子替换

# 回归实测的 ETXTBSY：让已部署 gitstatusd 处于运行中且内容与仓库不同，
# 重装必须走临时副本 + mv 原子替换，而不是直接 cp 覆盖（Text file busy）。
pkill -f "$home_a/.cache/gitstatus/gitstatusd" 2>/dev/null
sleep 1
printf '\n' >> "$home_a/.cache/gitstatus/gitstatusd-linux-x86_64"
( sleep 30 | "$home_a/.cache/gitstatus/gitstatusd-linux-x86_64" \
    -G v1.5.4 -s 1 -u 1 -d 1 -c 1 -m -1 -v FATAL -t 32 >/dev/null 2>&1 ) &
busy_daemon=$!

echo "# legacy config" > "$home_a/.zshrc"
# custom/ 是用户运行时层（自装插件/片段），.gx-managed 重装必须原样保留；
# 与仓库同名的文件（custom/example.zsh）以用户版本为准。
mkdir -p "$zsh_a/custom/plugins/mine"
echo "# mine plugin" > "$zsh_a/custom/plugins/mine/mine.plugin.zsh"
echo "# user snippet" > "$zsh_a/custom/user.zsh"
echo "# user example overrides repo" > "$zsh_a/custom/example.zsh"
# 安装器清理部署 HOME 内全部 compdump：omz 的 .zcompdump-<host>-<ver> 与
# Ubuntu 全局 compinit 留下的无后缀 .zcompdump 都要清。
echo stale > "$home_a/.zcompdump"
echo stale > "$home_a/.zcompdump-stale-0.0"
sh "$installer" --home "$home_a" --skip-apt --skip-chsh --unattended \
  > "$tmp/inst-b.out" 2> "$tmp/inst-b.err"
[ $? -eq 0 ] || { cat "$tmp/inst-b.err" >&2; fail "scenario B reinstall exited non-zero"; }
[ -f "$zsh_a/custom/plugins/mine/mine.plugin.zsh" ] || fail "custom plugin lost on reinstall"
grep -q "user snippet" "$zsh_a/custom/user.zsh" 2>/dev/null || fail "custom snippet lost on reinstall"
grep -q "user example overrides repo" "$zsh_a/custom/example.zsh" 2>/dev/null \
  || fail "user custom/example.zsh overwritten by repo copy"
[ -f "$zsh_a/custom/themes/example.zsh-theme" ] || fail "repo custom skeleton missing after reinstall"
[ -f "$zsh_a/custom/themes/powerlevel10k/.gx-managed" ] || fail "p10k not redeployed after reinstall"
grep -q "已回填 custom 层" "$tmp/inst-b.out" || fail "custom restore message absent"
stash=("$home_a"/.gx-custom.*(N) "${TMPDIR:-/tmp}"/gx-custom.*(N))
[ $#stash -eq 0 ] || fail "custom stash dir left behind: $stash"
[ ! -e "$home_a/.zcompdump" ] || fail "bare .zcompdump not cleaned by installer"
[ ! -e "$home_a/.zcompdump-stale-0.0" ] || fail "stale .zcompdump-* not cleaned by installer"
backup=("$home_a"/.zshrc.pre-gx-*(N))
[ $#backup -ge 1 ] || fail "legacy .zshrc not backed up"
grep -q "legacy config" "$backup[1]" || fail "backup content mismatch"
cmp -s "$repo_root/gx/config/zshrc" "$home_a/.zshrc" || fail ".zshrc not restored from repo copy"
cmp -s "$repo_root/gx/bin/gitstatusd-linux-x86_64" "$home_a/.cache/gitstatus/gitstatusd-linux-x86_64" \
  || fail "busy gitstatusd not atomically replaced"
grep -q "gitstatusd v1.5.4" "$tmp/inst-b.out" || fail "gitstatusd replace message absent"
grep -q "zoxide 已一致" "$tmp/inst-b.out" || fail "zoxide identical-skip message absent"
kill "$busy_daemon" 2>/dev/null || true

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

# ---------------------------------------------------------------- 场景 E：wezterm 目标由 git 自管则跳过

home_e="$tmp/home-e"
mkdir -p "$home_e/.config/wezterm/.git"
echo "# self-managed" > "$home_e/.config/wezterm/wezterm.lua"
sh "$installer" --home "$home_e" --skip-apt --skip-chsh --unattended \
  > "$tmp/inst-e.out" 2> "$tmp/inst-e.err"
[ $? -eq 0 ] || { cat "$tmp/inst-e.err" >&2; fail "scenario E install exited non-zero"; }
grep -q "# self-managed" "$home_e/.config/wezterm/wezterm.lua" \
  || fail "git-managed wezterm was replaced"
[ ! -f "$home_e/.config/wezterm/.gx-managed" ] || fail "git-managed wezterm got gx marker"
grep -q "git 自管" "$tmp/inst-e.out" || fail "wezterm git-skip message absent"

print -r -- "GX-INSTALL-SMOKE-OK"
exit 0
