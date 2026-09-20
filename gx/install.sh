#!/bin/sh
# gx/install.sh — gx 个人配置层一键安装器（fork 新增，不属于上游 tools/）。
#
# 把 gx/ 固化的 zsh 配置链（omz + p10k + 补全/高亮 + zoxide + 字体 + WezTerm）
# 部署到目标机器的用户目录。双模式：脚本位于仓库内时用本地工作树（离线可用，
# 无需 git）；curl 拉取执行或 --online 时先从 GX_REMOTE 取最新分支再本地部署。
#
# 用法:
#   本地:   sh gx/install.sh [选项]              # 仓库已就位（U 盘/git clone）
#   在线:   sh -c "$(curl -fsSL $GX_REMOTE_URL/gx/install.sh)"
#   仓库内: make gx-install
# 选项:
#   --home <dir>    用户侧部署根目录（默认 $HOME；隔离测试用）。显式给出时忽略
#                   继承的环境变量 ZSH（改用 <home>/.oh-my-zsh）
#   --zsh <dir>     Oh My Zsh 目录（默认 <home>/.oh-my-zsh；等价环境变量 ZSH，
#                   但环境 ZSH 不在 <home> 之下时 unattended 拒绝、交互须确认）
#   --online        忽略本地仓库，强制从 GX_REMOTE 拉取
#   --skip-apt      跳过 apt 包安装（zsh/fzf/autosuggestions/syntax-highlighting）
#   --skip-fonts    跳过 Nerd Font 部署
#   --skip-wezterm  跳过 WezTerm 配置部署
#   --skip-chsh     跳过登录 shell 切换
#   --unattended    全程无交互（stdin 非 tty 时自动生效）
#   --uninstall     恢复 .pre-gx-<ts> 备份并移除安装器管理的产物
#   -h, --help
# 退出码: 0 成功；1 前置检查失败；2 部署失败。
#
# 安全约定: 绝不 rm 用户既有文件——一律 mv 为 *.pre-gx-<时间戳> 备份；
# 仅允许删除带 .gx-managed 标记（本安装器前次部署）的目录；重装时新快照先在
# $ZSH 同级完整就位并合并 $ZSH/custom（用户运行时层，同名以用户为准、符号链接
# 原样保留），再两次 rename 原子替换——任何失败都发生在旧安装原样在位时。
# 不落任何凭据。

set -eu

GX_REMOTE_DEFAULT="https://github.com/gx0404/ohmyzsh.git"
GX_BRANCH_DEFAULT="feature/gx_ohmyzsh"
ZOXIDE_VERSION="0.9.9"
APT_PKGS="zsh git fzf zsh-autosuggestions zsh-syntax-highlighting"
# 部署 $ZSH 时排除的开发态目录（git 仓库与运行时产物不入安装目标）。
REPO_EXCLUDES="--exclude=./.git
--exclude=./.playwright
--exclude=./.playwright-mcp
--exclude=./.graphify-memory
--exclude=./graphify-out
--exclude=./test-results
--exclude=./__pycache__
--exclude=./cache
--exclude=./log"

GX_REMOTE="${GX_REMOTE:-$GX_REMOTE_DEFAULT}"
GX_BRANCH="${GX_BRANCH_DEFAULT}"
GX_HOME="${GX_HOME:-$HOME}"
ZSH_TARGET=""
ZSH_IGNORED=""
OPT_HOME_GIVEN=0
OPT_ZSH_GIVEN=0
OPT_ONLINE=0
OPT_SKIP_APT=0
OPT_SKIP_FONTS=0
OPT_SKIP_WEZTERM=0
OPT_SKIP_CHSH=0
OPT_UNATTENDED=0
OPT_UNINSTALL=0
TS="$(date +%Y%m%d%H%M%S)"
REPO_DIR=""
BACKED_UP=" "

say()  { printf '==> %s\n' "$*"; }
warn() { printf '警告: %s\n' "$*" >&2; }
die()  { printf '错误: %s\n' "$1" >&2; exit "${2:-1}"; }

