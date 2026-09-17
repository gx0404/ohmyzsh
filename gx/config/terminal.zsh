# Herdr / WezTerm 工作目录上报；不改 PS1、鼠标模式或已有 ZLE widget。
[[ -o interactive && -t 1 && $TERM != dumb ]] || return 0
[[ $TERM_PROGRAM == WezTerm || ${HERDR_ENV:-} == 1 ]] || return 0
(( $+functions[__wezterm_osc7] )) && return 0
[[ -z ${GX_TERMINAL_CWD_INSTALLED:-} ]] || return 0
typeset -g GX_TERMINAL_CWD_INSTALLED=1

_gx_terminal_report_cwd() {
  local exit_code=$?
  [[ ${_GX_TERMINAL_LAST_CWD:-} == $PWD ]] && return $exit_code
  local LC_ALL=C ch encoded='' hex
  local -i index
  for (( index=1; index<=${#PWD}; ++index )); do
    ch=$PWD[index]
    case $ch in
      [a-zA-Z0-9/._~-]) encoded+=$ch ;;
      *) printf -v hex '%%%02X' "'$ch"; encoded+=$hex ;;
    esac
  done
  builtin printf '\e]7;file://%s%s\e\\' "${HOST//[^a-zA-Z0-9.-]/}" "$encoded"
  typeset -g _GX_TERMINAL_LAST_CWD=$PWD
  return $exit_code
}
autoload -Uz add-zsh-hook
add-zsh-hook precmd _gx_terminal_report_cwd
