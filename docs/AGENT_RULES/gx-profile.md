# gx 个人配置层规则（gx/）

适用 scope：`gx/**`（个人 zsh 配置固化层：config/、omz-custom/、bin/、fonts/、
wezterm/、install.sh、bundle.sh、README.md）。本层是 fork 特有的"把一台机器的
shell 环境复制到另一台机器"的交付物，部署目标是用户真实 `$HOME`，属安全敏感面。

## 结构与真源

- `gx/config/` 是唯一配置真源：zshrc、zshenv、zshrc.local（机器差异层：
  CUDA/TensorRT、相机 SDK 等）、p10k.zsh。在本机改了 `~/.zshrc` 等文件后必须
  回填 gx/config/ 并提交，否则下次安装会把本机配置回退到仓库旧版。
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

## 修改纪律

- 严禁把凭据、token、内网密码写入任何 gx/ 文件；提交前对 gx/config/ 执行
  敏感词扫描（token|secret|password|api_key，含值形态零容忍）。
- zshrc 中机器差异路径一律放 zshrc.local 且缺失不报错；新增第三方集成沿用
  `[[ -r ... ]]` / `$+commands[...]` 存在性守卫风格，保证新机缺组件时静默降级。
- install.sh / bundle.sh 是 POSIX sh（dash 可执行），会被 `curl | sh` 执行：
  禁 bashism；绝不 rm 用户既有文件——一律 mv 为 `*.pre-gx-<时间戳>` 备份；
  仅允许删除带 `.gx-managed` 标记的本安装器前次产物。重装采用「新树同级就位
  → 合并 custom（符号链接原样保留）→ 两次 rename 替换」，不得引入任何把用户
  数据搬离原位再回填的中间态。
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
  恢复、自定义 ZSH 路径改写、`--home` 与环境 `ZSH` 互锁。所有安装器调用经
  `run_installer`（TMPDIR 指进沙箱），fc-cache 缓存断言落在隔离 HOME。
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