usage() { sed -n '2,34p' "$0" 2>/dev/null || cat <<'EOF'
用法: sh gx/install.sh [--home <dir>] [--zsh <dir>] [--online]
      [--skip-apt] [--skip-fonts] [--skip-wezterm] [--skip-chsh]
      [--unattended] [--uninstall]
EOF
}

# ---------------------------------------------------------------- 参数解析

while [ $# -gt 0 ]; do
  case "$1" in
    --home)        GX_HOME="${2:?--home 需要参数}"; OPT_HOME_GIVEN=1; shift 2 ;;
    --zsh)         ZSH_TARGET="${2:?--zsh 需要参数}"; OPT_ZSH_GIVEN=1; shift 2 ;;
    --online)      OPT_ONLINE=1; shift ;;
    --skip-apt)    OPT_SKIP_APT=1; shift ;;
    --skip-fonts)  OPT_SKIP_FONTS=1; shift ;;
    --skip-wezterm) OPT_SKIP_WEZTERM=1; shift ;;
    --skip-chsh)   OPT_SKIP_CHSH=1; shift ;;
    --unattended)  OPT_UNATTENDED=1; shift ;;
    --uninstall)   OPT_UNINSTALL=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *)             usage >&2; die "未知参数: $1" 1 ;;
  esac
done

# 去掉 home 末尾斜杠，保证下方「ZSH 是否在 home 之下」的前缀判定稳定。
case "$GX_HOME" in ?*/) GX_HOME="${GX_HOME%/}" ;; esac
if [ -z "$ZSH_TARGET" ]; then
  if [ "$OPT_HOME_GIVEN" -eq 1 ]; then
    # --home 显式给出时忽略继承的环境 ZSH：gx 层部署后的交互 zsh 会 export
    # ZSH=~/.oh-my-zsh，若让它优先，任何从 gx 会话里跑的隔离演练都会把重装的
    # 破坏性路径打到真实 ~/.oh-my-zsh 上。要指向其他目录必须显式传 --zsh。
    ZSH_TARGET="$GX_HOME/.oh-my-zsh"
    [ -z "${ZSH:-}" ] || [ "$ZSH" = "$ZSH_TARGET" ] || ZSH_IGNORED="$ZSH"
  else
    ZSH_TARGET="${ZSH:-$GX_HOME/.oh-my-zsh}"
  fi
fi
ZSH="$ZSH_TARGET"
[ -t 0 ] || OPT_UNATTENDED=1

# ---------------------------------------------------------------- 通用助手

# 目录由本安装器管理当且仅当含 .gx-managed 标记。
is_ours() { [ -f "$1/.gx-managed" ]; }

# $ZSH 来自环境变量而不在部署 home 之下时守门：这是「继承了 gx 会话的 ZSH 却想
# 部署到别处」的典型形态，unattended 直接拒绝（要真的这么做请显式传 --zsh），
# 交互模式要求确认。显式 --zsh 视为用户已确认，不再询问。
guard_zsh_location() {
  [ -z "$ZSH_IGNORED" ] \
    || say "忽略环境 ZSH=$ZSH_IGNORED（已指定 --home，改用 $ZSH；其他路径请显式传 --zsh）"
  [ "$OPT_ZSH_GIVEN" -eq 0 ] || return 0
  case "$ZSH" in "$GX_HOME"/*) return 0 ;; esac
  warn "环境变量 ZSH=$ZSH 不在 home=$GX_HOME 之下"
  [ "$OPT_UNATTENDED" -eq 0 ] \
    || die "unattended 模式拒绝在 home 之外的 ZSH 上操作；确认无误请显式传 --zsh \"$ZSH\"" 1
  printf '确认在 %s 上继续（会重装/卸载该目录）? [y/N] ' "$ZSH"
  read _gz_ans
  case "$_gz_ans" in y|Y) ;; *) die "已取消" 1 ;; esac
}

# 前次安装中断可能留下的同级残留（新树/旧树中转目录、旧版安装器的 custom 暂存）：
# 只提示不清理，内容是否还需要由用户判断。
report_leftovers() {
  for _rl_p in "$ZSH".gx-new-* "$ZSH".gx-old-* "$(dirname "$ZSH")"/.gx-custom.*; do
    [ -e "$_rl_p" ] || continue
    warn "发现前次安装中断的残留: $_rl_p（.gx-old-*/.gx-custom.* 内含当时的 custom 层，确认后可手动删除）"
  done
}

