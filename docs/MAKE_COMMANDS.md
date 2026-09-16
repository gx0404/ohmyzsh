# 命令手册

真源是 `docs/dev-framework.json`（argv 数组 + 仓库相对 cwd）；Makefile 与本手册
只是入口和语义说明。`make help` 输出各命令状态。

## 框架目标

| 目标 | 语义 |
|---|---|
| `make framework-check` | 路由闭集校验（resolver --check：全仓文件零遗漏零重叠、规则体量、文档闭集） |
| `make framework-ready` | 配置完整门（无 pending 命令、project.reviewed=true） |
| `make ai-doctor` | 各 configured 命令的 argv[0] 存在性盘点（FOUND/MISSING；不安装不运行） |
| `make ci-check` | ready → resolver --check → version --check → ci 列表（lint/test/generated-check） |
| `make version` / `version-check` / `version-write` | CHANGELOG.md SemVer 读取 / 一致性 / 写镜像（当前无镜像目标） |
| `make evidence <task>` | 分配 `.playwright-mcp/<分支>/<任务>/<批次>/` 证据目录（results/ + report/ + result.json[PENDING]） |

## 业务命令（17 个）

| 命令 | 绑定 | 说明 |
|---|---|---|
| setup | scripts/setup_env.sh --print | 环境盘点与补装指引；绝不自动安装 |
| dev | scripts/dev_shell.sh | 隔离 ZDOTDIR 启动交互 zsh，打印 omz version/主题/别名 |
| build | N/A | 解释型框架，zwc 由运行时 zrecompile 自理 |
| lint | scripts/check_syntax.sh | 全量语法检查（与上游 CI 目标集一致 + 按 shebang 分派扩展） |
| typecheck | N/A | 动态语言无类型检查器 |
| test | scripts/run_tests.sh | 语法 + 单元（lib/tests/cli.test.zsh）+ 加载 smoke + gx 安装演练 |
| test-integration | tests/smoke_load.zsh --plugins git,docker | 多插件组合加载断言 |
| test-heavy | N/A | 无打包/真机层；更多组合按需扩展 --plugins |
| generated-check | build_agent_kb.py --check | KB 与语料一致性（接入 ci） |
| ui-smoke | scripts/ui_smoke.sh | 终端渲染证据（主题分支段断言 + omz 子命令） |
| graph / graph-check | scripts/graphify.sh build/check | 图谱构建 / 指纹新鲜度 |
| kb / kb-check | build_agent_kb.py --confirm/--check | 知识库再生 / 一致性 |
| package | N/A | 发布形态为 git 分支/tag |
| gx-install | gx/install.sh | gx 个人配置层部署到本机（本地模式；选项见 gx/README.md；安装类不进 ci） |
| gx-bundle | gx/bundle.sh | 工作树打包 tar.gz 离线安装包（U 盘分发；不进 ci） |

## 环境依赖

必需：zsh、git、python3（3.11+ 或已装 tomli）。可选：zunit（插件测试族）、
shellcheck、tmux（终端捕获）、graphify（make graph）。缺失项 `make ai-doctor`
与 `scripts/setup_env.sh --print` 如实报告，不静默跳过报绿。

## 退出码纪律

质量门不吞失败：验收命令不接 `| tail` 一类吞退出码管道，以 `$?` 或落盘文件判定；
pending 命令直接失败（PENDING 前缀），N/A 打印理由返回 0。
