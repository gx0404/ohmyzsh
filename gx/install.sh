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
# 环境变量: GX_KEEP_BACKUPS=<N|all>  每个路径除「第一代」外再保留最新 N 份
#                   .pre-gx-<ts> 备份（默认 2，须 ≥1；all = 永不回收）。时间戳
#                   最小的那份是 gx 之前用户自己的配置，永久保留、从不回收；
#                   --uninstall 恢复最新一份后其余只留 N-1 份（第一代照旧保留）。
#                   例外：$ZSH 整树因体积固定只留「第一代 + 1 份」，不受本变量影响；
#                   $ZSH/custom/ 下的 p10k 备份属用户运行时层，一律不回收。
# 退出码: 0 成功；1 前置检查失败；2 部署失败。
#
# 安全约定: 绝不 rm 用户既有文件——一律 mv 为 *.pre-gx-<时间戳> 备份；
# 仅允许删除带 .gx-managed 标记（本安装器前次部署）的目录，以及本安装器自己打的
# .pre-gx-<14 位时间戳> 备份中超出 GX_KEEP_BACKUPS 的中间世代（时间戳最小的第一代
# 永久保留，它是唯一不可再生的 gx 前原件）；重装时新快照先在 $ZSH 同级完整就位并
# 合并 $ZSH/custom（用户运行时层，同名以用户为准、符号链接原样保留），再两次
# rename 原子替换——任何失败都发生在旧安装原样在位时。
# 补全缓存：本次部署的快照指纹与上次记录（$ZSH/.gx-managed 的 snapshot: 行）一致时
# 保留当前主机/版本的 dump 一族，否则连同其他主机/版本的 dump 一并清掉、下次启动重建；
# 无后缀 .zcompdump（Ubuntu 全局 compinit 产物）始终清除。
# 不落任何凭据。

set -eu

GX_REMOTE_DEFAULT="https://github.com/gx0404/ohmyzsh.git"
GX_BRANCH_DEFAULT="feature/gx_ohmyzsh"
ZOXIDE_VERSION="0.9.9"
APT_PKGS="zsh git fzf zsh-autosuggestions zsh-syntax-highlighting"
# 部署 $ZSH 时排除的开发态目录（git 仓库与运行时产物不入安装目标）。.build/ 是项目内
# 构建根（工具链、构建输出与测试临时数据）：带进快照会把构建产物部署进 $ZSH，快照
# 指纹也会随测试临时目录漂移。
REPO_EXCLUDES="--exclude=./.git
--exclude=./.build
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
GX_KEEP_BACKUPS="${GX_KEEP_BACKUPS:-2}"
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
# 本次部署的源快照指纹，与上次部署记在 $ZSH/.gx-managed 的 snapshot: 行比对。
# 不一致（或无记录）即认为补全集合可能变了，cleanup_zcompdump 连当前 dump 一起清。
SNAPSHOT_FP=""
SNAPSHOT_CHANGED=1

say()  { printf '==> %s\n' "$*"; }
warn() { printf '警告: %s\n' "$*" >&2; }
die()  { printf '错误: %s\n' "$1" >&2; exit "${2:-1}"; }

# 打印头部注释块作为帮助。范围末行必须跟随头部注释的最后一行（当前「不落任何凭据。」）：
# 多打一行就会把空行与 `set -eu` 也输出到 --help 里。
usage() { sed -n '2,42p' "$0" 2>/dev/null || cat <<'EOF'
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
# 安装路径的保留份数必须是 ≥1 的整数：0 会把本次刚打的备份一并删掉，回不去本次重装前
# 的状态。all 关闭回收。（卸载路径传 N-1，0 在那里是安全的：最新一份已被恢复回原位，
# 且时间戳最小的第一代由 prune_backups 永久保留。）
case "$GX_KEEP_BACKUPS" in
  all) ;;
  ''|*[!0-9]*|0) die "GX_KEEP_BACKUPS 须为 ≥1 的整数或 all，当前: '$GX_KEEP_BACKUPS'" 1 ;;
esac