# 备份既有路径（文件或目录）；同批次内已备份过则跳过。
did_backup() {
  case " $BACKED_UP " in *" $1 "*) return 1 ;; esac
  BACKED_UP="$BACKED_UP $1 "
  mv "$1" "$1.pre-gx-$TS"
}

# 替换部署目标目录：外来内容先备份，本安装器旧部署直接覆盖。
# 用法: replace_dir <src> <dst>（src 为快照源，dst 不含末尾斜杠）
replace_dir() {
  _rd_src="$1"; _rd_dst="$2"
  if [ -e "$_rd_dst" ]; then
    if is_ours "$_rd_dst"; then
      rm -rf "$_rd_dst"
    else
      say "备份既有目录: $_rd_dst -> $_rd_dst.pre-gx-$TS"
      did_backup "$_rd_dst" || die "备份失败: $_rd_dst" 2
    fi
  fi
  mkdir -p "$_rd_dst"
  cp -a "$_rd_src/." "$_rd_dst/"
}

# ---------------------------------------------------------------- 仓库获取

# 本地模式：脚本自身位于仓库内（上级目录有 oh-my-zsh.sh 与 gx/ 并存）。
detect_local_repo() {
  _dl_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." 2>/dev/null && pwd) || return 1
  [ -f "$_dl_dir/oh-my-zsh.sh" ] && [ -d "$_dl_dir/gx" ] || return 1
  REPO_DIR="$_dl_dir"
}

# 在线模式：浅取 GX_REMOTE 的 GX_BRANCH 到临时目录（手法同上游 tools/install.sh，
# git < 2.28 无 init -b，用 fetch + checkout）。
fetch_repo_online() {
  command -v git >/dev/null 2>&1 || die "在线模式需要 git" 1
  _fo_tmp=$(mktemp -d "${TMPDIR:-/tmp}/gx-install.XXXXXX")
  say "拉取 $GX_REMOTE ($GX_BRANCH)"
  git init --quiet "$_fo_tmp"
  git -C "$_fo_tmp" remote add origin "$GX_REMOTE"
  git -C "$_fo_tmp" fetch --depth=1 --quiet origin "$GX_BRANCH" \
    || die "拉取分支失败，检查网络或 GX_REMOTE/GX_BRANCH" 1
  git -C "$_fo_tmp" checkout --quiet --force -b "$GX_BRANCH" FETCH_HEAD
  REPO_DIR="$_fo_tmp"
}

acquire_repo() {
  if [ "$OPT_ONLINE" -eq 1 ]; then
    fetch_repo_online
    return
  fi
  detect_local_repo || fetch_repo_online
  # 部署内容自检：仓库内必须有 gx 层，否则可能是 curl 管道拿到了残缺脚本。
  [ -d "$REPO_DIR/gx/config" ] || die "仓库快照缺少 gx/config，非完整 gx 分支" 1
}

# ---------------------------------------------------------------- 部署步骤

install_apt_packages() {
  [ "$OPT_SKIP_APT" -eq 0 ] || { say "跳过 apt 包安装 (--skip-apt)"; return 0; }
  command -v apt-get >/dev/null 2>&1 \
    || { warn "非 apt 系统，请手动安装: $APT_PKGS"; return 0; }
  _ap_missing=""
  for _ap_pkg in $APT_PKGS; do
    dpkg -s "$_ap_pkg" >/dev/null 2>&1 || _ap_missing="$_ap_missing $_ap_pkg"
  done
  [ -n "$_ap_missing" ] || { say "apt 包已齐备"; return 0; }
  if [ "$(id -u)" = 0 ]; then
    _ap_sudo=""
  elif command -v sudo >/dev/null 2>&1; then
    _ap_sudo="sudo"
  else
    warn "无 root/sudo 权限，请手动安装:$_ap_missing"
    return 0
  fi
  # unattended 下 sudo 必须免密（-n），避免卡住管道。
  if [ -n "$_ap_sudo" ] && [ "$OPT_UNATTENDED" -eq 1 ]; then
    sudo -n true 2>/dev/null || { warn "sudo 需要密码且处于 unattended，请手动安装:$_ap_missing"; return 0; }
  fi
  say "安装 apt 包:$_ap_missing"
  DEBIAN_FRONTEND=noninteractive $_ap_sudo apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive $_ap_sudo apt-get install -y -qq $_ap_missing \
    || { warn "apt 安装失败，配置中的存在性守卫会静默跳过对应功能"; return 0; }
}

