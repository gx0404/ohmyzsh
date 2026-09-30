# 版本与发布

## 版本双体系（本仓特有）

| 体系 | 真源 | 消费者 | 说明 |
|---|---|---|---|
| 上游体系 | git tag + Conventional Commits | `omz version`（lib/cli.zsh）、`omz changelog`（tools/changelog.sh 动态生成） | 不落盘文件；fork 继续沿用，不受框架影响 |
| fork 体系 | `CHANGELOG.md`（`## X.Y.Z(日期|TBD)`） | `make version` / `version-check`（scripts/version.py 取最大数值 SemVer） | 只记 fork 侧已实现行为；上游同步类改动记 `chore(upstream)` 条目 |

两条规则：

1. CHANGELOG.md 只记录**已实现并通过验证**的行为；计划与承诺不写入。
2. 不引入与上游竞争的文件版本镜像（version_targets 为空）；若未来需要
   （如发布 fork 安装脚本版本），在 dev-framework.json 的 version_targets 登记
   并用 `make version-write` 同步，先全量校验后原子写入。

## fork 版本节奏

- 破坏性变更（规则契约、命令语义变更）：主版本位 + `BREAKING CHANGE`。
- 新能力（新规则域、新命令层）：次版本位。
- 修正与文档：补丁位。发布时把 `(TBD)` 改为 `(YYYYMMDD)`。

## 发布形态与当前状态

GX 增加独立的 Windows x64 EXE 与 Ubuntu amd64 DEB 打包链，不调用上游
`tools/install.sh` 或上游发布工作流。PR 仍遵循上游模板，披露 AI 参与程度。

**当前仍为开发中，不能将脚本、单测或 herdr 二进制构建成功等同于安装包已验收。**
中文配置/缓存路径、完整依赖再分发材料、真实安装升级卸载和 TUI 验收必须全部通过，
才能发布。禁止通过限制英文配置目录、关闭补全/P10k 缓存或跳过失败检查来降格交付。

| 平台 | 包装 | 运行环境与边界 |
|---|---|---|
| Windows x64 | Inno Setup EXE | 私有 MSYS2 Zsh + 原生 MSVC herdr + 完整 app-local ConPTY；不是 WSL，不覆盖既有 MSYS2 |
| Ubuntu amd64 | dpkg-deb | 系统管理的 GX 资源和 musl herdr；apt 解决声明的系统依赖，不能称为全依赖离线包 |

运行入口为 `gx-zsh` 和托管 `herdr`。用户 profile 与安装目录分离，不在 package
postinst 中改写 `.zshrc` 或执行 chsh；卸载保留配置、历史、会话。托管入口阻止
`herdr update` 和 `herdr channel set` 回到上游分发，升级经新的 GX 安装包完成；
这个限制不等于修改了内部 herdr 二进制的自更新实现。

Zsh 使用固定 5.9.2 源码和 `patches/zsh/` 中的中文路径修复，不替换系统 Zsh。
Linux 在固定 Focal 用户态构建，运行期需要 libc6、libncursesw6、libtinfo6；打包器
拒绝 GLIBC 高于 2.31 的产物。配置模块静态链接，不支持额外加载第三方动态 Zsh 模块。
P10k 的内部运行副本位于 profile 的版本化缓存目录，指纹同时绑定主题源码、平台与
Zsh 二进制；升级不覆盖旧指纹缓存，资源树不产生 `.zwc`。无控制终端时不初始化提示符
主题/instant prompt/gitstatus，OMZ CLI 与插件仍加载；真实 TTY 保留完整提示符和缓存。

## 固定输入与本地打包

真源：`scripts/packaging/dependencies.json`、MSYS2 子锁、CHANGELOG 和完整 Git SHA。
本组件已并入 `gx0404/gx_shell` 单仓：锁里 herdr 只写 `"source": {"monorepo_path": "herdr"}`，
加载时解析为当前检出提交的 `herdr/` 子目录——revision 即该提交 SHA，版本取自
`herdr/Cargo.toml`，源码为该提交 `git archive` 的 zip 及其 SHA-256；再分发锁里 herdr
组件的对应源码绑定同一归档。`gx_package.py stage` 把已解析的锁写入快照，脱离 Git
工作树仍可复核同一提交；`--ref` 必须是提供 herdr 的已检出提交。herdr 以
`HERDR_PACKAGE_MANAGER`（Windows `windows-installer`、Ubuntu `deb`）编译，自更新与
渠道切换在二进制内关闭。构建工具版本、依赖摘要、对应源码及许可都必须核对。herdr 版本变化时，
同一提交里要把 `redistribution-lock.json` 中 herdr 组件的 `version` 改成新版本并更新
`dependencies.json` 的 `canonical_sha256`，否则加载锁即报错，audit 与打包失败。
单仓里本组件不再单独发版，GX Shell 合并安装包由单仓根目录的发版流程生成。

