#!/usr/bin/env zsh
# gx 安装器隔离演练：mktemp HOME 中真实执行 gx/install.sh（本地模式），
# 断言部署物就位、隔离 zsh 可加载、幂等重装不产生新备份、
# 既有配置被备份、--uninstall 可恢复、自定义 ZSH 路径正确改写 zshrc。
# 用法：zsh tests/gx_install_smoke.zsh
# 失败输出 FAIL 行并以非零退出；只写 mktemp 临时目录，不碰真实 $HOME。
set -u

# 安装器会读取宿主的 ZSH / gitstatus 缓存等环境变量；演练一律清除作为纵深防御
# （安装器自身的 --home 与环境 ZSH 互锁由场景 G/H 用 $tmp 内的假目录专门验证，
# 互锁回归时受损的只是临时目录）。
unset ZSH ZSH_CUSTOM ZSH_CACHE_DIR ZSH_COMPDUMP GX_HOME GITSTATUS_CACHE_DIR GX_KEEP_BACKUPS

repo_root=${0:A:h:h}
installer="$repo_root/gx/install.sh"

fail() { print -u2 "FAIL $*"; exit 1; }
[ -f "$installer" ] || fail "installer missing: $installer"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/gx-smoke.XXXXXX")
# 场景 I 会把某个 HOME 置为只读，清理前先恢复写权限。
trap 'chmod -R u+w "$tmp" 2>/dev/null; rm -rf "$tmp"' EXIT

