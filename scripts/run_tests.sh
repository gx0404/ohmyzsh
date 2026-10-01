#!/usr/bin/env bash
# 测试编排：语法/单元 → 隔离加载与安装 → GX profile → 打包和发布单元。
# 逐层真实执行并汇总裁决；任一层失败整体非零退出，不用管道吞退出码。
set -uo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root" || exit 2

# 构建边界：测试临时数据一律留在项目内 .build/（gitignored）。
# TMPDIR 给 shell/mktemp；TEMP/TMP 用 Windows 形态给原生 Python 与子进程。
build_tmp="$repo_root/.build/tmp"; mkdir -p "$build_tmp"
export TMPDIR="$build_tmp"
command -v cygpath >/dev/null 2>&1 && export TEMP="$(cygpath -w "$build_tmp")" TMP="$(cygpath -w "$build_tmp")"

overall=0
summary=()

run_step() {
  local name=$1; shift
  echo "=== $name ==="
  "$@"
  local code=$?
  if [ $code -ne 0 ]; then
    summary+=("FAIL $name (exit $code)")
    overall=1
  else
    summary+=("PASS $name")
  fi
  return 0
}

run_step syntax bash scripts/check_syntax.sh
run_step unit-cli zsh lib/tests/cli.test.zsh
run_step config-shapes python3 tests/check_tool_configs.py
run_step smoke zsh tests/smoke_load.zsh
run_step gx-terminal python3 tests/gx_terminal.py
run_step gx-install-smoke zsh tests/gx_install_smoke.zsh
run_step gx-package-profile python3 tests/gx_package_profile.py
run_step gx-windows python3 tests/gx_windows.py
run_step gx-package-unit python3 -m unittest discover -s tests -p 'test_gx_*.py'

echo "=== summary ==="
printf '%s\n' "${summary[@]}"
exit "$overall"
