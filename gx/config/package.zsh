# 包模式在 instant prompt 前隔离运行时目录；参数无效时返回 1，不回退到 HOME。
(( ${+GX_PACKAGE_ROOT} || ${+GX_PROFILE_DIR} )) || return 0

() {
  emulate -L zsh
  local root=${GX_PACKAGE_ROOT:-} profile=${GX_PROFILE_DIR:-} target
  if [[ $root != /* || $profile != /* || $root == *[$'\r\n']* || $profile == *[$'\r\n']* ]]; then
    print -u2 -- 'gx package: GX_PACKAGE_ROOT and GX_PROFILE_DIR must both be absolute paths'
    return 1
  fi
  root=${root:A}
  profile=${profile:A}
  if [[ ! -r "$root/oh-my-zsh.sh" || ! -d "$root/gx/omz-custom" || ! -r "$root/gx/config/p10k.zsh" ]]; then
    print -u2 -- 'gx package: GX_PACKAGE_ROOT is not a complete GX resource tree'
    return 1
  fi
  if [[ ! -d $profile || ! -w $profile || ! -x $profile || $profile == / || $profile == ${HOME:A} || \
        $profile == $root || $profile == "$root"/* || $root == "$profile"/* ]]; then
    print -u2 -- 'gx package: GX_PROFILE_DIR must be an independent writable directory, not HOME or the resource tree'
    return 1
  fi
  local dump="$profile/.zcompdump-${HOST%%.*}-$ZSH_VERSION"
  for target in "$profile/.cache" "$profile/.cache/oh-my-zsh/completions" \
                "$profile/.zsh_history" "$dump" "$dump.zwc" "$dump.lock"; do
    if [[ ${target:A} != "$profile"/* ]]; then
      print -u2 -- 'gx package: runtime paths must stay inside GX_PROFILE_DIR'
      return 1
    fi
  done
  local runtime=${GX_P10K_RUNTIME_DIR:-} runtime_id
  if (( ${+GX_P10K_RUNTIME_DIR} )); then
    if [[ $runtime != /* || $runtime == *[$'\r\n']* ]]; then
      print -u2 -- 'gx package: GX_P10K_RUNTIME_DIR must be an absolute profile theme cache path'
      return 1
    fi
    runtime=${runtime:A}
    runtime_id=${runtime:h:t}
    if [[ ${#runtime_id} != 64 || $runtime_id == *[^0-9a-fA-F]* || \
          $runtime != "$profile/.cache/themes/$runtime_id/powerlevel10k" ]]; then
      print -u2 -- 'gx package: GX_P10K_RUNTIME_DIR must be profile/.cache/themes/<64hex>/powerlevel10k'
      return 1
    fi
    for target in powerlevel10k.zsh-theme internal/p10k.zsh gitstatus/gitstatus.plugin.zsh; do
      target="$runtime/$target"
      if [[ ! -f $target || ! -r $target || ${target:A} != "$runtime"/* ]]; then
        print -u2 -- 'gx package: GX_P10K_RUNTIME_DIR is incomplete or escapes the theme cache'
        return 1
      fi
    done
  fi
  local package_bin=${GX_PACKAGE_BIN:-}
  local -a package_path
  if [[ $package_bin == /* && -d $package_bin && -x $package_bin ]]; then
    package_bin=${package_bin:A}
    if [[ $package_bin != *:* && $package_bin != *[$'\r\n']* ]]; then
      package_path+=("$package_bin")
    fi
  fi
  # herdr 的 Windows PTY 会重建 PATH；MSYS 的 OSTYPE 也可能是 cygwin。
  if [[ $OSTYPE == (cygwin|msys)* ]]; then
    for target in /usr/bin /ucrt64/bin; do
      [[ -d $target && -x $target ]] && package_path+=("$target")
    done
  fi
  typeset -gU path PATH
  path=("${package_path[@]}" "${path[@]}")
  export PATH
  # herdr 窗格、嵌套 gx-zsh 继承的环境经原生程序中转：MSYS 把路径改成 C:/…，FPATH 还混进
  # 「;」分隔的碎片，会让 compdump 反复重建。只留存在的绝对目录。
  local -a functions_path
  for target in $fpath; do
    [[ $target == /* && -d $target ]] && functions_path+=("$target")
  done
  fpath=("${functions_path[@]}")
  typeset -gU fpath
  # :A 会把盘符路径当相对路径拼到 $PWD 后；只有盘符/UNC 值才调用一次 cygpath，其余非绝对值忽略。
  local name
  local -i index
  local -a names values converted
  for name in ZSH_CUSTOM POWERLEVEL9K_INSTALLATION_DIR; do
    target=${(P)name:-}
    [[ -z $target || $target == /* ]] && continue
    if [[ $OSTYPE == (cygwin|msys)* && $target != *[$'\r\n']* && \
          ( $target == [A-Za-z]:[\\/]* || $target == [\\][\\]* ) ]]; then
      names+=($name)
      values+=("$target")
    else
      print -u2 -- "gx package: ignoring non-absolute $name"
      unset $name
    fi
  done
  if (( $#names )) && (( $+commands[cygpath] )); then
    converted=("${(@f)$(command cygpath -u -- "${values[@]}" 2>/dev/null)}")
  fi
  for (( index = 1; index <= $#names; ++index )); do
    name=$names[index]
    if (( $#converted == $#names )) && [[ $converted[index] == /* ]]; then
      typeset -g $name=$converted[index]
    else
      print -u2 -- "gx package: ignoring non-absolute $name"
      unset $name
    fi
  done
  local custom=${ZSH_CUSTOM:-$root/gx/omz-custom} theme_root= installation=${POWERLEVEL9K_INSTALLATION_DIR:-}
  for target in "$custom/powerlevel10k/powerlevel10k.zsh-theme" \
                "$custom/themes/powerlevel10k/powerlevel10k.zsh-theme" \
                "$root/themes/powerlevel10k/powerlevel10k.zsh-theme"; do
    if [[ -f $target ]]; then
      theme_root=${target:A:h}
      break
    fi
  done
  # p10k 往自己的根目录写 .zwc：主题或显式安装目录位于资源树内任何位置都只能从 profile 运行副本加载；
  # Windows 路径不区分大小写，先折叠再比较。
  local inside=${${installation:+${installation:A}}:-$theme_root} base=$root
  if [[ $OSTYPE == (cygwin|msys)* ]]; then
    inside=${(L)inside}
    base=${(L)base}
  fi
  if [[ -n $inside && ( $inside == "$base" || $inside == "$base"/* ) ]]; then
    if [[ -z $runtime ]]; then
      print -u2 -- 'gx package: vendored Powerlevel10k requires GX_P10K_RUNTIME_DIR from the launcher'
      return 1
    fi
    installation=$runtime
  fi
  # Windows 上每次 fork 约 50 ms：目录已存在时不再调用外部 mkdir。
  zmodload -F zsh/files b:zf_mkdir
  if [[ ! -d "$profile/.cache/oh-my-zsh/completions" ]] && \
     ! zf_mkdir -p -- "$profile/.cache/oh-my-zsh/completions"; then
    print -u2 -- 'gx package: cannot create the profile cache'
    return 1
  fi
  if [[ ! -w "$profile/.cache/oh-my-zsh" || ! -w "$profile/.cache/oh-my-zsh/completions" ]]; then
    print -u2 -- 'gx package: profile cache is not writable'
    return 1
  fi
  # 原生 zoxide 需要 Windows 路径；启动器已给出 _ZO_DATA_DIR 时原样使用，这里只是兜底。
  if [[ $OSTYPE == (cygwin|msys)* && -z ${_ZO_DATA_DIR:-} ]] && (( $+commands[zoxide] )); then
    local zoxide_data="$profile/.local/share/zoxide" zoxide_native
    zoxide_data=${zoxide_data:A}
    if [[ $zoxide_data != "$profile"/* ]]; then
      print -u2 -- 'gx package: zoxide data directory must stay inside GX_PROFILE_DIR'
      return 1
    fi
    if (( ! $+commands[cygpath] )); then
      print -u2 -- 'gx package: native zoxide requires cygpath for its profile data directory'
      return 1
    fi
    if ! zoxide_native=$(command cygpath -w -- "$zoxide_data") || \
       [[ $zoxide_native != [A-Za-z]:\\* && $zoxide_native != \\\\* ]]; then
      print -u2 -- 'gx package: cannot resolve the native zoxide data directory'
      return 1
    fi
    if [[ ! -d $zoxide_data ]] && ! zf_mkdir -p -- "$zoxide_data"; then
      print -u2 -- 'gx package: cannot create the zoxide data directory'
      return 1
    fi
    export _ZO_DATA_DIR=$zoxide_native
  fi
  # Windows 上没有登录 shell 设定 SHELL：由本 shell 派生的程序（fzf、编辑器的 :sh 等）应拿到正在
  # 运行的 zsh。Linux 保持登录环境的 SHELL（包内私有 zsh 不在 /etc/shells 里）。
  if [[ $OSTYPE == (cygwin|msys)* ]]; then
    target=/proc/$$/exe
    target=${target:A}
    [[ -x $target ]] || target=${commands[zsh]:-}
    [[ -z $target ]] || export SHELL=$target
  fi
  export GX_PACKAGE_ROOT=$root GX_PROFILE_DIR=$profile
  export ZSH=$root ZSH_CUSTOM=$custom
  export XDG_CACHE_HOME="$profile/.cache"
  export ZSH_CACHE_DIR="$profile/.cache/oh-my-zsh" ZSH_COMPDUMP=$dump
  export HISTFILE="$profile/.zsh_history" NVM_DIR="$profile/.nvm"
  export GITSTATUS_AUTO_INSTALL=0
  [[ -z $installation ]] || typeset -g POWERLEVEL9K_INSTALLATION_DIR=$installation
  typeset -g POWERLEVEL9K_CONFIG_FILE="$profile/.p10k.zsh"
}
