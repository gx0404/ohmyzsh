# 核心加载器规则（oh-my-zsh.sh 与 lib/）

适用 scope：`oh-my-zsh.sh`、`lib/*.zsh`、`custom/**`（覆盖机制示例模板）。
这一层定义全局加载语义；改动会波及全部插件、主题与用户会话，按最高谨慎级别处理。

## 加载顺序（不可重排）

`oh-my-zsh.sh` 的初始化顺序是外部可观察契约，调整任何一步都是 breaking change：

1. 守卫：非 zsh 执行（打印进程树后 `return 1`）；emulation mode 非 zsh 直接退出。
2. 路径与缓存：确定 `ZSH`（脚本自身目录）、`ZSH_CUSTOM`（默认 `$ZSH/custom`）、
   `ZSH_CACHE_DIR`（不可写时回退 `${XDG_CACHE_HOME:-$HOME/.cache}/oh-my-zsh`），
   创建 `completions` 缓存目录并加入 `fpath`。
3. `source "$ZSH/tools/check_for_upgrade.sh"`：更新检查发生在一切加载之前。
4. 插件 fpath 预注册（`is_plugin`：存在 `<name>.plugin.zsh` 或 `_<name>` 补全即算插件），
   必须先于 `compinit`。
5. `compinit`（安全模式 `-i`，配合 `lib/compfix.zsh`；`ZSH_DISABLE_COMPFIX=true` 时 `-u`），
   之后 `zrecompile` 编译 `.zwc`。
6. `_omz_source` 依次加载：`lib/*.zsh`（全部、字典序）→ `$plugins` 数组的
   `plugins/<name>/<name>.plugin.zsh` → `custom/*.zsh` → 主题。

## 覆盖机制

- `_omz_source`（oh-my-zsh.sh）实现 custom 优先：`$ZSH_CUSTOM/<path>` 存在则优先于
  `$ZSH/<path>` 加载。任何"用户可覆盖"的声明都必须经过这条路径，不得另造覆盖点。
- 别名回滚：`zstyle ':omz:...' aliases` 允许按插件禁用别名，逻辑在 `_omz_source`
  内基于 grep 回查 `*.plugin.zsh` 内容实现；修改别名定义方式会破坏该机制。
- `custom/**` 当前只承载上游示例模板（example.zsh 等）；框架与业务配置一律不得写入
  `custom/`——它是用户运行时层且整体被 .gitignore 排除。

## 补全与缓存

- `ZSH_COMPDUMP` 写入两行 OMZ 元数据（`#omz revision: <sha>` 与 `#omz fpath:`）；
   fpath 或 revision 变化即删缓存重建。修改元数据格式会使用户端缓存失效行为改变。
- 不安全补全目录由 `lib/compfix.zsh` 处理；不得绕过 compfix 直接调用 `compinit -u`。

## lib 关键文件与约束

- `lib/git.zsh`：git prompt 引擎。`__git_prompt_git` 以 `GIT_OPTIONAL_LOCKS=0` 运行，
  避免提示符读取触发 git 索引锁；dirty/ahead/behind 计算走这里，主题不得另起 git 进程。
- `lib/cli.zsh`：`omz` CLI（plugin/theme/update/changelog/pr 等子命令）与 `_omz` 补全。
- `lib/misc.zsh` 的 `setopt` 组、`lib/theme-and-appearance.zsh` 的 `colors`/`prompt_subst`
  与 `ZSH_THEME_GIT_PROMPT_*` 默认值是后续加载物的隐式依赖；lib 内文件按字典序加载，
  新文件名会改变加载位次——不要创建会插到既有依赖对中间的文件名。
- `lib/termsupport.zsh`、`lib/diagnostics.zsh`、`lib/async_prompt.zsh` 各自注册
  precmd/preexec 钩子；新增钩子须幂等且可重入。
- `lib/nvm.zsh` 演示惰性加载模式（首次调用才 source）；重型工具集成优先复用该模式。

## 修改纪律

- 上游文件以最小 diff 合并；本 fork 对 lib/ 的定制必须能被 `git merge upstream/master`
  干净重放。凡可放 `custom/` 或独立插件解决的问题，不改 lib。
- 中文只出现在注释性说明会破坏上游英文注释约定：lib 与 oh-my-zsh.sh 保持英文注释、
  `#` 行注释、解释 why 而非 what。
- 验证：`bash scripts/check_syntax.sh`（zsh -n 全量）+ `zsh tests/smoke_load.zsh`
  （隔离 ZDOTDIR/HOME 加载断言）。改加载顺序必须补 smoke 断言后再改。
