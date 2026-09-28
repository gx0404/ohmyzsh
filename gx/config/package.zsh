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
  local custom=${ZSH_CUSTOM:-$root/gx/omz-custom}
  local vendored="$root/gx/omz-custom/themes/powerlevel10k" theme_root= installation=${POWERLEVEL9K_INSTALLATION_DIR:-}
  vendored=${vendored:A}
  for target in "$custom/powerlevel10k/powerlevel10k.zsh-theme" \
                "$custom/themes/powerlevel10k/powerlevel10k.zsh-theme" \
                "$root/themes/powerlevel10k/powerlevel10k.zsh-theme"; do
    if [[ -f $target ]]; then
      theme_root=${target:A:h}
      break
    fi
  done
  if [[ ( -z $installation && $theme_root == "$vendored" ) || \
        ( -n $installation && ${installation:A} == "$vendored" ) ]]; then
    if [[ -z $runtime ]]; then
      print -u2 -- 'gx package: vendored Powerlevel10k requires GX_P10K_RUNTIME_DIR from the launcher'
      return 1
    fi
    installation=$runtime
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
  if ! command mkdir -p -- "$profile/.cache/oh-my-zsh/completions"; then
    print -u2 -- 'gx package: cannot create the profile cache'
    return 1
  fi
  if [[ ! -w "$profile/.cache/oh-my-zsh" || ! -w "$profile/.cache/oh-my-zsh/completions" ]]; then
    print -u2 -- 'gx package: profile cache is not writable'
    return 1
  fi
  if [[ $OSTYPE == (cygwin|msys)* && -z ${_ZO_DATA_DIR:-} ]] && (( $+commands[zoxide] )) && \
     [[ $(command uname -s) == MSYS_NT-* ]]; then
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
    if ! command mkdir -p -- "$zoxide_data"; then
      print -u2 -- 'gx package: cannot create the zoxide data directory'
      return 1
    fi
    export _ZO_DATA_DIR=$zoxide_native
  fi
  export GX_PACKAGE_ROOT=$root GX_PROFILE_DIR=$profile
  export ZSH=$root ZSH_CUSTOM=${ZSH_CUSTOM:-$root/gx/omz-custom}
  export XDG_CACHE_HOME="$profile/.cache"
  export ZSH_CACHE_DIR="$profile/.cache/oh-my-zsh" ZSH_COMPDUMP=$dump
  export HISTFILE="$profile/.zsh_history" NVM_DIR="$profile/.nvm"
  export GITSTATUS_AUTO_INSTALL=0
  [[ -z $installation ]] || typeset -g POWERLEVEL9K_INSTALLATION_DIR=$installation
  typeset -g POWERLEVEL9K_CONFIG_FILE="$profile/.p10k.zsh"
}
