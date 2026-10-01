# gx 个人配置层规则（gx/）

适用 scope：`gx/**`（个人 zsh 配置固化层：config/、omz-custom/、bin/、fonts/、
wezterm/、history/、install.sh、bundle.sh、README.md）。本层是 fork 特有的"把一台机器的
shell 环境复制到另一台机器"的交付物，部署目标是用户真实 `$HOME`，属安全敏感面。

## 结构与真源

- `gx/config/` 是唯一配置真源：zshrc、zshenv、zshrc.local（机器差异层：
  CUDA/TensorRT、相机 SDK 等——**不入安装器部署对**，换机不带走；目标机已有
  同名文件原样保留，缺失时 zshrc 的 `[[ -r ... ]]` 守卫静默跳过）、p10k.zsh。
  在本机改了 `~/.zshrc` 等文件后必须回填 gx/config/ 并提交，否则下次安装会把
  本机配置回退到仓库旧版。
- `~/.zshrc` 归 gx 层真源（2026-09-21 拍板）：wezterm 安装器历史追加的
  `# >>> wezterm-gx >>>` cursor-mode 键位块已并入 `gx/config/zshrc`（位置在全部
  `zle -N`/bindkey 之后、autosuggestions 与 syntax-highlighting source 之前）；
  `install.sh::deploy_configs` 备份+整体替换 .zshrc 时检测并告知剥离该块。
- vendored 组件：`gx/omz-custom/themes/powerlevel10k/` 是 romkatv/powerlevel10k
  的提交树快照（无 .git，版本钉在 gx/README.md 清单）；
  `gx/bin/gitstatusd-linux-x86_64`（v1.5.4，运行期部署到
  `${GITSTATUS_CACHE_DIR:-~/.cache}/gitstatus/`）与
  `gx/bin/zoxide-linux-x86_64`（0.9.9）；`gx/fonts/` 是 Nerd Fonts v3.4.0
  JetBrainsMono 四字重；`gx/wezterm/` 是 `~/.config/wezterm` 工作树快照
  （含背景图，缺目录会破坏 backdrops.lua）。升级任一组件须同步更新
  gx/README.md 的来源/版本/复刻命令清单。
- 目录名用 `gx/omz-custom/` 而非 `gx/custom/`：上游 `.gitignore` 的 `custom/`
  模式会连带忽略嵌套同名目录，且目录级排除无法用取反恢复。
- `gx/history/` 是本机 Zsh 历史的**可公开子集**生成物（`scripts/gx_history.py::summarize`
  白名单统计与逐字符匹配精选，产出 `seed.zsh_history`/`summary.json`），不含原始参数、
  时间戳、工作目录与自由文本；再生流程、隐私边界与回归见 `gx/history/README.md` 与
  `tests/test_gx_history.py`，白名单扩词必须逐条确认可公开后才收录。

## 原生包 profile

- `gx/config/package.zsh` 只在 `GX_PACKAGE_ROOT` / `GX_PROFILE_DIR` 成对有效时启用，
  profile 必须独立于 HOME 与只读资源树。`ZDOTDIR` 由启动器管理；包模块不得重新指定。
- Zsh 缓存、历史与 P10k instant prompt 归 profile；不能把 XDG config/data/state
  全局重定向到 profile，否则 herdr socket 和既有 agent 的登录配置归属会改变。
- `GX_PACKAGE_BIN` 在调用外部工具前进入进程 PATH；MSYS 的 `OSTYPE` 可能是 cygwin，
  不得仅以 msys 前缀判断。不能把整套 MSYS usr/bin 注册进 Windows 全局 PATH。
- 包模式只加载 profile 的机器层和 P10k 覆盖；legacy `gx/install.sh` 的 HOME 部署
  契约不变。必须保留顶格 `export ZSH=` 的安装器改写入口，并分别测试两种模式。
- fzf completion 与 key-bindings 都包含 ZLE 操作，仅在真实 TTY 且 ZLE 启用时加载；
  无终端仍设置版本兼容选项、保留普通补全，不吞初始化错误。
- 中文 HOME、独立配置和缓存是必验场景；不得用 ASCII 路径、禁用缓存、关闭 compfix
  或 expectedFailure 替代。原生包当前验证状态见 `docs/RELEASE.md`。

## 修改纪律

- 严禁把凭据、token、内网密码写入任何 gx/ 文件；提交前对 gx/config/ 执行
  敏感词扫描（token|secret|password|api_key，含值形态零容忍）。
- zshrc 中机器差异路径一律放 zshrc.local 且缺失不报错；新增第三方集成沿用
  `[[ -r ... ]]` / `$+commands[...]` 存在性守卫风格，保证新机缺组件时静默降级。