herdr 包构建（`scripts/gx_build_herdr.py`）默认只在一次性 GitHub-hosted runner 上运行，receipt 记
`builder=github-actions`；**只有 herdr receipt 为 `builder=github-actions` 的 stage 可以发布**。本机
完整构建时设 `GX_LOCAL_BUILD_ROOT=<已存在的目录>`（GitHub Actions 上设了它会被拒绝）：工作、缓存与
输出目录都须在该目录之内，环境里不能有 `GITHUB_TOKEN`/`GH_TOKEN`，receipt 记 `builder=local`。
herdr 构建与 Windows 目标的启动器编译都设 `RUSTUP_AUTO_INSTALL=0`，锁定的 Rust 工具链须事先装好、
缺少即失败；Windows 目标显式使用 `<锁定版本>-x86_64-pc-windows-msvc`，rustup 默认 host 是 GNU 时
也不会用错。`gx_package.py stage` 只在源码干净（未用 `--allow-dirty`）且 receipt 的 builder 为
`github-actions` 时写 `publishable: true`，`builder=local` 或缺少该字段一律不可发布；`verify-stage`
拒绝自称可发布、builder 却不是 `github-actions` 的 stage，`verify --require-release` 拒绝 builder
不是 `github-actions` 的包。单仓 `gx_shell_package.py assemble` 不加 `--allow-dirty` 就拒绝这类
stage，加了之后产物名带 `-local`，单仓 `verify` 也只在 `--allow-dirty` 下接受它们，发版流程因此
不会上传。单仓 `scripts/gx_shell_stage_shell.sh` 在设了 `GX_LOCAL_BUILD_ROOT` 时以 `--allow-dirty`
stage：未提交的 Oh My Zsh 改动会进包，herdr 仍按已提交的 HEAD 构建。不要伪造 CI 环境变量绕过
runner 检查。

```bash
python3 scripts/gx_dependencies.py audit --platform ubuntu-amd64
python3 scripts/gx_dependencies.py fetch --platform ubuntu-amd64 --cache /绝对路径/cache
python3 scripts/gx_dependencies.py verify --platform ubuntu-amd64 --cache /绝对路径/cache
python3 scripts/gx_build_zsh.py fetch --platform ubuntu-amd64 --cache /绝对路径/cache
python3 scripts/gx_build_zsh.py build --platform ubuntu-amd64 --cache /绝对路径/cache \
  --work /绝对路径/新构建目录 --output /绝对路径/zsh-build
python3 scripts/gx_dependencies.py assemble --platform ubuntu-amd64 \
  --cache /绝对路径/cache --herdr-build /绝对路径/herdr-build \
  --zsh-build /绝对路径/zsh-build --output /绝对路径/dependencies
```

`fetch` 只取锁内资产；下载成功不代表对应源码或许可材料完整。`assemble` 离线读取
已校验资产，输出必须是新目录，不能拿包含实验 HOME/keyring/cache 的 MSYS2 工作树
冒充发行负载。herdr build receipt 及产物必须来自真实固定版本构建和签名验证。

Windows 私有运行时 = MSYS2 base 快照 + 锁内签名包（含 diffutils、patch、unzip/zip、
tree、bc、procps-ng、vim、rsync、jq 等常用工具），不运行 pacman 或安装脚本。签名包带
`upgrades_base` 时整体替换 base 快照里的同名旧版本：先按 pacman 本地库的文件清单与 mtree
摘要核对全部旧文件，全部一致才删除旧文件及其本地库条目并装新包，依赖 manifest 的
`msys2_upgrades` 记录这次替换（msys2-runtime 3.6.10-5 → 3.6.10-6，修复调用 winget、应用商店
别名后挂死的问题，上游 msys2/msys2-runtime#372），`verify-bundle` 按锁复核该记录并拒绝载荷里残留的
旧版本地库条目。覆盖安装时 Inno 不删除新载荷里没有的旧文件，所以每个 `upgrades_base` 都要在单仓
`packaging/windows/gx-shell.iss` 的 `[InstallDelete]` 里删除
`{app}\runtime\msys64\var\lib\pacman\local\<包名>-<旧版本>`（单仓根单测
`test_upgrades_delete_the_pacman_records_of_replaced_base_packages` 守门）。

运行时现在随包带上游 MSYS2 的 `etc/fstab`（此前被排除）：盘符路径从 `/cygdrive/c/...` 变为
`/c/...`（与 Git for Windows 一致）。这是用户可见的破坏性变化，历史记录、脚本、配置里手写的
`/cygdrive/...` 路径不再可用。GX 只改 filesystem 包的两个文件：`etc/fstab` 在上游内容之外
把 Windows 用户临时目录（进程的 `TMP`/`TEMP`）挂到 `/tmp`，启动器不再改写原生子进程的
`TEMP`/`TMP`，所以它就是用户自己的 `%TEMP%`；`etc/nsswitch.conf` 改为
`db_home: env windows cygwin desc`，home 先取 `HOME`（未设置时取 `USERPROFILE`）再取
Windows profile，启动器令 `HOME=USERPROFILE`，ssh 因而使用 `%USERPROFILE%\.ssh`。改后的
文件在 `scripts/packaging/notices/msys2-overlay/`，作为 msys2-filesystem 的对应源码随再分发
材料发布；`msys2-lock.json` 的 `overlay` 钉住原文件与新文件摘要，上游原文件变化时
`assemble` 失败，须复核后再更新。依赖 manifest 与 stage manifest 都记录 `msys2_overlay`，
`verify-bundle`、`verify-stage` 逐项核对载荷里的文件摘要。