# ---------------------------------------------------------------- 通用助手

# 目录由本安装器管理当且仅当含 .gx-managed 标记。
is_ours() { [ -f "$1/.gx-managed" ]; }

# 读 <dir>/.gx-managed 里的快照指纹；旧版部署没有该行，输出空串（= 视为快照已变）。
read_snapshot_fp() { sed -n 's/^snapshot: //p' "$1/.gx-managed" 2>/dev/null | head -n 1; }

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

guard_destination() {
  if [ -e "$1" ] || [ -L "$1" ]; then
    die "时间戳目标已存在，拒绝覆盖（请稍后重试；既有内容保留）: $1" 2
  fi
}

# 秒级时间戳不保证唯一；在部署前拒绝碰撞，移动时再检查，不回收或复用占用项。
guard_timestamp_paths() {
  [ "${#TS}" -eq 14 ] || die "无效的备份时间戳: $TS" 1
  case "$TS" in *[!0-9]*) die "无效的备份时间戳: $TS" 1 ;; esac
  if [ "$OPT_UNINSTALL" -eq 1 ]; then
    for _ts_file in .zshrc .zshenv .zshrc.local .p10k.zsh; do
      guard_destination "$GX_HOME/$_ts_file.gx-removed-$TS"
    done
  else
    for _ts_path in "$ZSH" "$GX_HOME/.zshrc" "$GX_HOME/.zshenv" "$GX_HOME/.p10k.zsh" \
                    "$ZSH/custom/themes/powerlevel10k" "$GX_HOME/.config/wezterm"; do
      guard_destination "$_ts_path.pre-gx-$TS"
    done
    guard_destination "$ZSH.gx-new-$TS"
    guard_destination "$ZSH.gx-old-$TS"
  fi
}

# 备份既有路径（文件或目录）；同批次内已备份过则跳过。
did_backup() {
  case " $BACKED_UP " in *" $1 "*) return 1 ;; esac
  guard_destination "$1.pre-gx-$TS"
  mv "$1" "$1.pre-gx-$TS" || return 1
  BACKED_UP="$BACKED_UP $1 "
}

# 列出 <path>.pre-gx-<14 位时间戳> 备份，按时间戳升序（最后一行最新）。只认本安装器
# 的后缀形态，用户手工改名的 *.pre-gx-old 之类一律不在其列。用法: list_backups <path>
list_backups() {
  for _lb_p in "$1".pre-gx-*; do
    [ -e "$_lb_p" ] || [ -L "$_lb_p" ] || continue
    case "${_lb_p##*.pre-gx-}" in
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) printf '%s\n' "$_lb_p" ;;
    esac
  done | sort
}

# 回收 <path> 的旧备份：时间戳最小的「第一代」永久保留，其余只留最新 <keep> 份
# （此前每次「改过配置再重装」都 +1 且永不回收；真实 HOME 曾累积 6 份）。
# 第一代是唯一一份「gx 之前用户自己的配置」——后面每一份都是 gx 部署出去的文件被用户
# 改过之后的派生物，可以再生；把它删掉等于永久销毁「回到 gx 之前」的能力（--uninstall
# 只恢复最新一份），所以它不在回收对象里。<keep> 为 all 时整条回收关闭。
# 删除对象仅限 list_backups 认定的本安装器产物。用法: prune_backups <path> <keep>
prune_backups() {
  [ "$2" != all ] || return 0
  _pb_list=$(list_backups "$1")
  [ -n "$_pb_list" ] || return 0
  # 去掉首行（第一代）后再算超额份数：实际留存 = 第一代 + 最新 <keep> 份。
  _pb_rest=$(printf '%s\n' "$_pb_list" | tail -n +2)
  [ -n "$_pb_rest" ] || return 0
  _pb_drop=$(( $(printf '%s\n' "$_pb_rest" | wc -l) - $2 ))
  [ "$_pb_drop" -gt 0 ] || return 0
  printf '%s\n' "$_pb_rest" | head -n "$_pb_drop" | while IFS= read -r _pb_old; do
    say "回收旧备份（第一代 + 最近 $2 份之外）: $_pb_old"
    rm -rf "$_pb_old" || warn "回收失败（保留原样）: $_pb_old"
  done
  # 回收是尽力而为的清理：失败不该让已完成的部署以 set -e 中止。
  return 0
}

