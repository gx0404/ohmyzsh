# 测试纪律（tests/、lib/tests/、插件自带测试）

适用 scope：`tests/**`（框架测试根）、`lib/tests/**`；插件自带 zunit 测试的
编写规范在 plugins.md，此处约束执行纪律。

## 分层与真源

| 层 | 入口 | 能证明 |
|---|---|---|
| 语法 | `bash scripts/check_syntax.sh` | 全部 shell 文件可被解析（与上游 CI 的 zsh -n 对等） |
| 单元 | `lib/tests/cli.test.zsh`（自包含）；zunit（可选） | awk 插件禁用逻辑等独立单元 |
| 加载 smoke | `zsh tests/smoke_load.zsh` | 隔离环境下主入口可加载、关键函数/别名就位、退出码 0 |
| 集成 | `zsh tests/smoke_load.zsh --plugins a,b` | 多插件组合加载不互相破坏 |
| 终端证据 | `make ui-smoke` + `dev_framework.py evidence <task>` | 主题渲染/omz 子命令的实际输出被捕获并读回 |

上游 CI（.github/workflows/main.yml）只做 zsh -n 且被
`if: github.repository == 'ohmyzsh/ohmyzsh'` 守卫——**fork 上不会运行**。
本地 `make ci-check` 是本仓的真实质量门；不要引用上游 CI 状态作为本 fork 的验证结论。

## 执行纪律

- 测试只写临时数据：`mktemp -d` 隔离 `HOME`/`ZDOTDIR`，结束清理；绝不写仓库跟踪
  目录、`custom/`、真实 `$HOME`。
- 缺工具链不得整族 skip 后报绿：zunit 本机未装时，`make ai-doctor` 报 MISSING，
  zunit 族不纳入默认 `make test`，也不得假装通过。补装指引见 scripts/setup_env.sh
  （打印式，不自动安装）。
- 断言失败必须让脚本非零退出；验收命令禁止接吞退出码的管道（`cmd | tail`），
  以 `$?` 或落盘文件判定。
- 每个新行为覆盖至少一条关键失败路径（如：别名冲突检测、补全缺失降级、
  非交互环境提前返回）。
- 生成型夹具（补全缓存下载）在测试中重建而非复用本地缓存。

## 证据与截图

- 证据根 `.playwright-mcp/`（gitignored）。`python3 scripts/dev_framework.py
  evidence <task>`（`make evidence` 等价于任务名 ui）分配
  `<分支>/<任务>/<批次>/` 目录；runner 只清理自己批次的 `results/`。
- 终端场景（主题渲染、omz 子命令输出、安装演练）以文本捕获为主
  （`script`/tmux capture-pane），有 tmux 时补 PNG 截图。捕获后**必须读回检查**
  内容再在 result.json 置 `images_reviewed: true`；只保存不算通过。
- 失败批次的捕获、日志保留待修复对照；修复后另开批次复测，不覆盖旧批次。
