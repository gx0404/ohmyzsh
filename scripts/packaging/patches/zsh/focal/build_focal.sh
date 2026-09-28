#!/bin/bash
set -euo pipefail
umask 022
export HOME=/work/home TMPDIR=/work/tmp TMPPREFIX=/work/tmp/zsh XDG_CONFIG_HOME=/work/home/.config XDG_CACHE_HOME=/work/home/.cache XDG_DATA_HOME=/work/home/.local/share XDG_STATE_HOME=/work/home/.local/state XDG_RUNTIME_DIR=/work/home/run CARGO_HOME=/work/home/.cargo
export PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8
printf '%s\n' '36fa734374b44783582cec09bcd67822e2f992c779ec1624ab5596df078d2f81  /source-input/downloads/zsh-5.9.2.tar.xz' | sha256sum -c -
printf '%s\n' '230fc112b509bece56e97c1485b6de2ed32ca695b43af4628a697a8954a4107d  /source-input/patches/zsh-5.9.2-metafied-paths.patch' | sha256sum -c -
mkdir -p /work/source /work/build-focal /work/stage-focal /work/logs
[ ! -e /work/source/zsh-5.9.2 ]
tar -xJf /source-input/downloads/zsh-5.9.2.tar.xz -C /work/source
cd /work/source/zsh-5.9.2
patch --fuzz=0 -p1 < /source-input/patches/zsh-5.9.2-metafied-paths.patch
cd /work/build-focal
export CFLAGS='-O2 -ffile-prefix-map=/work=.'
/work/source/zsh-5.9.2/configure --prefix=/ --bindir=/libexec/zsh --libdir=/lib --enable-fndir=/share/zsh/functions --enable-site-fndir=/share/zsh/site-functions --disable-dynamic --disable-etcdir --enable-multibyte --with-term-lib=ncursesw
cp /source-input/static-linux.config.modules config.modules
make prep
make -j4
make DESTDIR=/work/stage-focal install.bin install.modules install.fns
mkdir -p /work/stage-focal/share/licenses/zsh /work/stage-focal/bin
cp /work/source/zsh-5.9.2/LICENCE /work/stage-focal/share/licenses/zsh/LICENCE
cp /probe-input/zsh-wrapper /work/stage-focal/bin/zsh
chmod 755 /work/stage-focal/bin/zsh
/work/stage-focal/bin/zsh --version
readelf --version-info /work/stage-focal/libexec/zsh/zsh > /work/logs/focal-glibc-versions.log
ldd /work/stage-focal/libexec/zsh/zsh
make TESTNUM=A09 check
make TESTNUM=D03 check
