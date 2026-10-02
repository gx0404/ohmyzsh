#!/usr/bin/env bash
# 全量语法检查：与上游 CI（zsh -n 循环）对等，并按 shebang 分派扩展到
# tools/、scripts/、tests/。任一文件失败即非零退出；不使用吞退出码的管道。
set -uo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd)
# 构建边界：临时数据不出项目（.build/ 已 gitignored）。
build_tmp="$repo_root/.build/tmp"; mkdir -p "$build_tmp"
export TMPDIR="$build_tmp"
failed=0
checked=0
fail_log=$(mktemp)
trap 'rm -f "$fail_log"' EXIT

check_one() {
  local file=$1 runner=$2
  checked=$((checked + 1))
  if ! "$runner" -n "$file" >/dev/null 2>"$fail_log"; then
    echo "FAIL [$runner -n] $file"
    sed 's/^/    /' "$fail_log"
    failed=$((failed + 1))
  fi
}

# 按 shebang 选择解释器：sh → sh（dash 兼容性即在此暴露），zsh → zsh，其余按 bash
dispatch() {
  local file=$1
  case "$(head -n1 "$file")" in
    *"/sh"*) check_one "$file" sh ;;
    *"zsh"*) check_one "$file" zsh ;;
    *) check_one "$file" bash ;;
  esac
}

cd "$repo_root" || exit 2

# --- 与上游 CI（main.yml，GX 分支归档于 .github/workflows-archive/）完全一致的目标集 ---
for file in ./oh-my-zsh.sh ./lib/*.zsh ./plugins/*/*.plugin.zsh ./plugins/*/_* \
            ./themes/*.zsh-theme; do
  [ -e "$file" ] || continue
  check_one "$file" zsh
done

# --- fork 扩展：框架自有的 shell 面 ---
for file in ./lib/tests/*.zsh ./tests/*.zsh ./tools/*.sh ./scripts/*.sh ./gx/*.sh \
            ./scripts/packaging/debian/preinst ./scripts/packaging/debian/postinst \
            ./scripts/packaging/debian/postrm ./.claude/hooks/*.sh; do
  [ -e "$file" ] || continue
  dispatch "$file"
done
for file in ./gx/config/*.zsh ./gx/config/zshrc ./gx/config/zshenv ./gx/omz-custom/plugins/*/*.plugin.zsh; do
  [ -e "$file" ] || continue
  check_one "$file" zsh
done

# --- fork 扩展：框架、打包器、测试与 hooks 的 Python 面 ---
for file in ./scripts/*.py ./tests/*.py ./.codex/hooks/*.py; do
  [ -e "$file" ] || continue
  checked=$((checked + 1))
  if ! python3 -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" "$file" \
      >/dev/null 2>"$fail_log"; then
    echo "FAIL [python ast] $file"
    sed 's/^/    /' "$fail_log"
    failed=$((failed + 1))
  fi
done

echo "syntax: checked=$checked failed=$failed"
[ "$failed" -eq 0 ] || exit 1
exit 0
