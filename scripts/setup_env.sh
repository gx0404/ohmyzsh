#!/usr/bin/env bash
# 环境盘点（--print）：只打印工具链可用性与补装指引，绝不自动安装或登录。
# ai-doctor 检查命令入口；本脚本回答"环境里有什么、缺什么、怎么补"。
set -uo pipefail

report() { # name, 检测命令, 指引
  local name=$1 probe=$2 hint=$3
  if eval "$probe" >/dev/null 2>&1; then
    local detail
    detail=$(eval "$probe" 2>/dev/null | head -n1)
    echo "FOUND   $name ($detail)"
  else
    echo "MISSING $name — $hint"
  fi
}

case "${1:-}" in
  --print) ;;
  *) echo "usage: $0 --print"; exit 2 ;;
esac

echo "# ohmyzsh fork 环境盘点（$(date -u +%Y-%m-%dT%H:%M:%SZ)）"
report "zsh"          "zsh --version"                 "必需：sudo apt-get install zsh"
report "git"          "git --version"                 "必需：sudo apt-get install git"
report "python3"      "python3 --version"             "必需（resolver/KB）：系统包管理器安装"
if python3 -c "import tomllib" >/dev/null 2>&1 || python3 -c "import tomli" >/dev/null 2>&1; then
  echo "FOUND   tomllib/tomli（resolver TOML 解析可用）"
else
  echo "MISSING tomllib/tomli — Python<3.11 时：pip install --user tomli（resolver 前置）"
fi
report "zunit"        "command -v zunit"              "可选（插件 zunit 族）：git clone https://github.com/zunit-zsh/zunit && cd zunit && ./install.zsh"
report "shellcheck"   "shellcheck --version"          "可选（shell 静态分析增强）：sudo apt-get install shellcheck"
report "tmux"         "tmux -V"                       "可选（终端截图捕获）：sudo apt-get install tmux"
report "graphify"     "graphify --version"            "可选（make graph）：uv tool install graphifyy（PyPI 包名，双 y）"
report "msys2-host"   "test -x .build/msys64/usr/bin/bash.exe" "可选（Windows 本机 POSIX 测试宿主，项目内 .build/）：搭建见 docs/DEVELOPMENT.md 构建边界"
report "rustc"        "rustc --version"               "package/typecheck/package-test 需要 Rust；发行版本见 scripts/packaging/dependencies.json，可用 GX_RUSTC 指定隔离编译器"
report "zig"          "zig version"                   "herdr 构建需要锁定版本 Zig；只在独立构建目录配置，不替换系统工具"
report "dpkg-deb"     "dpkg-deb --version"            "Ubuntu DEB 打包工具；Windows EXE 使用通过 GX_ISCC 指定的 Inno Setup"
echo "INFO    工具存在不代表版本匹配或安装包已通过验收；发行依赖和校验值以锁文件为准。"
echo "INFO    缺可选项不阻塞普通 shell 测试；对应能力缺失必须报告，不能跳过打包检查后报通过。"
exit 0
