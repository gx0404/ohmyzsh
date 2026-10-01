# 安装与运维工具规则（tools/、templates/）

适用 scope：`tools/**`（7 个脚本）、`templates/**`（zshrc 模板）。
这层脚本被 `curl | sh` 直接执行或随每次启动 source，属安全敏感面。

## install.sh（604 行，POSIX sh）

- 必须保持 POSIX sh 兼容（dash 可执行）：禁用 bashism（数组、`[[ ]]`、进程替换）。
  CI 的 installer.yml 在 ubuntu/macos 矩阵用 `sh ./tools/install.sh` 验证。
- 环境变量契约：`ZSH`、`ZDOTDIR`、`REPO`、`REMOTE`、`BRANCH` 可覆盖安装目标；
  参数 `--unattended`、`--keep-zshrc`、`--skip-zshrc`、`--skip-chsh`。
  `--unattended` 下严禁任何交互提示（确认、选择、读 stdin）。
- 备份语义：保留原 `~/.zshrc` 为 `.zshrc.pre-oh-my-zsh`；uninstall.sh 依此恢复。
  改备份命名会破坏卸载路径，两侧必须同步。
- 不落盘任何凭据；模板写入内容来自 templates/zshrc.zsh-template。

## check_for_upgrade.sh（每次启动 source）

- `zstyle ':omz:update' mode` 闭集：prompt / auto / reminder / disabled（后台
  background-alpha 属实验位）。未声明的 mode 必须回退到 prompt，不得报错打断启动。
- 基于 epoch 节流：未到检查间隔必须完全静默（零输出、零 git 调用），
  否则拖慢所有用户每次启动。
- 写状态文件到 `$ZSH_CACHE_DIR`，不得写仓库目录。

## upgrade.sh 与 changelog.sh

- upgrade.sh verbosity：`-v default|minimal|silent`、`-i`、`-c <days>`；
  silent 模式零输出。
- changelog.sh（`omz changelog` 后端）从 Conventional Commits 生成变更日志，
  内置 TYPES 表（feat/fix/docs/...）。commit 格式或 TYPES 变更会直接改变生成结果，
  改动需同步验证 `omz changelog` 输出。
- require_tool.sh 用 awk 实现 strverscmp 语义的版本比较，供其他工具复用；
  不得引入新的外部依赖。

## 修改纪律

- 这些文件是上游高频改动区：fork 侧保持零定制；确需定制优先评估移到
  custom/ 或独立插件。上游英文注释风格不变。
- templates/zshrc.zsh-template 的注释是安装器写给最终用户的说明书；
  minimal.zshrc 服务 devcontainer。

## 验证

- `bash scripts/check_syntax.sh` 对 tools/*.sh 做 `sh -n`、对 zsh 脚本做 `zsh -n`。
- install/uninstall 路径改动：在隔离 `ZDOTDIR`/`HOME`（mktemp）演练装-卸-恢复循环，
  证据留 `python3 scripts/dev_framework.py evidence installer-rehearsal` 批次目录；
  不得碰真实 `$HOME`。