# 替换部署目标目录：外来内容先备份，本安装器旧部署直接覆盖。
# 用法: replace_dir <src> <dst> <keep>（src 为快照源，dst 不含末尾斜杠；
# keep 为 prune_backups 的保留份数，keep=all 表示该路径不回收——$ZSH/custom/ 下的目标
# 属用户运行时层，备份一律不动）
replace_dir() {
  _rd_src="$1"; _rd_dst="$2"; _rd_keep="$3"
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
  prune_backups "$_rd_dst" "$_rd_keep"
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
  guard_destination "$_oz_new"
  guard_destination "$_oz_old"
  mkdir -p "$(dirname "$ZSH")" || die "无法创建安装目录的上级（检查权限）: $ZSH" 2
  mkdir "$_oz_new" || die "无法独占创建中转目录 $_oz_new（检查权限或并发安装）" 2
  # tar 中转（而非 cp -a）以应用 REPO_EXCLUDES，且失败可见、目标恒为干净快照。
  _oz_tar=$(mktemp "${TMPDIR:-/tmp}/gx-omz.XXXXXX.tar")
  if tar -cf "$_oz_tar" -C "$REPO_DIR" $REPO_EXCLUDES . 2>/dev/null \
      && tar -xf "$_oz_tar" -C "$_oz_new"; then
    # 指纹取中转 tar 的 CRC+字节数：同一份未改动的工作树逐字节相同 → 指纹相同；
    # 任何被部署文件的内容/元数据变化都会改指纹（保守方向：宁可多重建一次 dump）。
    SNAPSHOT_FP="cksum-$(cksum < "$_oz_tar" | awk '{print $1 "-" $2}')"
    rm -f "$_oz_tar"
  else
    rm -f "$_oz_tar"
    rm -rf "$_oz_new"
    die "打包/解包仓库快照失败，既有安装未改动" 2
  fi
  printf 'gx install.sh 管理的 Oh My Zsh 工作树（%s）\nsnapshot: %s\n' "$TS" "$SNAPSHOT_FP" \
    > "$_oz_new/.gx-managed"

  if [ -e "$ZSH" ] || [ -L "$ZSH" ]; then
    if is_ours "$ZSH"; then
      say "更新既有 gx 安装: $ZSH"
      # 与上次部署同一快照才敢保留补全缓存：omz 自己的自检只覆盖 fpath 目录集
      # （#omz fpath:）与 compinit 的「补全文件总数 + zsh 版本」，已存在补全文件的
      # 内容/#compdef 标签变化它看不见（#omz revision: 在无 .git 的快照部署下恒为空）。
      if [ "$(read_snapshot_fp "$ZSH")" = "$SNAPSHOT_FP" ]; then
        SNAPSHOT_CHANGED=0
      else
        say "源快照指纹与上次部署不同：补全缓存将清除并在下次启动重建"
      fi
      merge_custom_layer "$ZSH" "$_oz_new"
      # 两次 rename 之间屏蔽中断：旧树让位到 .gx-old-<ts>，新树随即就位；第二步
      # 失败则把旧树放回原位。
      guard_destination "$_oz_old"
      trap '' INT TERM HUP
      mv "$ZSH" "$_oz_old" || die "旧安装让位失败: $ZSH，新快照保留在 $_oz_new" 2
      mv "$_oz_new" "$ZSH" || { mv "$_oz_old" "$ZSH"; die "新快照就位失败，已放回旧安装" 2; }
      trap - INT TERM HUP
      rm -rf "$_oz_old"
    else
      say "检测到既有 Oh My Zsh（官方或其他来源），备份迁移"
      did_backup "$ZSH" || die "备份失败: $ZSH，新快照保留在 $_oz_new" 2
      # 整棵 omz 树体积大：除第一代（用户原装的那棵）外只保留最近 1 份，份数固定、
      # 不受 GX_KEEP_BACKUPS 影响（all 例外——那是用户明确要求不回收）。
      if [ "$GX_KEEP_BACKUPS" = all ]; then
        prune_backups "$ZSH" all
      else
        prune_backups "$ZSH" 1
      fi
      mv "$_oz_new" "$ZSH" || die "新快照就位失败，备份在 $ZSH.pre-gx-$TS" 2
    fi
  else
    mv "$_oz_new" "$ZSH" || die "新快照就位失败: $ZSH" 2
  fi
  [ "$CUSTOM_MERGED" -eq 0 ] || say "已回填 custom 层: $ZSH/custom"
}

