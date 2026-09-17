#!/usr/bin/env bash
# 测试编排：语法层 → 自包含单元（lib/tests/cli.test.zsh）→ 隔离加载 smoke。
# 逐层真实执行并汇总裁决；任一层失败整体非零退出，不用管道吞退出码。
set -uo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root" || exit 2

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

echo "=== summary ==="
printf '%s\n' "${summary[@]}"
exit "$overall"