# 所有安装器调用（含需要传环境变量的场景，写成前缀 VAR=value）都经这里：TMPDIR 指进
# 沙箱，安装器的 tar 中转文件（gx-omz.*）不落共享 /tmp、残留断言只需扫描 $tmp；宿主
# 可能导出的 ZSH/GX_* 在这里再剥一次（纵深防御，不依赖脚本顶部的 unset）。
run_installer() {
  local -a pre
  while (( $# )) && [[ $1 == [A-Za-z_]*=* ]]; do pre+=("$1"); shift; done
  env -u ZSH -u ZSH_CUSTOM -u ZSH_COMPDUMP -u GX_HOME -u GX_KEEP_BACKUPS \
    TMPDIR="$tmp" "${pre[@]}" sh "$installer" "$@"
}

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
run_installer --home "$home_a" --skip-apt --skip-chsh --unattended \
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
# --home 重定向时 fc-cache 的 per-user 缓存必须落在部署 HOME（XDG_CACHE_HOME 改写），
# 否则演练会往真实 ~/.cache/fontconfig 写缓存。
if command -v fc-cache >/dev/null 2>&1; then
  fccache=("$home_a"/.cache/fontconfig/*(N))
  [ $#fccache -ge 1 ] || fail "fontconfig cache not written under isolated HOME (leaked to real ~/.cache?)"
fi

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
# 当前主机/版本的 dump（omz 的 ZSH_COMPDUMP 口径），场景 B 断言重装后它被保留且仍有效。
dump_cur="$home_a/.zcompdump-${HOST/.*/}-$ZSH_VERSION"
[ -f "$dump_cur" ] || fail "current-host compdump ${dump_cur:t} missing after interactive load"

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
# 安装器只清 Ubuntu 全局 compinit 留下的无后缀 .zcompdump 与其他主机/版本的
# .zcompdump-*；当前 <host>-<ver> 一族在源快照指纹未变时保留。
echo stale > "$home_a/.zcompdump"
echo stale > "$home_a/.zcompdump-stale-0.0"
# omz 的 zrecompile 互斥锁是**目录**（oh-my-zsh.sh 用 command mkdir 创建，异常退出即
# 残留；真实 HOME 就有一份）。它落在同一个 .zcompdump-* glob 上，清理必须容错：
# 回归形态是安装器在 set -eu 下被 rm 的「Is a directory」打断，且摘要不再打印。
mkdir -p "$home_a/.zcompdump-stale-0.0.lock" "$dump_cur.lock"
run_installer --home "$home_a" --skip-apt --skip-chsh --unattended \
  > "$tmp/inst-b.out" 2> "$tmp/inst-b.err"
[ $? -eq 0 ] || { cat "$tmp/inst-b.err" >&2; fail "scenario B reinstall exited non-zero"; }
[ -f "$zsh_a/custom/plugins/mine/mine.plugin.zsh" ] || fail "custom plugin lost on reinstall"
grep -q "user snippet" "$zsh_a/custom/user.zsh" 2>/dev/null || fail "custom snippet lost on reinstall"
grep -q "user example overrides repo" "$zsh_a/custom/example.zsh" 2>/dev/null \
  || fail "user custom/example.zsh overwritten by repo copy"
[ -f "$zsh_a/custom/themes/example.zsh-theme" ] || fail "repo custom skeleton missing after reinstall"
[ -f "$zsh_a/custom/themes/powerlevel10k/.gx-managed" ] || fail "p10k not redeployed after reinstall"
grep -q "已回填 custom 层" "$tmp/inst-b.out" || fail "custom restore message absent"
# 新树/旧树中转目录与 tar 中转文件不得残留；只扫沙箱内路径（TMPDIR 已指进 $tmp）。
leftover=("$zsh_a".gx-new-*(N) "$zsh_a".gx-old-*(N) "$home_a"/.gx-custom.*(N) "$tmp"/gx-omz.*(N))
[ $#leftover -eq 0 ] || fail "installer left intermediate dirs behind: $leftover"
grep -q "残留" "$tmp/inst-b.err" && fail "reinstall reported leftovers on a clean tree"
grep -q "部署完成:" "$tmp/inst-b.out" || fail "installer printed no summary (aborted before print_summary?)"
[ ! -e "$home_a/.zcompdump" ] || fail "bare .zcompdump not cleaned by installer"
[ ! -e "$home_a/.zcompdump-stale-0.0" ] || fail "stale .zcompdump-* not cleaned by installer"
[ ! -e "$home_a/.zcompdump-stale-0.0.lock" ] || fail "stale zrecompile lock dir not cleaned by installer"
[ -d "$dump_cur.lock" ] || fail "current-family lock dir must be left alone (may be held by a live shell)"
rmdir "$dump_cur.lock"   # 留着会让下一次交互加载跳过 zrecompile
# 无差别清除让每次重装的首启多付 119 ms（冷缓存 332 ms）：当前 dump 必须留下，且下次
# 启动 compinit 仍接受它（mtime 不变 = 没有被重建）。
[ -f "$dump_cur" ] || fail "current-host compdump ${dump_cur:t} cleared by reinstall (first start pays compinit again)"
dump_stamp=$(stat -c %y "$dump_cur")
load_check "$home_a" 'print -r -- GX-DUMP-REUSE'
[ "$(stat -c %y "$dump_cur")" = "$dump_stamp" ] || fail "kept compdump was regenerated on next start (omz metadata mismatch?)"
# 「保留当前 dump」整条策略靠 omz 自己的元数据自检兜底（oh-my-zsh.sh::_omz_compdump_has_metadata）：
# fpath 变了就重建。篡改该行验证这条依赖仍成立——否则安装器会把失效缓存留给下次启动。
grep -q '^#omz fpath: ' "$dump_cur" || fail "kept compdump carries no omz fpath metadata to self-invalidate on"
sed -i 's|^#omz fpath: .*|#omz fpath: /gx-smoke-nonexistent-fpath|' "$dump_cur"
dump_stamp=$(stat -c %y "$dump_cur")
load_check "$home_a" 'print -r -- GX-DUMP-INVALIDATE'
[ "$(stat -c %y "$dump_cur")" != "$dump_stamp" ] || fail "compdump with stale fpath metadata was not rebuilt by omz"
grep -q '/gx-smoke-nonexistent-fpath' "$dump_cur" && fail "rebuilt compdump kept the tampered fpath metadata"
# omz 的自检只覆盖 fpath 目录集与 compinit 的「补全文件总数 + zsh 版本」（#omz revision:
# 在无 .git 的快照部署下恒为空），已存在补全文件的内容/#compdef 标签变化它检不出。所以
# 「保留当前 dump」只在源快照指纹与上次部署一致时成立：指纹变了必须连当前一族一起清。
grep -q '^snapshot: cksum-' "$zsh_a/.gx-managed" || fail "deployed \$ZSH carries no snapshot fingerprint"
sed -i 's|^snapshot: .*|snapshot: cksum-0-0|' "$zsh_a/.gx-managed"
run_installer --home "$home_a" --skip-apt --skip-chsh --unattended \
  > "$tmp/inst-b2.out" 2> "$tmp/inst-b2.err"
[ $? -eq 0 ] || { cat "$tmp/inst-b2.err" >&2; fail "scenario B fingerprint reinstall exited non-zero"; }
grep -q "源快照指纹与上次部署不同" "$tmp/inst-b2.out" \
  || fail "installer did not report the changed snapshot fingerprint"
[ ! -e "$dump_cur" ] || fail "compdump kept although the deployed snapshot fingerprint changed"
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

run_installer --home "$home_a" --skip-apt --uninstall --unattended \
  > "$tmp/inst-c.out" 2> "$tmp/inst-c.err"
[ $? -eq 0 ] || { cat "$tmp/inst-c.err" >&2; fail "scenario C uninstall exited non-zero"; }
grep -q "legacy config" "$home_a/.zshrc" || fail "uninstall did not restore legacy .zshrc"
[ ! -e "$home_a/.config/wezterm" ] || fail "uninstall left managed wezterm dir"
[ ! -e "$zsh_a/custom/themes/powerlevel10k" ] || fail "uninstall left managed p10k dir"
[ -f "$zsh_a/.gx-managed" ] || fail "uninstall should keep \$ZSH (with marker)"

# ---------------------------------------------------------------- 场景 D：自定义 ZSH 路径改写

home_d="$tmp/home-d"
zsh_d="$home_d/omz-custom-location"
run_installer --home "$home_d" --zsh "$zsh_d" --skip-apt --skip-chsh --unattended \
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
run_installer --home "$home_e" --skip-apt --skip-chsh --unattended \
  > "$tmp/inst-e.out" 2> "$tmp/inst-e.err"
[ $? -eq 0 ] || { cat "$tmp/inst-e.err" >&2; fail "scenario E install exited non-zero"; }
grep -q "# self-managed" "$home_e/.config/wezterm/wezterm.lua" \
  || fail "git-managed wezterm was replaced"
[ ! -f "$home_e/.config/wezterm/.gx-managed" ] || fail "git-managed wezterm got gx marker"
grep -q "git 自管" "$tmp/inst-e.out" || fail "wezterm git-skip message absent"

# ---------------------------------------------------------------- 场景 F：custom 为符号链接（dotfiles 仓库）时重装原样保留

home_f="$tmp/home-f"
zsh_f="$home_f/.oh-my-zsh"
run_installer --home "$home_f" --skip-apt --skip-fonts --skip-wezterm --skip-chsh --unattended \
  > "$tmp/inst-f.out" 2> "$tmp/inst-f.err"
[ $? -eq 0 ] || { cat "$tmp/inst-f.err" >&2; fail "scenario F install exited non-zero"; }
dotfiles="$tmp/dotfiles-omz-custom"
mv "$zsh_f/custom" "$dotfiles"
ln -s "$dotfiles" "$zsh_f/custom"
echo "# v1 in dotfiles" > "$dotfiles/from-dotfiles.zsh"
run_installer --home "$home_f" --skip-apt --skip-fonts --skip-wezterm --skip-chsh --unattended \
  > "$tmp/inst-f2.out" 2> "$tmp/inst-f2.err"
[ $? -eq 0 ] || { cat "$tmp/inst-f2.err" >&2; fail "scenario F reinstall exited non-zero"; }
[ -L "$zsh_f/custom" ] || fail "symlinked custom was expanded into a real directory on reinstall"
[ "$(readlink "$zsh_f/custom")" = "$dotfiles" ] || fail "custom symlink target changed: $(readlink "$zsh_f/custom")"
grep -q "v1 in dotfiles" "$dotfiles/from-dotfiles.zsh" || fail "dotfiles custom content lost"
[ -f "$zsh_f/custom/themes/powerlevel10k/.gx-managed" ] || fail "p10k not redeployed through custom symlink"
grep -q "符号链接" "$tmp/inst-f2.out" || fail "symlink-preserved message absent"
# 通过链接改文件仍流回 dotfiles 仓库（没有被拷贝断开）。
echo "# v2" > "$zsh_f/custom/from-dotfiles.zsh"
grep -q "v2" "$dotfiles/from-dotfiles.zsh" || fail "edits via \$ZSH/custom no longer reach dotfiles"

# ---------------------------------------------------------------- 场景 G：--home 显式给出时忽略继承的环境 ZSH

# 模拟「从 gx 会话里跑隔离演练」：环境 ZSH 指向另一棵带 .gx-managed 标记的树
# （真实情况就是 ~/.oh-my-zsh）。安装器必须改写到 <home>/.oh-my-zsh，且不碰该树。
foreign="$tmp/foreign-zsh"
mkdir -p "$foreign/custom/plugins/keep"
echo "gx-managed marker (foreign)" > "$foreign/.gx-managed"
echo "# keep me" > "$foreign/custom/plugins/keep/keep.plugin.zsh"
foreign_before=$(cd "$foreign" && find . | sort)
home_g="$tmp/home-g"
env ZSH="$foreign" TMPDIR="$tmp" sh "$installer" --home "$home_g" \
  --skip-apt --skip-fonts --skip-wezterm --skip-chsh --unattended \
  > "$tmp/inst-g.out" 2> "$tmp/inst-g.err"
[ $? -eq 0 ] || { cat "$tmp/inst-g.err" >&2; fail "scenario G install exited non-zero"; }
[ -f "$home_g/.oh-my-zsh/.gx-managed" ] || fail "--home did not deploy to <home>/.oh-my-zsh when env ZSH set"
grep -q "忽略环境 ZSH=$foreign" "$tmp/inst-g.out" || fail "installer did not announce ignoring env ZSH"
[ "$(cd "$foreign" && find . | sort)" = "$foreign_before" ] || fail "env ZSH tree touched despite --home: $foreign"
grep -q "# keep me" "$foreign/custom/plugins/keep/keep.plugin.zsh" || fail "foreign custom content changed"
leftover=("$tmp"/.gx-custom.*(N) "$foreign".gx-new-*(N) "$foreign".gx-old-*(N))
[ $#leftover -eq 0 ] || fail "scenario G left intermediates next to env ZSH: $leftover"

# ---------------------------------------------------------------- 场景 H：环境 ZSH 不在部署 home 之下且未传 --zsh → unattended 拒绝

home_h="$tmp/home-h"
mkdir -p "$home_h"
env ZSH="$foreign" GX_HOME="$home_h" TMPDIR="$tmp" sh "$installer" \
  --skip-apt --skip-fonts --skip-wezterm --skip-chsh --unattended \
  > "$tmp/inst-h.out" 2> "$tmp/inst-h.err"
rc_h=$?
[ $rc_h -eq 1 ] || { cat "$tmp/inst-h.err" >&2; fail "scenario H expected exit 1 (refused), got $rc_h"; }
grep -q -- "--zsh" "$tmp/inst-h.err" || fail "refusal did not tell the user to pass --zsh explicitly"
[ "$(cd "$foreign" && find . | sort)" = "$foreign_before" ] || fail "refused run still touched env ZSH tree"
[ ! -e "$home_h/.oh-my-zsh" ] && [ ! -e "$home_h/.zshrc" ] || fail "refused run deployed something into home"
# --uninstall 走同一道门。
env ZSH="$foreign" GX_HOME="$home_h" TMPDIR="$tmp" sh "$installer" --uninstall --unattended \
  > "$tmp/inst-h2.out" 2> "$tmp/inst-h2.err"
[ $? -eq 1 ] || fail "scenario H: --uninstall bypassed the env ZSH guard"
[ -f "$foreign/custom/plugins/keep/keep.plugin.zsh" ] || fail "refused uninstall touched env ZSH tree"

# ---------------------------------------------------------------- 场景 I：$ZSH 上级不可写 → 中止且旧安装（含 custom）原样在位

if [ "$(id -u)" = 0 ]; then
  print -r -- "scenario I: N/A (root ignores directory permissions)"
else
  home_i="$tmp/home-i"
  zsh_i="$home_i/.oh-my-zsh"
  run_installer --home "$home_i" --skip-apt --skip-fonts --skip-wezterm --skip-chsh --unattended \
    > "$tmp/inst-i.out" 2> "$tmp/inst-i.err"
  [ $? -eq 0 ] || { cat "$tmp/inst-i.err" >&2; fail "scenario I install exited non-zero"; }
  echo "# precious" > "$zsh_i/custom/precious.zsh"
  tree_before=$(cd "$zsh_i" && find . | sort)
  chmod a-w "$home_i"
  run_installer --home "$home_i" --skip-apt --skip-fonts --skip-wezterm --skip-chsh --unattended \
    > "$tmp/inst-i2.out" 2> "$tmp/inst-i2.err"
  rc_i=$?
  chmod u+w "$home_i"
  [ $rc_i -eq 2 ] || { cat "$tmp/inst-i2.err" >&2; fail "scenario I expected exit 2 on unwritable parent, got $rc_i"; }
  [ "$(cd "$zsh_i" && find . | sort)" = "$tree_before" ] || fail "aborted reinstall modified the existing tree"
  grep -q "# precious" "$zsh_i/custom/precious.zsh" || fail "custom content lost on aborted reinstall"
  leftover=("$zsh_i".gx-new-*(N) "$zsh_i".gx-old-*(N) "$tmp"/gx-omz.*(N))
  [ $#leftover -eq 0 ] || fail "aborted reinstall left intermediates: $leftover"
fi

# ---------------------------------------------------------------- 场景 J：.pre-gx-* 备份回收

# 真实升级路径 = 用户改过配置后重装：每次都产生一份 .zshrc.pre-gx-<ts>，此前永不回收
# （真实 HOME 已累积 6 份）。回收策略是「时间戳最小的第一代永久保留 + 最新
# GX_KEEP_BACKUPS 份」——第一代是唯一一份 gx 之前用户自己的配置，删掉就再也回不去；
# --uninstall 恢复最新一份后其余同样按该策略回收；wezterm 目录备份走同一函数。
home_j="$tmp/home-j"
run_installer --home "$home_j" --skip-apt --skip-fonts --skip-chsh --unattended \
  > "$tmp/inst-j0.out" 2> "$tmp/inst-j0.err"
[ $? -eq 0 ] || { cat "$tmp/inst-j0.err" >&2; fail "scenario J install exited non-zero"; }
for i in 1 2 3 4; do
  echo "# mod $i" > "$home_j/.zshrc"
  rm -f "$home_j/.config/wezterm/.gx-managed"   # 去掉标记 = 视为外来目录，须备份
  sleep 1                                        # 备份后缀是秒级时间戳
  run_installer GX_KEEP_BACKUPS=4 --home "$home_j" \
    --skip-apt --skip-fonts --skip-chsh --unattended \
    > "$tmp/inst-j$i.out" 2> "$tmp/inst-j$i.err"
  [ $? -eq 0 ] || { cat "$tmp/inst-j$i.err" >&2; fail "scenario J reinstall $i exited non-zero"; }
done
zshrc_bk=("$home_j"/.zshrc.pre-gx-*(N))
[ $#zshrc_bk -eq 4 ] || fail "GX_KEEP_BACKUPS=4 should keep 4 .zshrc backups, got $#zshrc_bk"
grep -q "mod 1" "$zshrc_bk[1]" || fail "oldest .zshrc backup should be mod 1"
wez_bk=("$home_j"/.config/wezterm.pre-gx-*(N))
[ $#wez_bk -eq 4 ] || fail "GX_KEEP_BACKUPS=4 should keep 4 wezterm backups, got $#wez_bk"
# 默认份数下重装：第一代（mod 1）+ 最新 2 份（mod 4 与本次的 mod 5），中间世代被回收。
echo "# mod 5" > "$home_j/.zshrc"
sleep 1
run_installer --home "$home_j" --skip-apt --skip-fonts --skip-chsh --unattended \
  > "$tmp/inst-j5.out" 2> "$tmp/inst-j5.err"
[ $? -eq 0 ] || { cat "$tmp/inst-j5.err" >&2; fail "scenario J reinstall 5 exited non-zero"; }
zshrc_bk=("$home_j"/.zshrc.pre-gx-*(N))
[ $#zshrc_bk -eq 3 ] || fail "default retention should keep first gen + 2, got $#zshrc_bk: $zshrc_bk"
grep -q "mod 1" "$zshrc_bk[1]" || fail "first-generation .zshrc backup must never be recycled"
grep -q "mod 4" "$zshrc_bk[2]" || fail "second newest .zshrc backup should be mod 4"
grep -q "mod 5" "$zshrc_bk[-1]" || fail "newest .zshrc backup is not the latest user edit"
grep -q "回收旧备份" "$tmp/inst-j5.out" || fail "installer did not report pruned backups"
wez_bk=("$home_j"/.config/wezterm.pre-gx-*(N))
[ $#wez_bk -eq 3 ] || fail "default retention should keep first gen + 2 wezterm backups, got $#wez_bk"
# GX_KEEP_BACKUPS=all 关闭回收：一轮改配置重装只加不减。
echo "# mod all" > "$home_j/.zshrc"
sleep 1
run_installer GX_KEEP_BACKUPS=all --home "$home_j" --skip-apt --skip-fonts --skip-chsh --unattended \
  > "$tmp/inst-ja.out" 2> "$tmp/inst-ja.err"
[ $? -eq 0 ] || { cat "$tmp/inst-ja.err" >&2; fail "scenario J keep-all reinstall exited non-zero"; }
zshrc_bk=("$home_j"/.zshrc.pre-gx-*(N))
[ $#zshrc_bk -eq 4 ] || fail "GX_KEEP_BACKUPS=all should recycle nothing, got $#zshrc_bk"
grep -q "回收旧备份" "$tmp/inst-ja.out" && fail "GX_KEEP_BACKUPS=all still recycled backups"
# 回到默认额度：mod all 之后第一代 + 最新 2 份。
echo "# mod 5b" > "$home_j/.zshrc"; sleep 1
run_installer --home "$home_j" --skip-apt --skip-fonts --skip-chsh --unattended \
  > "$tmp/inst-j5b.out" 2> "$tmp/inst-j5b.err"
[ $? -eq 0 ] || { cat "$tmp/inst-j5b.err" >&2; fail "scenario J reinstall 5b exited non-zero"; }
zshrc_bk=("$home_j"/.zshrc.pre-gx-*(N))
[ $#zshrc_bk -eq 3 ] || fail "default retention after keep-all should be first gen + 2, got $#zshrc_bk"
# --uninstall 恢复最新备份（mod 5b）算作最新一代，其余留第一代 + N-1=1 份（mod all）。
run_installer --home "$home_j" --skip-apt --uninstall --unattended \
  > "$tmp/inst-j6.out" 2> "$tmp/inst-j6.err"
[ $? -eq 0 ] || { cat "$tmp/inst-j6.err" >&2; fail "scenario J uninstall exited non-zero"; }
grep -q "mod 5b" "$home_j/.zshrc" || fail "uninstall did not restore the newest .zshrc backup"
zshrc_bk=("$home_j"/.zshrc.pre-gx-*(N))
[ $#zshrc_bk -eq 2 ] || fail "after uninstall expected first gen + 1 backup, got $#zshrc_bk"
grep -q "mod 1" "$zshrc_bk[1]" || fail "first-generation backup must survive --uninstall"
grep -q "mod all" "$zshrc_bk[-1]" || fail "remaining backup after uninstall should be mod all"
# 保留份数为 1 的卸载：恢复最新后其余（N-1=0 份）全部回收，但第一代仍在。
echo "# mod 6" > "$home_j/.zshrc"; sleep 1
run_installer --home "$home_j" --skip-apt --skip-fonts --skip-chsh --unattended \
  > "$tmp/inst-j7.out" 2> "$tmp/inst-j7.err"
[ $? -eq 0 ] || { cat "$tmp/inst-j7.err" >&2; fail "scenario J reinstall 7 exited non-zero"; }
run_installer GX_KEEP_BACKUPS=1 --home "$home_j" --skip-apt --uninstall --unattended \
  > "$tmp/inst-j8.out" 2> "$tmp/inst-j8.err"
[ $? -eq 0 ] || { cat "$tmp/inst-j8.err" >&2; fail "scenario J uninstall (keep 1) exited non-zero"; }
grep -q "mod 6" "$home_j/.zshrc" || fail "uninstall (keep 1) did not restore the newest .zshrc backup"
zshrc_bk=("$home_j"/.zshrc.pre-gx-*(N))
[ $#zshrc_bk -eq 1 ] || fail "uninstall with GX_KEEP_BACKUPS=1 should leave only the first gen, got $#zshrc_bk"
grep -q "mod 1" "$zshrc_bk[1]" || fail "the single remaining backup must be the pre-gx original (mod 1)"
# 非法保留份数拒绝执行（0 会把本次刚打的备份也删掉）。
run_installer GX_KEEP_BACKUPS=0 --home "$home_j" \
  --skip-apt --skip-fonts --skip-chsh --unattended > "$tmp/inst-j9.out" 2> "$tmp/inst-j9.err"
[ $? -eq 1 ] || fail "GX_KEEP_BACKUPS=0 should be refused with exit 1"

print -r -- "GX-INSTALL-SMOKE-OK"
exit 0