# 把旧安装的 $ZSH/custom（用户自装插件/主题/片段，不属于快照）合并进尚未就位的
# 新快照树。只读旧树：任何失败都在旧安装原样在位时 die，不存在「暂存后回填」的
# 中间态。用法: merge_custom_layer <旧 $ZSH> <新树>
CUSTOM_MERGED=0

merge_custom_layer() {
  _mc_old="$1/custom"; _mc_new="$2/custom"
  if [ -L "$_mc_old" ]; then
    # 符号链接（指向 dotfiles 仓库的常见做法）整体复刻，不展开成拷贝——展开会让
    # 之后对 $ZSH/custom 的改动不再流回用户仓库。
    rm -rf "$_mc_new"
    cp -a "$_mc_old" "$_mc_new" || die "复刻 custom 符号链接失败，旧安装未改动: $_mc_old" 2
    say "custom 层是符号链接 -> $(readlink "$_mc_old")，原样保留"
    CUSTOM_MERGED=1
    return 0
  fi
  [ -d "$_mc_old" ] || return 0
  mkdir -p "$_mc_new"
  # cp -a 覆盖同名文件，用户版本胜出（含仓库自带的 example.*）。
  cp -a "$_mc_old/." "$_mc_new/" || die "合并 custom 层失败，旧安装未改动: $_mc_old" 2
  # p10k 快照由 deploy_p10k 重新部署，本安装器的旧产物不必带入新树。
  if is_ours "$_mc_new/themes/powerlevel10k"; then
    rm -rf "$_mc_new/themes/powerlevel10k"
  fi
  CUSTOM_MERGED=1
}

deploy_omz_repo() {
  _oz_new="$ZSH.gx-new-$TS"; _oz_old="$ZSH.gx-old-$TS"
  # 新快照先在 $ZSH 同级（同一文件系统，mv 为原子 rename）完整就位；在此之前既有
  # 安装不被改动。同级不可写时（rename 本身也做不了）在这里就中止。
  rm -rf "$_oz_new"
  mkdir -p "$_oz_new" || die "无法创建中转目录 $_oz_new（检查上级目录可写）" 2
  # tar 中转（而非 cp -a）以应用 REPO_EXCLUDES，且失败可见、目标恒为干净快照。
  _oz_tar=$(mktemp "${TMPDIR:-/tmp}/gx-omz.XXXXXX.tar")
  if tar -cf "$_oz_tar" -C "$REPO_DIR" $REPO_EXCLUDES . 2>/dev/null \
      && tar -xf "$_oz_tar" -C "$_oz_new"; then
    rm -f "$_oz_tar"
  else
    rm -f "$_oz_tar"
    rm -rf "$_oz_new"
    die "打包/解包仓库快照失败，既有安装未改动" 2
  fi
  printf 'gx install.sh 管理的 Oh My Zsh 工作树（%s）\n' "$TS" > "$_oz_new/.gx-managed"

  if [ -e "$ZSH" ] || [ -L "$ZSH" ]; then
    if is_ours "$ZSH"; then
      say "更新既有 gx 安装: $ZSH"
      merge_custom_layer "$ZSH" "$_oz_new"
      # 两次 rename 之间屏蔽中断：旧树让位到 .gx-old-<ts>，新树随即就位；第二步
      # 失败则把旧树放回原位。
      trap '' INT TERM HUP
      mv "$ZSH" "$_oz_old" || die "旧安装让位失败: $ZSH，新快照保留在 $_oz_new" 2
      mv "$_oz_new" "$ZSH" || { mv "$_oz_old" "$ZSH"; die "新快照就位失败，已放回旧安装" 2; }
      trap - INT TERM HUP
      rm -rf "$_oz_old"
    else
      say "检测到既有 Oh My Zsh（官方或其他来源），备份迁移"
      did_backup "$ZSH" || die "备份失败: $ZSH，新快照保留在 $_oz_new" 2
      # 只保留最近一次 $ZSH 备份，避免重复安装无限膨胀。
      for _oz_prev in "$ZSH".pre-gx-*; do
        [ -e "$_oz_prev" ] || continue
        [ "$_oz_prev" = "$ZSH.pre-gx-$TS" ] && continue
        say "清理旧备份: $_oz_prev"
        rm -rf "$_oz_prev"
      done
      mv "$_oz_new" "$ZSH" || die "新快照就位失败，备份在 $ZSH.pre-gx-$TS" 2
    fi
  else
    mv "$_oz_new" "$ZSH" || die "新快照就位失败: $ZSH" 2
  fi
  [ "$CUSTOM_MERGED" -eq 0 ] || say "已回填 custom 层: $ZSH/custom"
}