- install.sh / bundle.sh 是 POSIX sh（dash 可执行），会被 `curl | sh` 执行：
  禁 bashism；绝不 rm 用户既有文件——一律 mv 为 `*.pre-gx-<时间戳>` 备份；
  仅允许删除带 `.gx-managed` 标记的本安装器前次产物，以及本安装器自己打的
  `.pre-gx-<14 位时间戳>` 备份中超出 `GX_KEEP_BACKUPS`（默认 2，`all` 关闭回收）的
  **中间世代**（`install.sh::prune_backups`，只认该后缀形态）。时间戳最小的「第一代」
  是唯一不可再生的 gx 前原件，永久保留、任何路径任何份数设置都不回收；`$ZSH` 整树
  固定「第一代 + 1 份」，`$ZSH/custom/` 下的目标（p10k）不回收。补全缓存：无后缀
  `.zcompdump` 与其他主机/版本的 dump（含残留 `.lock` 锁**目录**）总清；当前一族只在
  源快照指纹（`$ZSH/.gx-managed` 的 `snapshot:` 行，`install.sh::deploy_omz_repo` 写入）
  与上次部署一致时保留——omz 自己的判据只有 `#omz fpath:` 与 compinit 的「文件数 +
  版本」，`#omz revision:` 在无 `.git` 的快照部署下恒为空，不能用它论证安全性。
  清理补全缓存的循环必须容错（锁是目录、`rm` 会失败），失败只告警不中止。重装采用「新树同级就位
  → 合并 custom（符号链接原样保留）→ 两次 rename 替换」，不得引入任何把用户
  数据搬离原位再回填的中间态。
- 同秒备份/中转/卸载移出路径占用时退出 2，提示稍后重试；`guard_timestamp_paths`
  预检和移动前复查均不能覆盖已有文件、目录或悬空链接。`.gx-new-*` 必须独占创建，
  不先删除残留。此防线不是多进程共享目标的完整事务锁；确定性冻结时间回归见场景 K。
- `--home` 显式给出时必须忽略继承的环境 `ZSH`（gx 会话里它指向真实
  `~/.oh-my-zsh`）；环境 `ZSH` 不在部署 home 之下且未传 `--zsh` 时 unattended
  拒绝、交互须确认。测试不得靠 `unset ZSH` 掩盖这条互锁：smoke 场景 G/H 与
  `gx_terminal.py::InstallerZshInterlock` 用 mktemp 内假树验证。
- 不修改上游 tools/install.sh 与 templates/；gx 安装器独立实现（工作树快照
  部署，omz 自动更新在 gx/config/zshrc 中已 `zstyle ':omz:update' mode
  disabled`，升级 = 重跑安装器）。

## 验证

- 任何 install.sh / config / vendored 组件改动后运行
  `zsh tests/gx_install_smoke.zsh`（已接入 `make test`）：隔离 HOME 部署断言、
  交互加载断言（p10k + 插件别名 + omz version）、幂等重装（custom 层保全、
  符号链接 custom 保留、上级不可写时中止不改旧树）、既有配置备份、`--uninstall`
  恢复、自定义 ZSH 路径改写、`--home` 与环境 `ZSH` 互锁、重装保留当前
  zcompdump 且下次启动不重建（含残留 `.lock` 目录不打断安装器、快照指纹变化时清 dump）、
  `.pre-gx-*` 按 `GX_KEEP_BACKUPS` 回收且第一代永存（含 `--uninstall` 之后）。所有安装器
  调用经 `run_installer`（TMPDIR 指进沙箱、剥离宿主 `ZSH`/`GX_*`，需要传环境变量时写成
  `run_installer VAR=值 …` 前缀），fc-cache 缓存断言落在隔离 HOME。
- config 改动同时运行 `python3 tests/gx_terminal.py`（已接入 `make test`）：
  模块单元用例之外，DeployedZshrc / DeployedInteractive 用 install.sh 落地
  mktemp HOME 后走真实 `.zshenv/.zshrc` 链与真 PTY `zsh -i`（不加 `-f`），
  覆盖 p10k instant prompt 生效形态；只在 `zsh -f` 下验证的守卫不算通过。
- 性能项改前/改后都在部署 HOME 的真 PTY 里测 precmd 链（20 次取中位）：
  `zmodload zsh/datetime; for i in {1..20}; do t0=$EPOCHREALTIME; for f in
  $precmd_functions; do $f; done; print $(( (EPOCHREALTIME - t0) * 1000 )); done`；
  启动用 `hyperfine -w 3 -r 20 'zsh -i -c exit'`（无 hyperfine 时 python 计时
  20 次取中位），有/无 `.zcompdump-*` 两态各测一次，数字写进交付说明。
- 真实安装/卸载/迁移循环演练留 `make evidence` 批次证据并读回；测试与演练
  只写 mktemp 隔离目录，在真实 `$HOME` 执行安装器属于用户主动行为，
  须用户明确确认后方可进行。
