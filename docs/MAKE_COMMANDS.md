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

## 业务命令

| 命令 | 绑定 | 说明 |
|---|---|---|
| setup | scripts/setup_env.sh --print | 环境盘点与补装指引；绝不自动安装 |
| dev | scripts/dev_shell.sh | 隔离 ZDOTDIR 启动交互 zsh，打印 omz version/主题/别名 |
| build | N/A | 核心 shell 解释执行；原生发行入口在 package 阶段编译 |
| lint | scripts/check_syntax.sh | shell 与 GX 配置语法、框架及打包 Python AST；不证明安装模板可编译 |
| typecheck | tests/gx_launcher.py | 真实 rustc 编译并执行启动器测试；需 Rust，可用 GX_RUSTC 指定 |
| test | scripts/run_tests.sh | 原有单元/加载/安装演练、中文 GX profile 回归、打包/发布 Python 单元 |
| test-integration | tests/smoke_load.zsh --plugins git,docker | 多插件组合加载断言 |
| test-heavy | scripts/gx_lifecycle_entry.py | 仅 GitHub-hosted 可丢弃环境，需 GX_PACKAGE_MANIFEST；GX_UPGRADE_INSTALLER 指定真实新版本，Linux 需 GX_LIFECYCLE_USER。缺验收项非零退出，禁止在真实宿主运行 |
| generated-check | build_agent_kb.py --check | KB 与语料一致性（接入 ci） |
| ui-smoke | scripts/ui_smoke.sh | 终端渲染证据（主题分支段断言 + omz 子命令） |
| graph / graph-check | scripts/graphify.sh build/check | 图谱构建 / 指纹新鲜度 |
| kb / kb-check | build_agent_kb.py --confirm/--check | 知识库再生 / 一致性 |
| package | scripts/gx_package_entry.py | 显式 GX_DEPENDENCY_BUNDLE + 平台/工具链构建 EXE 或 DEB，不安装、不发布；详见 RELEASE.md |
| package-test | tests/run_package_tests.py | 打包/依赖/发布单元与原生启动器测试，不替代真实安装验收 |
| gx-install | gx/install.sh | legacy HOME 部署；选项见 gx/README.md，安装类不进 ci |
| gx-bundle | gx/bundle.sh | 工作树 tar.gz 离线包，包含未提交内容，不作为正式原生包来源 |

## 环境依赖

普通 shell 检查需要 zsh、git、Python 3.11+（旧版 resolver 可用已装 tomli）；
打包 Python 的版本下限以脚本/工作流为准，`.zst` 解包需要 Python 3.14 或显式 zstd。
原生启动器检查需 Rust，正式构建按依赖锁钉定 Rust/Zig。Windows 需要 Inno Setup，
Ubuntu 需要 dpkg-deb；入口不会替用户安装这些工具。

zunit、shellcheck、tmux、graphify 是对应能力的可选工具。缺失项必须如实报告；
`framework-ready` 的配置完整不等于工具齐备或验收通过，PENDING 期间应保持红灯。

## 退出码纪律

质量门不吞失败：验收命令不接 `| tail` 一类吞退出码管道，以 `$?` 或落盘文件判定；
pending 命令直接失败（PENDING 前缀），N/A 打印理由返回 0。