deploy_configs() {
  _dc_pairs="zshrc:.zshrc zshenv:.zshenv zshrc.local:.zshrc.local p10k.zsh:.p10k.zsh"
  for _dc_pair in $_dc_pairs; do
    _dc_src="$REPO_DIR/gx/config/${_dc_pair%%:*}"
    _dc_dst="$GX_HOME/${_dc_pair##*:}"
    if [ -e "$_dc_dst" ] && cmp -s "$_dc_src" "$_dc_dst"; then
      say "已一致，跳过: $_dc_dst"
      continue
    fi
    if [ -e "$_dc_dst" ]; then
      say "备份: $_dc_dst -> $_dc_dst.pre-gx-$TS"
      did_backup "$_dc_dst" || die "备份失败: $_dc_dst" 2
    fi
    if [ "${_dc_pair%%:*}" = zshrc ] && [ "$ZSH" != "$GX_HOME/.oh-my-zsh" ]; then
      # 自定义 ZSH 路径时改写 zshrc 的 export ZSH= 行（手法同上游安装器）。
      sed "s|^export ZSH=.*$|export ZSH=\"$ZSH\"|" "$_dc_src" > "$_dc_dst"
    else
      cp "$_dc_src" "$_dc_dst"
    fi
  done
}

deploy_p10k() {
  _p1_src="$REPO_DIR/gx/omz-custom/themes/powerlevel10k"
  _p1_dst="$ZSH/custom/themes/powerlevel10k"
  replace_dir "$_p1_src" "$_p1_dst"
  say "p10k 主题 -> $_p1_dst"
  printf 'gx install.sh 部署的 powerlevel10k 快照\n' > "$_p1_dst/.gx-managed"
  # 快照不含 gitstatusd 守护进程（上游 gitignore 挡在仓库外），单独补齐。
  deploy_gitstatusd
}

deploy_gitstatusd() {
  _gs_arch=$(uname -m)
  _gs_cache="${GITSTATUS_CACHE_DIR:-$GX_HOME/.cache/gitstatus}"
  _gs_src="$REPO_DIR/gx/bin/gitstatusd-linux-x86_64"
  _gs_dst="$_gs_cache/gitstatusd-linux-x86_64"
  if [ "$_gs_arch" != x86_64 ]; then
    # 非 x86_64 平台不携带二进制；有网络时 gitstatus 会自行下载守护进程。
    warn "架构 $_gs_arch 无 vendored gitstatusd；p10k 将在联网时自动下载"
    return 0
  fi
  mkdir -p "$_gs_cache"
  if [ -x "$_gs_dst" ] && cmp -s "$_gs_src" "$_gs_dst"; then
    say "gitstatusd 已一致，跳过"
    return 0
  fi
  # 守护进程可能正被运行中的会话执行（直接 cp 覆盖会 Text file busy）：
  # 临时副本 + mv 原子替换；旧 inode 由存量进程继续使用，新会话拉起新文件。
  cp "$_gs_src" "$_gs_dst.new"
  chmod +x "$_gs_dst.new"
  mv -f "$_gs_dst.new" "$_gs_dst"
  say "gitstatusd v1.5.4 -> $_gs_cache"
}

