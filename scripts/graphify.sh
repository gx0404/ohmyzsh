#!/usr/bin/env bash
# graphify 图谱 wrapper（产物 graphify-out/，gitignored）。
#
# 子命令：
#   build             无 LLM 构图：graphify extract . --code-only --no-cluster
#   check             指纹校验：输入文件集哈希 vs graphify-out/input-fingerprint.txt
#   query "..."       透传 graphify query（BFS 图查询）
#   path "A" "B"      透传最短路
#   explain "X"       透传节点解释
#
# 已实测限制（graphify 0.9.20，2026-09）：本地 AST 不识别 .zsh / *.plugin.zsh /
# *.zsh-theme 扩展名（全仓 691 个文件 "not classified"），图谱实际覆盖 bash/python/
# json 面（tools/、scripts/、plugins/*.sh、.github/*.py 等）。lib/ 与插件主语料的
# 结构检索由知识库（make kb，含 shell 函数/别名符号层）承担——图谱与 KB 互补，
# 不要用图谱否定 zsh 源码的存在。
set -uo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root" || exit 2

out_dir="$repo_root/graphify-out"
graph="$out_dir/graph.json"
fingerprint="$out_dir/input-fingerprint.txt"

compute_fingerprint() {
  # 覆盖 graphify 扫描的同一范围：全部 Git 可见文件（尊重 .gitignore）
  git ls-files --cached --others --exclude-standard -z \
    | xargs -0 sha256sum 2>/dev/null \
    | sort -k2 | sha256sum | awk '{print $1}'
}

case "${1:-}" in
  build)
    command -v graphify >/dev/null 2>&1 || { echo "FAIL graphify 未安装（scripts/setup_env.sh --print 有指引）" >&2; exit 1; }
    # 已实测：在已有 graphify-out 上增量重建可能产出 0 节点空图（0.9.20 缓存合并
    # 缺陷）；build 前整体清理，代价是每次全量抽取，但结果确定。
    rm -rf "$out_dir"
    mkdir -p "$out_dir"
    graphify extract . --code-only --no-cluster || { echo "FAIL graphify extract" >&2; exit 1; }
    [ -s "$graph" ] || { echo "FAIL 产物为空图" >&2; exit 1; }
    compute_fingerprint > "$fingerprint"
    echo "graph: $graph（指纹已记录）"
    ;;

  check)
    [ -f "$graph" ] || { echo "FAIL 未建图：先运行 make graph" >&2; exit 1; }
    [ -f "$fingerprint" ] || { echo "FAIL 缺少输入指纹（旧图）：重跑 make graph" >&2; exit 1; }
    current=$(compute_fingerprint)
    recorded=$(awk '{print $1}' "$fingerprint")
    if [ "$current" = "$recorded" ]; then
      echo "graph-check: PASS（输入未变化）"
    else
      echo "graph-check: STALE（输入已变化，重跑 make graph）" >&2
      exit 1
    fi
    ;;

  query|path|explain|affected)
    [ -f "$graph" ] || { echo "FAIL 未建图：先运行 make graph" >&2; exit 1; }
    exec graphify "$@"
    ;;

  *)
    echo "usage: $0 {build|check|query \"...\"|path A B|explain X|affected X}" >&2
    exit 2
    ;;
esac
