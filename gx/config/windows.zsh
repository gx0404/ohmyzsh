[[ $OSTYPE == (cygwin|msys)* ]] || return 0
# Windows（MSYS/Cygwin）交互层：irm/iwr/iex 转交 PowerShell、缺失命令只给提示、补齐常用 shim。
# 只定义还没有被命令、函数或别名占用的名字；~/.zshrc.local 在本文件之后加载，仍可覆盖。

# PowerShell 安装器改的是注册表里的 PATH（REG_EXPAND_SZ 原文，%VAR% 由 _gx_windows_refresh_path 展开）。
typeset -ga _gx_registry_path_keys=(
  /proc/registry/HKEY_CURRENT_USER/Environment/Path
  '/proc/registry/HKEY_LOCAL_MACHINE/SYSTEM/CurrentControlSet/Control/Session Manager/Environment/Path'
)

# 选 PowerShell：GX_POWERSHELL（命令名或路径）优先，其次 pwsh.exe、powershell.exe；结果放在 REPLY。
_gx_powershell() {
  emulate -L zsh
  local exe=${GX_POWERSHELL:-}
  if [[ -z $exe ]]; then
    exe=${commands[pwsh.exe]:-${commands[powershell.exe]:-}}
  elif [[ $exe == [A-Za-z]:[\\/]* || $exe == [\\][\\]* ]]; then
    exe=$(command cygpath -u -- "$exe" 2>/dev/null)
  elif [[ $exe != */* ]]; then
    exe=${commands[$exe]:-}
  fi
  [[ -n $exe && -f $exe && -x $exe ]] || return 1
  REPLY=$exe
}

# PowerShell 单引号字面量放在 REPLY：' ‘ ’ ‚ ‛ 都会结束字符串，逐个写成两个。
_gx_pwsh_quote() {
  emulate -L zsh -o extendedglob
  REPLY="'${1//(#m)(\'|‘|’|‚|‛)/$MATCH$MATCH}'"
}

# 把参数（没有参数时读标准输入）原样写成带 UTF-8 BOM 的临时 .ps1，由外层 -Command 设好输出编码、
# 关掉进度条后调用它。脚本本身不加任何前置行：以 param()、[CmdletBinding()] 或 using 开头的安装脚本
# 必须从第一行开始；也不强制 $ErrorActionPreference，与 Invoke-Expression 一致。退出码与 -File 相同：
# 脚本 exit N 时为 N（$? 为假），正常结束为 0（不沿用脚本里早先原生命令留下的 $LASTEXITCODE），
# throw 为 1。不用 `-Command -` 读标准输入：那样不可靠，还会占用安装器提问需要的终端输入。
_gx_pwsh_run() {
  emulate -L zsh
  if ! _gx_powershell; then
    if [[ -n ${GX_POWERSHELL:-} ]]; then
      print -ru2 -- "gx-pwsh: GX_POWERSHELL 不是可执行的 PowerShell：$GX_POWERSHELL"
    else
      print -ru2 -- 'gx-pwsh: 找不到 PowerShell（pwsh.exe 或 powershell.exe），可用 GX_POWERSHELL 指定路径'
    fi
    return 127
  fi
  local exe=$REPLY script native body command input=/dev/null entry child_path
  # 私有运行时的 /usr/bin 等排到 PATH 最后：安装脚本里的 tar、find、sort、curl、cmd 应该是 Windows 自带的版本。
  local -a windows_first runtime_last
  for entry in $path; do
    case ${entry%/} in
      (/usr/bin|/bin|/usr/local/bin|/ucrt64/bin|/mingw64/bin|/clang64/bin|/opt/bin) runtime_last+=("$entry") ;;
      (*) windows_first+=("$entry") ;;
    esac
  done
  child_path=${(j.:.)windows_first}${runtime_last:+${windows_first:+:}${(j.:.)runtime_last}}
  script=$(command mktemp --suffix=.ps1 "${TMPDIR:-/tmp}/gx-pwsh.XXXXXX") || return 1
  zmodload -F zsh/files b:zf_rm
  trap 'return 130' INT
  {
    {
      print -rn -- $'\xef\xbb\xbf'
      if (( $# )); then
        print -r -- "$*"
      else
        command cat
      fi
    } >| $script || return 1
    body=$(<$script)
    if [[ ${body#$'\xef\xbb\xbf'} != *[^[:space:]]* ]]; then
      print -ru2 -- 'gx-pwsh: 没有收到要执行的 PowerShell 脚本（管道前面的命令可能失败了），未运行 PowerShell'
      return 1
    fi
    native=$(command cygpath -w -- "$script") || return 1
    _gx_pwsh_quote "$native"
    command="& { Remove-Item Env:MSYS2_ARG_CONV_EXCL -ErrorAction SilentlyContinue;"
    command+=" [Console]::OutputEncoding = \$OutputEncoding = [Text.UTF8Encoding]::new(\$false);"
    command+=" \$ProgressPreference = 'SilentlyContinue'; & $REPLY;"
    command+=" if (\$?) { exit 0 }; if (\$LASTEXITCODE) { exit \$LASTEXITCODE }; exit 1 }"
    if (( $# )); then
      PATH=$child_path MSYS2_ARG_CONV_EXCL='*' "$exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$command"
    else
      [[ -n ${TTY:-} ]] && { : < /dev/tty } 2>/dev/null && input=/dev/tty
      PATH=$child_path MSYS2_ARG_CONV_EXCL='*' "$exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$command" < $input
    fi
  } always {
    zf_rm -f -- "$script"
  }
}

# 安装器装完只改了注册表 PATH 或用户 bin 目录：把新出现的目录追加到 $path 并 rehash，不必重开终端。
_gx_windows_refresh_path() {
  emulate -L zsh -o extendedglob
  (( $+functions[_gx_add_user_bins] )) && _gx_add_user_bins
  local key value entry expanded name
  local -a windows posix names
  local -A seen
  for key in $_gx_registry_path_keys; do
    [[ -r $key ]] || continue
    value=$(<$key)
    for entry in ${(s:;:)${value//$'\0'/}}; do
      # 与 ExpandEnvironmentStrings 一样只展开一遍；变量名不区分大小写，展开不了的条目跳过。
      expanded=
      while [[ $entry == (#b)([^%]#)%([^%]##)%(*) ]]; do
        names=(${parameters[(I)(#i)${(b)match[2]}]})
        for name in $names; do
          [[ ${parameters[$name]} == scalar*export* ]] && break
          name=
        done
        if [[ -z $name ]]; then
          entry= expanded=
          break
        fi
        expanded+=$match[1]${(P)name}
        entry=$match[3]
      done
      [[ -n $entry || -n $expanded ]] || continue
      entry=$expanded$entry
      [[ $entry == ([A-Za-z]:[\\/]*|[\\][\\]*) ]] && windows+=("$entry")
    done
  done
  if (( $#windows )); then
    posix=("${(@f)$(command cygpath -u -- "${windows[@]}" 2>/dev/null)}")
    if (( $#posix == $#windows )); then
      for entry in $path; do
        seen[${(L)entry%/}/]=1
      done
      # 先查已有集合再 stat：不可达的 UNC 条目不在每次 gx-pwsh 后都等超时。
      for entry in $posix; do
        [[ $entry == /* && -z ${seen[${(L)entry%/}/]} && -d $entry ]] || continue
        seen[${(L)entry%/}/]=1
        path+=("$entry")
      done
    fi
  fi
  rehash
}

gx-pwsh() {
  _gx_pwsh_run "$@"
  local rc=$?
  _gx_windows_refresh_path
  return $rc
}

# irm/iwr 拼成一条 PowerShell 命令：只有 -Name 形式的参数名原样传，其余参数一律作单引号字面量，
# URL 里的 & ? 与 -x;… 这类参数都不会被解释。iwr 没写 -UseBasicParsing（可简写为 -useb）时补上：
# Windows PowerShell 5.1 不带它会用 IE 引擎解析页面，没有 IE 的系统上会报错或卡住；PowerShell 6+
# 忽略这个参数。输出进管道时 iwr 只写正文，`iwr … | iex` 与在 PowerShell 里一样可用。请求失败只是
# 语句级错误、脚本照常结束，所以追加一行让它返回 1。
_gx_pwsh_invoke() {
  emulate -L zsh -o extendedglob
  local line=$1 arg basic=
  shift
  for arg in "$@"; do
    if [[ $arg == -[A-Za-z][A-Za-z0-9]# ]]; then
      line+=" $arg"
      [[ $arg == (#i)-useb* ]] && basic=1
    else
      _gx_pwsh_quote "$arg"
      line+=" $REPLY"
    fi
  done
  if [[ $line == Invoke-WebRequest* ]]; then
    [[ -n $basic ]] || line+=" -UseBasicParsing"
    [[ -t 1 ]] || line="($line).Content"
  fi
  _gx_pwsh_run "$line"$'\n''if (-not $?) { exit 1 }'
}

_gx_windows_free() {
  (( ! $+commands[$1] && ! $+functions[$1] && ! $+aliases[$1] && ! $+builtins[$1] ))
}

_gx_windows_free iex && iex() { gx-pwsh "$@" }
_gx_windows_free Invoke-Expression && Invoke-Expression() { gx-pwsh "$@" }
_gx_windows_free irm && irm() { _gx_pwsh_invoke Invoke-RestMethod "$@" }
_gx_windows_free Invoke-RestMethod && Invoke-RestMethod() { _gx_pwsh_invoke Invoke-RestMethod "$@" }
_gx_windows_free iwr && iwr() { _gx_pwsh_invoke Invoke-WebRequest "$@" }
_gx_windows_free Invoke-WebRequest && Invoke-WebRequest() { _gx_pwsh_invoke Invoke-WebRequest "$@" }

# 只提示、从不执行：PowerShell 的 Verb-Noun 命令提示改用 gx-pwsh，常见 Linux 工具给出 winget 包名。
if (( ! $+functions[command_not_found_handler] )); then
  command_not_found_handler() {
    emulate -L zsh -o extendedglob
    local id line arg
    print -ru2 -- "zsh: command not found: $1"
    if [[ $1 == [A-Z][A-Za-z]##-[A-Z][[:alnum:]]# ]]; then
      # 逐个参数按 PowerShell 规则加引号，含空格或特殊字符的参数在提示里仍是一个参数。
      line=$1
      for arg in "${@[2,-1]}"; do
        if [[ $arg == [A-Za-z0-9_./\\:=+~*?%-]## ]]; then
          line+=" $arg"
        elif [[ $arg != *[\$\`\"“”„‟]* ]]; then
          line+=" \"$arg\""
        else
          _gx_pwsh_quote "$arg"
          line+=" $REPLY"
        fi
      done
      print -ru2 -- "$1 是 PowerShell 命令，可以这样运行：gx-pwsh ${(qq)line}"
      return 127
    fi
    case $1 in
      rg) id=BurntSushi.ripgrep.MSVC ;;
      fd) id=sharkdp.fd ;;
      bat) id=sharkdp.bat ;;
      yq) id=MikeFarah.yq ;;
      delta) id=dandavison.delta ;;
      gh) id=GitHub.cli ;;
      lazygit) id=JesseDuffield.lazygit ;;
      nvim) id=Neovim.Neovim ;;
      node|npm|npx) id=OpenJS.NodeJS.LTS ;;
      go) id=GoLang.Go ;;
      cargo|rustc|rustup) id=Rustlang.Rustup ;;
      make) id=ezwinports.make ;;
      7z) id=7zip.7zip ;;
      htop|btop) id=aristocratos.btop4win ;;
      man)
        print -ru2 -- "Windows 版没有附带 man，可以改用：${2:-<命令>} --help"
        return 127
        ;;
      tmux|screen)
        print -ru2 -- "Windows 上没有 $1；终端复用可以用随 GX Shell 安装的 herdr"
        return 127
        ;;
    esac
    [[ -z $id ]] || print -ru2 -- "可用 winget 安装：winget install --id $id -e（装好后在新标签页里使用）"
    return 127
  }
fi

# 运行时缺 unzip 时用自带的 bsdunzip（extract 插件对 .zip 调用 unzip）；MSYS2 的 vim 包不带 vi；
# open/xdg-open 走 OMZ 的 open_command。
_gx_windows_free unzip && (( $+commands[bsdunzip] )) && unzip() { command bsdunzip "$@" }
_gx_windows_free vi && (( $+commands[vim] )) && vi() { command vim "$@" }
_gx_windows_free open && open() { open_command "$@" }
_gx_windows_free xdg-open && xdg-open() { open_command "$@" }
_gx_windows_free pbcopy && pbcopy() { command cat > /dev/clipboard }
_gx_windows_free pbpaste && pbpaste() { command cat /dev/clipboard }
unset -f _gx_windows_free

# 原生 zoxide 生成的钩子每次 cd 都同步跑 `zoxide add -- "$(__zoxide_pwd)"`：子 shell、cygpath 与
# zoxide 三个进程。盘符目录（/c/… 或 /cygdrive/c/…）改用纯 zsh 换算 Windows 路径，其余目录仍交给
# 原函数；记录放到后台，cd 不再等 zoxide。z/zi 的查询与跳转逻辑不变。
if (( $+functions[__zoxide_pwd] && $+functions[__zoxide_hook] )) && [[ $functions[__zoxide_pwd] == *cygpath* ]]; then
  functions[_gx_zoxide_pwd]=$functions[__zoxide_pwd]
  _gx_windows_pwd() {
    local dir=${PWD:P}
    dir=${dir#/cygdrive}
    [[ $dir == /[a-zA-Z] || $dir == /[a-zA-Z]/* ]] || return 1
    REPLY=${(U)dir[2]}:${${dir[3,-1]:-/}//\//\\}
  }
  __zoxide_pwd() {
    local REPLY
    if _gx_windows_pwd; then
      \builtin print -r -- "$REPLY"
    else
      _gx_zoxide_pwd "$@"
    fi
  }
  __zoxide_hook() {
    local REPLY
    _gx_windows_pwd || REPLY=$(_gx_zoxide_pwd) || return
    \command zoxide add -- "$REPLY" &!
  }
fi