deploy_zoxide() {
  _zx_dst="$GX_HOME/.local/bin/zoxide"
  _zx_src="$REPO_DIR/gx/bin/zoxide-linux-x86_64"
  # 判定看部署目标而非当前进程 PATH：--home 重定向时目标目录必须自足。
  if [ -x "$_zx_dst" ] && cmp -s "$_zx_src" "$_zx_dst"; then
    say "zoxide 已一致，跳过"
    return 0
  fi
  if [ ! -e "$_zx_dst" ] && [ "$GX_HOME" = "$HOME" ] && command -v zoxide >/dev/null 2>&1; then
    say "zoxide 已在系统 PATH，跳过"
    return 0
  fi
  if [ "$(uname -m)" != x86_64 ] || [ ! -x "$_zx_src" ]; then
    warn "架构 $(uname -m) 无 vendored zoxide；请手动安装或联网下载 $ZOXIDE_VERSION"
    return 0
  fi
  mkdir -p "$GX_HOME/.local/bin"
  # 与 gitstatusd 同理：运行中的二进制用临时副本 + mv 原子替换。
  cp "$_zx_src" "$_zx_dst.new"
  chmod +x "$_zx_dst.new"
  mv -f "$_zx_dst.new" "$_zx_dst"
  say "zoxide $ZOXIDE_VERSION -> $GX_HOME/.local/bin/zoxide"
}

deploy_fonts() {
  [ "$OPT_SKIP_FONTS" -eq 0 ] || { say "跳过字体部署 (--skip-fonts)"; return 0; }
  _ft_dst="$GX_HOME/.local/share/fonts/JetBrainsMonoNerd"
  mkdir -p "$_ft_dst"
  cp "$REPO_DIR"/gx/fonts/JetBrainsMonoNerd/*.ttf "$_ft_dst/"
  say "Nerd Font v3.4.0 (JetBrainsMono 4 字重) -> $_ft_dst"
  if ! command -v fc-cache >/dev/null 2>&1; then
    warn "无 fc-cache，字体已复制但缓存未刷新（安装 fontconfig 后手动执行 fc-cache -f）"
  elif [ "$GX_HOME" = "$HOME" ]; then
    fc-cache -f "$GX_HOME/.local/share/fonts" >/dev/null 2>&1 || warn "fc-cache 失败（不影响安装）"
  else
    # --home 重定向时 fontconfig 的 per-user 缓存也落在部署 HOME，不写真实 ~/.cache。
    XDG_CACHE_HOME="$GX_HOME/.cache" fc-cache -f "$GX_HOME/.local/share/fonts" >/dev/null 2>&1 \
      || warn "fc-cache 失败（不影响安装）"
  fi
}

deploy_wezterm() {
  [ "$OPT_SKIP_WEZTERM" -eq 0 ] || { say "跳过 WezTerm 配置 (--skip-wezterm)"; return 0; }
  _wt_dst="$GX_HOME/.config/wezterm"
  if [ -d "$_wt_dst/.git" ]; then
    # 目标配置由用户自己的 git 仓库管理（本机即如此）：保留现场，不快照替换。
    say "WezTerm 配置目录由 git 自管（含 .git），跳过部署"
    return 0
  fi
  replace_dir "$REPO_DIR/gx/wezterm" "$_wt_dst"
  say "WezTerm 配置 -> $_wt_dst"
  printf 'gx install.sh 部署的 wezterm 配置快照\n' > "$_wt_dst/.gx-managed"
}

set_login_shell() {
  [ "$OPT_SKIP_CHSH" -eq 0 ] || { say "跳过登录 shell 切换 (--skip-chsh)"; return 0; }
  [ "$GX_HOME" = "$HOME" ] || { say "非真实 HOME（--home 重定向），跳过 chsh"; return 0; }
  _sl_cur=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f7) || _sl_cur=""
  case "$_sl_cur" in
    */zsh) say "登录 shell 已是 zsh"; return 0 ;;
  esac
  _sl_zsh=$(command -v zsh) || { warn "未找到 zsh，跳过 chsh"; return 0; }
  if [ "$OPT_UNATTENDED" -eq 1 ]; then
    say "unattended 模式不执行 chsh；请手动执行: chsh -s $_sl_zsh"
    return 0
  fi
  printf '把登录 shell 切换为 zsh? [y/N] '
  read _sl_ans
  case "$_sl_ans" in
    y|Y) chsh -s "$_sl_zsh" || warn "chsh 失败，请手动执行: chsh -s $_sl_zsh" ;;
    *)   say "跳过 chsh（可稍后手动执行: chsh -s $_sl_zsh）" ;;
  esac
}