deploy_configs() {
  # 机器差异层 .zshrc.local 不在部署对里（CUDA/SDK 等路径属单机所有，换机不带走）；
  # 目标机已存在的同名文件原样保留、不再备份覆盖，缺失时 zshrc 的存在性守卫静默跳过。
  _dc_pairs="zshrc:.zshrc zshenv:.zshenv p10k.zsh:.p10k.zsh"
  # 历史遗留：wezterm 安装器曾向 ~/.zshrc 追加「# >>> wezterm-gx >>>」cursor-mode
  # 键位块，其内容已并入 gx/config/zshrc（~/.zshrc 归 gx 层真源）。下面对 .zshrc 的
  # 「备份 + 整体替换」会把该块一并剥离，原样留在 .pre-gx-<ts> 备份里可回查；
  # 这里负责检测与告知。已一致而跳过时 .zshrc 必无该块（仓库版不含标记）。
  if [ -f "$GX_HOME/.zshrc" ] && grep -q '^# >>> wezterm-gx >>>' "$GX_HOME/.zshrc" 2>/dev/null; then
    say "检测到历史 wezterm-gx 键位块：随 .zshrc 整体替换剥离（内容已并入 gx zshrc，原块留在备份）"
  fi
  for _dc_pair in $_dc_pairs; do
    _dc_src="$REPO_DIR/gx/config/${_dc_pair%%:*}"
    _dc_dst="$GX_HOME/${_dc_pair##*:}"
    if [ -e "$_dc_dst" ] && cmp -s "$_dc_src" "$_dc_dst"; then
      say "已一致，跳过: $_dc_dst"
    else
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
    fi
    # 无论本次是否新打备份都回收：早期版本留下的多份也借此收敛到保留额度。
    prune_backups "$_dc_dst" "$GX_KEEP_BACKUPS"
  done
}