新增 MSYS2 包时从同一签名库解析依赖闭包：`msys2-lock.json` 记包 URL、SHA-256 与
`.sig`；`redistribution-lock.json` 按 pkgbase 记 `.src.tar.zst` 及 `.sig`、`notices/msys2/`
下的 PKGBUILD 与许可文本、`.SRCINFO` 摘要和 source_members；再更新 `dependencies.json`
的 `canonical_sha256`，依次跑 audit、fetch、verify、assemble。已入库 notice 改动后，本地
cache 中的同名旧文件要先删除，`fetch` 不覆盖摘要不符的缓存。

```bash
GX_DEPENDENCY_BUNDLE=/绝对路径/dependencies \
GX_PACKAGE_PLATFORM=ubuntu-amd64 GX_RUSTC=/绝对路径/rustc make package
```

Windows 从 PowerShell 设置对应环境变量，另设 `GX_ISCC` 为已有的 Inno 编译器路径；
可直接执行 `python scripts/gx_package_entry.py`。入口不会安装工具、部署到 HOME 或发布。
`GX_PACKAGE_REF` 默认 HEAD；`GX_PACKAGE_OUTPUT` 默认 `dist/gx`，每次分配新批次。
`--dry-run` 只打印参数，不创建输出。显式 `GX_PACKAGE_ALLOW_DIRTY=1` 仅用于开发包，
其 manifest 永远不可公开发布。正式包从干净 Git 对象读取资源，保持 shell 文本 LF，
排除 `gx/config/zshrc.local`、用户 `custom/`、缓存、凭据和开发目录。

低层入口及产物复核：

```bash
python3 scripts/gx_package.py stage --platform ubuntu-amd64 --ref <SHA> \
  --dependencies /绝对路径/dependencies --output /绝对路径/stage --rustc /绝对路径/rustc
python3 scripts/gx_package.py verify-stage --stage /绝对路径/stage
python3 scripts/gx_package.py build --stage /绝对路径/stage --output /绝对路径/artifacts
python3 scripts/gx_package.py verify --manifest /绝对路径/artifacts/<名称>.manifest.json
```

输出安装器、对应源码 tar.xz、manifest 和 sha256。结构验证通过仍不能证明用户环境
可运行；manifest 的 lifecycle/pty 初值为 pending，不得手工改为 passed。

## 手动 GitHub Release

本节只适用于独立的 gx0404/ohmyzsh 仓库。单仓中本目录的 workflow 不执行：GX Shell 合并安装包由单仓
根 `.github/workflows/release.yml` 构建，在一次性 Windows runner（能下载到 0.1.0 安装包时还验证从
GX Shell 0.1.0 升级）和 Ubuntu 20.04/24.04 容器里跑安装—使用—卸载冒烟，全部通过后才发布。

`.github/workflows/gx-release.yml` 仅接受 `workflow_dispatch`，`publish` 默认 false。
工作流必须先经人工审阅进入默认分支；本文不授权自动 commit、push、改默认分支或发包。

- 两平台锁同一 ohmyzsh SHA 与 herdr SHA；构建 job 只读，checkout 不保留凭据。
- 完整包、源码、许可、校验值和 Windows / Ubuntu 20.04 / 24.04 实际验收证据齐备后，
  `scripts/gx_release.py::verify` 才允许进入发布。
- 只有 publish job 临时获得 contents:write，controller 来自可信工作流 SHA；其他 ref
  可以只读构建，不能把任意 ref 的脚本带入持写权限发布步骤。
- 标签为 `gx-vX.Y.Z`。不移动标签，不覆盖已公开 Release；草稿必须绑定相同 SHA 和
  资产摘要，上传完成后核对远端 size/digest 才公开。
- 缺环境、中文运行时错误、生命周期入口或锁定材料缺失时必须失败，不以文件存在证明成功。

```bash
python3 scripts/gx_release.py prepare --ref <SHA> --version <X.Y.Z>
python3 scripts/gx_release.py verify --sha <SHA> --version <X.Y.Z> --artifacts /绝对路径/artifacts
```

发布验证的必需检查名以 `scripts/gx_release.py::COMMON_CHECKS`、`WINDOWS_CHECKS` 和
`LINUX_CHECKS` 为准。测试用 synthetic installer/证据只能验证消费者逻辑，不构成真实验收。

## upstream 同步（周期性维护）

```bash
git fetch upstream && git merge upstream/master
make framework-check   # 新文件未路由会红 → 补 routes.toml（bootstrap 闭集）
make ci-check          # 语法/加载/KB 全量复验
make kb                # 语料变化后再生 chunks.json 并审 diff
```

同步后在 CHANGELOG.md 的当前版本下补 `chore(upstream)` 条目（同步到哪个
commit、是否有冲突处理）。上游合并冲突只允许出现在 .gitignore 标记块；
出现在其他文件即违反只增不改纪律，需回查定制来源。