# 只清部署目标 HOME 内的补全缓存：omz 的 .zcompdump-<host>-<ver>{,.zwc} 与
# Ubuntu /etc/zsh/zshrc 全局 compinit 留下的无后缀 .zcompdump（glob 同时命中
# 两族），新配置首次启动时重建。
cleanup_zcompdump() {
  rm -f "$GX_HOME"/.zcompdump* 2>/dev/null || true
}

print_summary() {
  printf '\n部署完成:\n'
  printf '  Oh My Zsh (fork %s): %s\n' "$GX_BRANCH" "$ZSH"
  printf '  zsh 配置链: %s/.zshrc (+ .zshenv/.zshrc.local/.p10k.zsh)\n' "$GX_HOME"
  printf '  p10k 主题: %s/custom/themes/powerlevel10k\n' "$ZSH"
  [ "$OPT_SKIP_WEZTERM" -eq 0 ] && printf '  WezTerm 配置: %s/.config/wezterm\n' "$GX_HOME"
  printf '\n启动新会话生效: exec zsh\n'
  printf '回退: sh %s/gx/install.sh --uninstall（恢复 .pre-gx 备份）\n' "$ZSH"
}

# ---------------------------------------------------------------- 卸载

uninstall() {
  say "卸载 gx 部署（只恢复备份与移除带标记产物，不动其他数据）"
  if [ "$OPT_UNATTENDED" -eq 0 ]; then
    printf '继续? [y/N] '
    read _un_ans
    case "$_un_ans" in y|Y) ;; *) die "已取消" 1 ;; esac
  fi
  for _un_f in .zshrc .zshenv .zshrc.local .p10k.zsh; do
    _un_new=$(ls -t "$GX_HOME/$_un_f".pre-gx-* 2>/dev/null | head -n 1)
    if [ -n "$_un_new" ]; then
      [ -e "$GX_HOME/$_un_f" ] && mv "$GX_HOME/$_un_f" "$GX_HOME/$_un_f.gx-removed-$TS"
      mv "$_un_new" "$GX_HOME/$_un_f"
      say "已恢复: $_un_f <- $(basename "$_un_new")"
    else
      say "无备份，保留现状: $_un_f"
    fi
  done
  for _un_d in "$GX_HOME/.config/wezterm" "$ZSH/custom/themes/powerlevel10k"; do
    if [ -e "$_un_d" ] && is_ours "$_un_d"; then
      rm -rf "$_un_d"
      say "已移除（安装器管理）: $_un_d"
    fi
  done
  if [ -f "$ZSH/.gx-managed" ]; then
    say "保留 $ZSH（含 .gx-managed 标记）；如确认不再需要请手动删除"
  fi
  say "保留二进制与字体: ~/.local/bin/zoxide、~/.cache/gitstatus、~/.local/share/fonts"
}

# ---------------------------------------------------------------- 主流程

main() {
  say "gx 安装器 (home=$GX_HOME, zsh=$ZSH, remote=$GX_REMOTE, branch=$GX_BRANCH)"
  guard_zsh_location
  report_leftovers
  if [ "$OPT_UNINSTALL" -eq 1 ]; then
    uninstall
    return 0
  fi
  command -v zsh >/dev/null 2>&1 \
    || warn "未检测到 zsh（若 apt 步骤被跳过，请先安装 zsh 再运行）"
  acquire_repo
  install_apt_packages
  deploy_omz_repo
  deploy_configs
  deploy_p10k
  deploy_zoxide
  deploy_fonts
  deploy_wezterm
  set_login_shell
  cleanup_zcompdump
  print_summary
}

main
