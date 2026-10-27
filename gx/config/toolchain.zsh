# Keep user runtimes outside the GX profile; never install or fetch on startup.
[[ -o interactive ]] || return 0

() {
  emulate -L zsh
  local dir node version binary pnpm_home
  if [[ $OSTYPE != (cygwin|msys)* ]]; then
    # An explicitly set value (including empty or incomplete) is authoritative.
    if (( ! ${+NVM_DIR} )); then
      for dir in "$HOME/.nvm" "${XDG_CONFIG_HOME:-$HOME/.config}/nvm"; do
        if [[ -f $dir/nvm.sh && -r $dir/nvm.sh ]]; then
          export NVM_DIR=$dir
          break
        fi
      done
    fi
    if [[ -n ${NVM_DIR:-} && -f $NVM_DIR/nvm.sh && -r $NVM_DIR/nvm.sh ]] &&
       (( ! $+functions[nvm] && ! $+aliases[nvm] && ! $+commands[nvm] )); then
      node=${commands[node]:-}
      if [[ -z $node || $node == (/usr/bin/node|/bin/node) ]] &&
         (( ! $+functions[node] && ! $+aliases[node] )); then
        # --no-use avoids implicit .nvmrc/default activation in nvm.sh itself.
        # Let NVM resolve aliases (including LTS), then require an installed binary.
        if builtin source "$NVM_DIR/nvm.sh" --no-use >/dev/null 2>&1 &&
           (( $+functions[nvm] )) && version=$(nvm version default 2>/dev/null) &&
           [[ -n $version && $version != (N/A|system|none) ]] &&
           binary=$(nvm which "$version" 2>/dev/null) && [[ -f $binary && -x $binary ]]; then
          nvm use --silent "$version" >/dev/null 2>&1
        fi
      else
        # Only nvm is lazy: node/npm/pnpm and other managers must not be wrapped.
        function nvm {
          unfunction nvm
          [[ -n ${NVM_DIR:-} && -f $NVM_DIR/nvm.sh && -r $NVM_DIR/nvm.sh ]] || return 127
          builtin source "$NVM_DIR/nvm.sh" --no-use || return
          (( $+functions[nvm] )) || return 127
          nvm "$@"
        }
      fi
    fi
  fi

  # Do not steal pnpm from an active manager, corepack, function or alias.
  if [[ -n ${PNPM_HOME:-} ]] &&
     (( ! $+commands[pnpm] && ! $+functions[pnpm] && ! $+aliases[pnpm] )); then
    pnpm_home=$PNPM_HOME
    # Convert only the lookup path, not the user's native environment value.
    if [[ $OSTYPE == (cygwin|msys)* && $pnpm_home != /* ]] && (( $+commands[cygpath] )); then
      pnpm_home=$(command cygpath -u -- "$pnpm_home" 2>/dev/null) || return 0
    fi
    for dir in "$pnpm_home/bin" "$pnpm_home"; do
      if [[ -f $dir/pnpm && -x $dir/pnpm ]] ||
         { [[ $OSTYPE == (cygwin|msys)* && -f $dir/pnpm.exe && -x $dir/pnpm.exe ]]; }; then
        path+=("$dir")
        export PATH
        break
      fi
    done
  fi
  return 0
}
