#!/bin/bash
set -euo pipefail
for package in /packages/focal--*.deb; do
  printf 'EXTRACT %s\n' "$package"
  dpkg-deb --fsys-tarfile "$package" | tar --keep-directory-symlink --no-same-owner -xpf - -C /
done
if [ ! -e /usr/bin/awk ]; then ln -s gawk /usr/bin/awk; fi
if [ ! -e /usr/bin/cc ]; then ln -s gcc /usr/bin/cc; fi
mkdir -p /work/home/run /work/tmp /work/source /work/build /work/stage /work/logs
chmod 700 /work/home /work/home/run /work/tmp
gcc --version
make --version
python3 --version
/lib/x86_64-linux-gnu/libc.so.6
