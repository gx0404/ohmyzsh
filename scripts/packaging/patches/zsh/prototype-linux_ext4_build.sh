#!/bin/sh
set -eu
ROOT=$1
EVIDENCE=${2:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)}
export HOME="$ROOT/home" XDG_CONFIG_HOME="$ROOT/home/.config" XDG_CACHE_HOME="$ROOT/home/.cache" XDG_DATA_HOME="$ROOT/home/.local/share" TMPDIR="$ROOT/tmp" TMPPREFIX="$ROOT/tmp/zsh" CARGO_HOME="$ROOT/home/.cargo"
export PATH="$ROOT/tools/usr/bin:/usr/bin:/bin"
mkdir -p "$HOME" "$TMPDIR" "$ROOT/source" "$ROOT/build" "$ROOT/tools" "$ROOT/stage" "$ROOT/logs"
(cd "$EVIDENCE/downloads" && sha512sum -c "$EVIDENCE/ubuntu-tools.sha512")
if [ -d "$EVIDENCE/linux-tools" ]; then
  cp -a "$EVIDENCE/linux-tools/." "$ROOT/tools/"
else
  for package in "$EVIDENCE"/downloads/*.deb; do
    dpkg-deb -x "$package" "$ROOT/tools"
  done
fi
actual=$(sha256sum "$EVIDENCE/downloads/zsh-5.9.2.tar.xz")
[ "${actual%% *}" = 36fa734374b44783582cec09bcd67822e2f992c779ec1624ab5596df078d2f81 ]
actual=$(sha256sum "$EVIDENCE/patches/zsh-5.9.2-metafied-paths.patch")
[ "${actual%% *}" = 230fc112b509bece56e97c1485b6de2ed32ca695b43af4628a697a8954a4107d ]
tar -xJf "$EVIDENCE/downloads/zsh-5.9.2.tar.xz" -C "$ROOT/source"
cd "$ROOT/source/zsh-5.9.2"
patch --fuzz=0 -p1 < "$EVIDENCE/patches/zsh-5.9.2-metafied-paths.patch"
cd "$ROOT/build"
export CPPFLAGS="-I$ROOT/tools/usr/include"
export LDFLAGS="-L$ROOT/tools/usr/lib/x86_64-linux-gnu"
export CFLAGS="-O2 -ffile-prefix-map=$ROOT=."
"$ROOT/source/zsh-5.9.2/configure" --prefix=/ --bindir=/libexec/zsh --libdir=/lib --enable-fndir=/share/zsh/functions --enable-site-fndir=/share/zsh/site-functions --disable-dynamic --disable-etcdir --enable-multibyte --with-term-lib=ncursesw
cp "$EVIDENCE/static-linux.config.modules" config.modules
make prep
make -j4
make DESTDIR="$ROOT/stage" install.bin install.modules install.fns
mkdir -p "$ROOT/stage/share/licenses/zsh"
cp "$ROOT/source/zsh-5.9.2/LICENCE" "$ROOT/stage/share/licenses/zsh/LICENCE"
"$ROOT/stage/libexec/zsh/zsh" --version
make TESTNUM=A09 check
make TESTNUM=D03 check