deploy_p10k() {
  _p1_src="$REPO_DIR/gx/omz-custom/themes/powerlevel10k"
  _p1_dst="$ZSH/custom/themes/powerlevel10k"
  # 目标在 $ZSH/custom/（用户运行时层）下：用户自装过 p10k 时首次部署会备份成
  # powerlevel10k.pre-gx-<ts>，这份属于用户数据，不进回收范围（keep=all）。
  replace_dir "$_p1_src" "$_p1_dst" all
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
  replace_dir "$REPO_DIR/gx/wezterm" "$_wt_dst" "$GX_KEEP_BACKUPS"
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

# 补全缓存清理。始终清掉 Ubuntu /etc/zsh/zshrc 全局 compinit 留下的无后缀 .zcompdump 与
# 其他主机名/zsh 版本的 .zcompdump-<host>-<ver>{,.zwc,.lock}。当前主机/版本的一族只在
# 「本次源快照指纹与上次部署相同」时保留：无差别清除让每次重装的首启多付 119 ms
# （冷缓存 332 ms），而未改动的重装前 dump 实测仍完全有效。指纹不同就照旧全清——omz
# 自己的失效判据只有 #omz fpath:（fpath 目录集）与 compinit 的「补全文件总数 + zsh
# 版本」，已存在补全文件的内容/#compdef 标签变化它检不出（#omz revision: 在本安装器
# 的无 .git 快照部署下恒为空，不参与判定）。
# 当前一族的名字按 oh-my-zsh.sh 的口径由 zsh 自己算；算不出（无 zsh）时退回全清。
cleanup_zcompdump() {
  rm -f "$GX_HOME/.zcompdump" 2>/dev/null || true
  _cz_keep=""
  if [ "$SNAPSHOT_CHANGED" -eq 0 ] && command -v zsh >/dev/null 2>&1; then
    _cz_keep=$(zsh -fc 'h=${HOST/.*/}; [[ $OSTYPE == darwin* ]] && h=$(scutil --get LocalHostName 2>/dev/null || print -r -- "$h"); print -r -- ".zcompdump-$h-$ZSH_VERSION"' 2>/dev/null) || _cz_keep=""
  fi
  for _cz_f in "$GX_HOME"/.zcompdump-*; do
    [ -e "$_cz_f" ] || [ -L "$_cz_f" ] || continue
    if [ -n "$_cz_keep" ]; then
      # 当前一族（dump、其 .zwc 与可能正被活动会话持有的 .lock）跳过；名字算不出或
      # 快照变了时 _cz_keep 为空，全部落到下面清掉。
      case "${_cz_f##*/}" in
        "$_cz_keep"|"$_cz_keep.zwc"|"$_cz_keep.lock") continue ;;
      esac
    fi
    say "清理失效补全缓存: ${_cz_f##*/}"
    # 这个 glob 会命中 omz 的 zrecompile 互斥锁**目录**（oh-my-zsh.sh 用
    # command mkdir "${ZSH_COMPDUMP}.lock" 创建，异常退出即残留，并让 omz 再也不重编
    # dump）：rm -rf 兼容文件与目录，且失败只告警——一次清理不该把已完成的部署以
    # set -e 中止（旧实现是 rm -f … || true，本函数必须同样容错）。
    rm -rf "$_cz_f" || warn "清理失效补全缓存失败（保留原样）: $_cz_f"
  done
  if [ -n "$_cz_keep" ]; then
    say "保留补全缓存: $_cz_keep{,.zwc,.lock}（如存在；源快照未变）"
  else
    say "已清全部 .zcompdump-*（源快照变化或无法判定当前 dump 名），下次启动重建"
  fi
}

print_summary() {
  printf '\n部署完成:\n'
  printf '  Oh My Zsh (fork %s): %s\n' "$GX_BRANCH" "$ZSH"
  printf '  zsh 配置链: %s/.zshrc (+ .zshenv/.p10k.zsh)\n' "$GX_HOME"
  printf '  机器差异层 .zshrc.local 不在部署对：已存在的保留原样，缺失由 zshrc 守卫跳过\n'
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
    # 最新 = 时间戳后缀最大（与 prune_backups 同一口径，不依赖被 mv 保留的旧 mtime）。
    _un_new=$(list_backups "$GX_HOME/$_un_f" | tail -n 1)
    if [ -n "$_un_new" ]; then
      if [ -e "$GX_HOME/$_un_f" ] || [ -L "$GX_HOME/$_un_f" ]; then
        guard_destination "$GX_HOME/$_un_f.gx-removed-$TS"
        mv "$GX_HOME/$_un_f" "$GX_HOME/$_un_f.gx-removed-$TS"
      fi
      mv "$_un_new" "$GX_HOME/$_un_f"
      say "已恢复: $_un_f <- $(basename "$_un_new")"
      # 恢复的那份算作最新一代，其余（第一代之外）只留 N-1 份，卸载完不留一堆。
      # N=1 时实参为 0，在这里是安全的：最新一份已经回到原位，第一代由 prune_backups
      # 永久保留——安装路径拒绝 0 的理由（会把本次刚打的备份也删掉）在卸载路径不成立。
      if [ "$GX_KEEP_BACKUPS" = all ]; then
        _un_keep=all
      else
        _un_keep=$((GX_KEEP_BACKUPS - 1))
      fi
      prune_backups "$GX_HOME/$_un_f" "$_un_keep"
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
  guard_timestamp_paths
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
