# Ghostty GX / herdr 工作目录上报与提示符光标复位；不改 PS1、鼠标模式或已有 ZLE widget。
# 守卫对 p10k instant prompt 免疫：instant prompt 在 zshrc 早期把 fd 1 重定向到临时
# 文件，此时 `-t 1` 恒假，故改以 $TTY（zsh 为有控制终端的 shell 记录的 tty 路径）
# 判定；无 pty（agent 以 zsh -ic 调用）时 $TTY 为空，模块与旧行为一致不安装。
# 副作用：fd 1 非终端但 $TTY 非空（如 `zsh -i > log`）时 OSC 7 仍写到 stdout——与
# instant prompt 的捕获回放顺序一致，捕获类测试需自行过滤 `\e]7;`。
[[ -o interactive && ( -t 1 || -n ${TTY:-} ) && $TERM != dumb ]] || return 0
# 远端会话（ssh / emacs）里的路径对本地终端没有意义：上游 lib/termsupport.zsh 在这些
# 环境下连函数都不定义（omz #11696），本模块同样不接管，避免 TERM_PROGRAM/HERDR_ENV
# 被 SendEnv/AcceptEnv 带进 ssh 后把远端 cwd 以 file://localhost/... 报成本地目录。
[[ -z ${SSH_CONNECTION:-}${SSH_CLIENT:-}${SSH_TTY:-}${INSIDE_EMACS:-} ]] || return 0
# Ghostty 导出的 TERM_PROGRAM 恰为小写 ghostty；herdr 窗格带 HERDR_ENV=1。
[[ $TERM_PROGRAM == ghostty || ${HERDR_ENV:-} == 1 ]] || return 0
autoload -Uz add-zsh-hook
# 上游 lib/termsupport.zsh 在 xterm* 终端下无条件挂 omz_termsupport_cwd（每提示符
# 2 次 fork、无缓存、带主机名）；由本模块或 Ghostty 自带集成上报 OSC 7 时把它摘掉，
# 避免同一提示符双发。必须放在下面两处早退之前：`source ~/.zshrc` 会让上游重新挂钩，
# 而此时本模块已安装或 Ghostty 集成已在位，不再往下走。
add-zsh-hook -d precmd omz_termsupport_cwd
# Ghostty 自带的 zsh 集成在 .zshenv 阶段加载（定义 _ghostty_state）后，OSC 7/133 与光标
# 形状由它负责，本模块不再叠加；zshrc 同样不再启用 p10k 的 OSC 133。
(( ${+_ghostty_state} )) && return 0
[[ -z ${GX_TERMINAL_CWD_INSTALLED:-} ]] || return 0
typeset -g GX_TERMINAL_CWD_INSTALLED=1

_gx_terminal_report_cwd() {
  local exit_code=$?
  [[ ${_GX_TERMINAL_LAST_CWD:-} == $PWD ]] && return $exit_code
  typeset -g _GX_TERMINAL_LAST_CWD=$PWD
  local LC_ALL=C ch encoded='' hex drive= dir=$PWD
  local -i index
  # MSYS/Cygwin 的盘符目录（/c/… 或 /cygdrive/c/…）报成 file://localhost/C:/…，终端与 herdr
  # 新开的标签/分屏才能沿用；运行时根下等非盘符目录对原生程序没有意义，不上报。
  if [[ $OSTYPE == (cygwin|msys)* ]]; then
    dir=${dir#/cygdrive}
    [[ $dir == /[a-zA-Z] || $dir == /[a-zA-Z]/* ]] || return $exit_code
    drive=/${(U)dir[2]}:
    dir=${dir[3,-1]:-/}
  fi
  for (( index=1; index<=${#dir}; ++index )); do
    ch=$dir[index]
    case $ch in
      [a-zA-Z0-9/._~-]) encoded+=$ch ;;
      *) printf -v hex '%%%02X' "'$ch"; encoded+=$hex ;;
    esac
  done
  # 主机名字段固定写 localhost（file://localhost/path）：Ghostty 拒收没有主机名的 OSC 7，
  # herdr 的 parse_file_uri_cwd 接受空主机与 localhost。不读 $HOST，也就不会因两边主机名
  # 写法不同（大小写、FQDN）被当成远端上报丢弃。
  builtin printf '\e]7;file://localhost%s\e\\' "$drive$encoded"
  return $exit_code
}
add-zsh-hook precmd _gx_terminal_report_cwd

# TUI（vim、herdr 等）用 DECSCUSR 改光标形状后若异常退出，形状会遗留给 shell；
# 每个提示符复位成终端默认（\e[0 q = DECSCUSR 0）。cwd 未变时 OSC 7 有缓存早退，
# 光标复位必须每提示符都发，所以是独立钩子；成本 = 一次 builtin printf，无 fork。
_gx_terminal_reset_cursor() { builtin printf '\e[0 q'; }
add-zsh-hook precmd _gx_terminal_reset_cursor
