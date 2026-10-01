#!/usr/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
export HOME="$ROOT/msys-home" TMPDIR="$ROOT/msys-home/tmp" TMPPREFIX="$ROOT/msys-home/tmp/zsh"
export PATH=/usr/bin:/bin
mkdir -p "$ROOT/windows-build" "$ROOT/windows-stage" "$TMPDIR"
gcc --version
gcc -dumpmachine
cd "$ROOT/windows-build"
export CFLAGS="-O2 -ffile-prefix-map=$ROOT=."
"$ROOT/windows-source-v3/zsh-5.9.2/configure" --prefix=/ --bindir=/libexec/zsh --libdir=/lib --enable-fndir=/share/zsh/functions --enable-site-fndir=/share/zsh/site-functions --disable-dynamic --disable-etcdir --enable-multibyte --with-term-lib=ncursesw --enable-pcre --disable-cap --enable-zsh-secure-free
cp "$ROOT/static-msys.config.modules" config.modules
make prep
make -j"${GX_ZSH_JOBS:-4}"
make DESTDIR="$ROOT/windows-stage" install.bin install.modules install.fns
mkdir -p "$ROOT/windows-stage/share/licenses/zsh"
cp "$ROOT/windows-source-v3/zsh-5.9.2/LICENCE" "$ROOT/windows-stage/share/licenses/zsh/LICENCE"
"$ROOT/windows-stage/libexec/zsh/zsh.exe" --version
make TESTNUM=A09 check
make TESTNUM=D03 check
