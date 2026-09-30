-- 纯函数用例：herdr 应用模式判定与状态转移 + tab 标题进程名清洗 + Config 字段守门
-- + 启动菜单不起子进程 + Windows/Linux 键位一致。
--
-- 仓库没有 lua5.4/busted 等独立解释器（机器上只装了 liblua 库，没有 CLI），
-- 这里借用 wezterm 自带的 mlua 运行时当解释器：wezterm --config-file 会把
-- 该文件当配置执行，执行到 error() 时会静默回退默认配置、不产生任何可见
-- 诊断（已用探针验证），所以断言结果一律用 print 显式输出，不依赖异常/
-- 退出码。跑法：
--
--   wezterm --config-file tests/pure_fn_test.lua show-keys 2>&1 | grep PURE_FN_TEST
--
-- 全部通过时最后一行是 `PURE_FN_TEST: ALL PASS (n cases)`；任何一条失败会
-- 单独打印 `PURE_FN_TEST FAIL: <case> ...`。

local wezterm = require('wezterm')
-- wezterm.config_dir 是 --config-file 指向文件所在目录，即 tests/；回退一级
-- 拼出 wezterm-config 根目录，与调用时的进程 cwd 无关（wezterm 沙箱化的
-- Lua 环境没有 debug 库，不能用 debug.getinfo 自行定位脚本路径）。
local config_root = wezterm.config_dir .. '/..'
package.path = config_root .. '/?.lua;' .. config_root .. '/?/init.lua;' .. package.path

local status = require('events.status')
local tab_title = require('events.tab-title')

local failures = 0
local total = 0

---@param name string
---@param actual any
---@param expected any
local function check(name, actual, expected)
   total = total + 1
   if actual ~= expected then
      failures = failures + 1
      print(string.format('PURE_FN_TEST FAIL: %s (got %s, want %s)', name, tostring(actual), tostring(expected)))
   end
end

-- should_hide_tab_bar：herdr_app_mode / tab 数量 / 前台进程名 三个入参的判定表
check('hide.single_tab_herdr', status.should_hide_tab_bar(true, 1, 'herdr'), true)
check('hide.multi_tab_herdr', status.should_hide_tab_bar(true, 2, 'herdr'), false)
check('hide.single_tab_other_process', status.should_hide_tab_bar(true, 1, 'bash'), false)
check('hide.app_mode_disabled', status.should_hide_tab_bar(false, 1, 'herdr'), false)
check('hide.empty_process_name', status.should_hide_tab_bar(true, 1, ''), false)
check('hide.uncleaned_process_name', status.should_hide_tab_bar(true, 1, 'herdr.exe'), false)
check('hide.zero_tabs', status.should_hide_tab_bar(true, 0, 'herdr'), false)

-- next_tab_bar_state：herdr 应用模式的 tab bar 状态转移（纯函数）
do
   local next_state = status.next_tab_bar_state

   -- 新窗口首次见到且不需隐藏：记录状态，不写 overrides
   local st, ov = next_state(nil, false, nil)
   check('state.first_seen_visible.hidden', st.hidden, false)
   check('state.first_seen_visible.no_write', ov, nil)

   -- 新窗口启动 herdr：只写 enable_tab_bar=false，不引入 background 等其他键
   st, ov = next_state(nil, true, nil)
   check('state.hide.hidden', st.hidden, true)
   check('state.hide.had_prev', st.had_prev, false)
   check('state.hide.enable_tab_bar', ov and ov.enable_tab_bar, false)
   check('state.hide.no_background', ov and ov.background, nil)

   -- 重载后状态丢失（或部署前旧实现遗留的 false 覆盖）：按原值 nil 记录，
   -- 退出 herdr 时删掉 enable_tab_bar 回落 base，其余覆盖键原样保留
   local legacy = { enable_tab_bar = false, background = 'wallpaper-sentinel' }
   st, ov = next_state(nil, true, legacy)
   check('state.legacy.had_prev', st.had_prev, false)
   check('state.legacy.input_untouched', legacy.enable_tab_bar, false)
   st, ov = next_state(st, false, ov)
   check('state.legacy.restore.hidden', st.hidden, false)
   check('state.legacy.restore.enable_tab_bar_removed', ov and ov.enable_tab_bar, nil)
   check('state.legacy.restore.keeps_other_keys', ov and ov.background, 'wallpaper-sentinel')

   -- 手动切换后判定不变：不改写（原样返回 state，overrides 为 nil）
   local hidden_state = { hidden = true, had_prev = false }
   st, ov = next_state(hidden_state, true, { enable_tab_bar = true })
   check('state.manual_toggle.same_state', st, hidden_state)
   check('state.manual_toggle.no_write', ov, nil)

   -- 多 tab 时恢复显示（判定由 should_hide_tab_bar 给出）
   local multi_tab_hide = status.should_hide_tab_bar(true, 2, 'herdr')
   st, ov = next_state(hidden_state, multi_tab_hide, { enable_tab_bar = false })
   check('state.multi_tab.hidden', st.hidden, false)
   check('state.multi_tab.enable_tab_bar_removed', ov and ov.enable_tab_bar, nil)

   -- 启动 herdr 前已手动隐藏（覆盖 false）：退出后还原为手动值 false
   st, ov = next_state({ hidden = false, had_prev = false }, true, { enable_tab_bar = false })
   check('state.prev_false.had_prev', st.had_prev, true)
   check('state.prev_false.prev', st.prev, false)
   st, ov = next_state(st, false, ov)
   check('state.prev_false.restore', ov and ov.enable_tab_bar, false)

   -- 启动 herdr 前手动显示（覆盖 true）：退出后还原为 true
   st, ov = next_state({ hidden = false, had_prev = false }, true, { enable_tab_bar = true })
   st, ov = next_state(st, false, ov)
   check('state.prev_true.restore', ov and ov.enable_tab_bar, true)
end

-- apply_herdr_app_mode 端到端：假 window/pane 驱动，状态走真实 wezterm.GLOBAL；
-- 清掉 package.loaded 重新 require 模拟配置重载（模块局部状态丢失、GLOBAL 保留）。
do
   local function fake_window(id)
      local window = { id = id, overrides = nil, writes = 0, tab_count = 1 }
      function window:window_id()
         return self.id
      end
      function window:mux_window()
         local tabs = {}
         for i = 1, self.tab_count do
            tabs[i] = i
         end
         return {
            tabs = function()
               return tabs
            end,
         }
      end
      function window:get_config_overrides()
         if self.overrides == nil then
            return nil
         end
         local copy = {}
         for k, v in pairs(self.overrides) do
            copy[k] = v
         end
         return copy
      end
      function window:set_config_overrides(value)
         self.overrides = value
         self.writes = self.writes + 1
      end
      return window
   end

   local function fake_pane(process)
      return {
         get_foreground_process_name = function()
            return process
         end,
      }
   end

   local function tab_bar_override(window)
      return window.overrides and window.overrides.enable_tab_bar
   end

   local function reload_status()
      package.loaded['events.status'] = nil
      return require('events.status')
   end

   -- 每次调用推进 10 秒，越过前台进程探测的 2 秒节流
   local clock = 0
   local function later()
      clock = clock + 10
      return clock
   end

   -- 取测试进程内不会与真实窗口冲突的大 id
   local window = fake_window(900001)
   local herdr = fake_pane('/usr/local/bin/herdr')
   local shell = fake_pane('/usr/bin/zsh')

   status.apply_herdr_app_mode(window, shell, true, later())
   check('apply.visible_no_write', window.writes, 0)

   status.apply_herdr_app_mode(window, herdr, true, later())
   check('apply.hide.writes', window.writes, 1)
   check('apply.hide.enable_tab_bar', tab_bar_override(window), false)
   check('apply.hide.no_background', window.overrides and window.overrides.background, nil)

   status.apply_herdr_app_mode(window, herdr, true, later())
   check('apply.steady_no_rewrite', window.writes, 1)

   local reloaded = reload_status()
   check('apply.reload.fresh_module', reloaded ~= status, true)
   reloaded.apply_herdr_app_mode(window, herdr, true, later())
   check('apply.reload.no_rewrite', window.writes, 1)

   reloaded.apply_herdr_app_mode(window, shell, true, later())
   check('apply.reload.restore.writes', window.writes, 2)
   check('apply.reload.restore.enable_tab_bar', tab_bar_override(window), nil)

   -- 手动隐藏后启动 herdr，中途重载，再退出：GLOBAL 里的 prev=false 生效
   -- （也覆盖 false 值经 GLOBAL 往返不被读成 nil）
   local manual = fake_window(900002)
   manual.overrides = { enable_tab_bar = false }
   reloaded.apply_herdr_app_mode(manual, shell, true, later())
   reloaded.apply_herdr_app_mode(manual, herdr, true, later())
   reloaded = reload_status()
   reloaded.apply_herdr_app_mode(manual, shell, true, later())
   check('apply.manual_prev_false.restore', tab_bar_override(manual), false)

   -- 同上但手动值为 true：能区分「按 GLOBAL 记录还原」与「重载丢状态后卡在 false」
   local manual_shown = fake_window(900004)
   manual_shown.overrides = { enable_tab_bar = true }
   reloaded.apply_herdr_app_mode(manual_shown, shell, true, later())
   reloaded.apply_herdr_app_mode(manual_shown, herdr, true, later())
   check('apply.manual_prev_true.hidden', tab_bar_override(manual_shown), false)
   reloaded = reload_status()
   reloaded.apply_herdr_app_mode(manual_shown, shell, true, later())
   check('apply.manual_prev_true.restore', tab_bar_override(manual_shown), true)

   -- 多 tab：隐藏后开第二个 tab 即恢复
   local multi = fake_window(900003)
   reloaded.apply_herdr_app_mode(multi, herdr, true, later())
   multi.tab_count = 2
   reloaded.apply_herdr_app_mode(multi, herdr, true, later())
   check('apply.multi_tab.restore', tab_bar_override(multi), nil)
   check('apply.multi_tab.writes', multi.writes, 2)

   -- 前台进程探测：同一窗口 2 秒内复用结果，多 tab 或关闭应用模式时不探测
   local probes = 0
   local counting = {
      get_foreground_process_name = function()
         probes = probes + 1
         return '/usr/local/bin/herdr'
      end,
   }
   local throttled = fake_window(900005)
   reloaded.apply_herdr_app_mode(throttled, counting, true, 1000)
   reloaded.apply_herdr_app_mode(throttled, counting, true, 1001)
   check('probe.throttled', probes, 1)
   check('probe.throttled.hidden', tab_bar_override(throttled), false)
   reloaded.apply_herdr_app_mode(throttled, counting, true, 1002)
   check('probe.after_interval', probes, 2)
   throttled.tab_count = 2
   reloaded.apply_herdr_app_mode(throttled, counting, true, 1010)
   check('probe.skipped_multi_tab', probes, 2)
   check('probe.multi_tab.restore', tab_bar_override(throttled), nil)
   throttled.tab_count = 1
   reloaded.apply_herdr_app_mode(throttled, counting, false, 1020)
   check('probe.skipped_app_mode_off', probes, 2)
   -- 时钟往回拨（上次探测记在 1002）：按过期处理，重新探测
   reloaded.apply_herdr_app_mode(throttled, counting, true, 990)
   check('probe.clock_stepped_back', probes, 3)
end

-- update-status：battery_info 在缓存期内只查一次
do
   local battery_calls = 0
   local real_battery_info, real_on = wezterm.battery_info, wezterm.on
   local handler = nil
   wezterm.battery_info = function()
      battery_calls = battery_calls + 1
      return { { state_of_charge = 0.5, state = 'Charging' } }
   end
   wezterm.on = function(name, callback)
      if name == 'update-status' then
         handler = callback
      end
   end
   package.loaded['events.status'] = nil
   require('events.status').setup({ herdr_app_mode = false })
   wezterm.on = real_on

   local window = {}
   function window:active_workspace()
      return 'default'
   end
   function window:active_key_table()
      return nil
   end
   function window:leader_is_active()
      return false
   end
   function window:window_id()
      return 900010
   end
   function window:mux_window()
      return {
         tabs = function()
            return { 1 }
         end,
      }
   end
   function window:set_left_status(_) end
   function window:set_right_status(value)
      self.right = value
   end
   handler(window, nil)
   handler(window, nil)
   wezterm.battery_info = real_battery_info
   check('battery.cached', battery_calls, 1)
   check('battery.rendered', window.right ~= nil and window.right:find('50%%') ~= nil, true)
end

-- clean_process_name（来自 events/tab-title.lua，herdr 应用模式判断复用同一口径）
check('clean.unix_path', tab_title.clean_process_name('/usr/bin/herdr'), 'herdr')
check('clean.windows_path_exe', tab_title.clean_process_name('C:\\Users\\x\\herdr.exe'), 'herdr')
check('clean.bare_name', tab_title.clean_process_name('herdr'), 'herdr')
check('clean.empty', tab_title.clean_process_name(''), '')

-- toggled_tab_bar_overrides（events/tab-title.lua 手动切换 tab bar）
do
   local toggled = tab_title.toggled_tab_bar_overrides
   local input = { background = 'wallpaper-sentinel', enable_tab_bar = false }
   local out = toggled(input, false)
   check('toggle.show', out.enable_tab_bar, true)
   check('toggle.keeps_other_keys', out.background, 'wallpaper-sentinel')
   check('toggle.input_untouched', input.enable_tab_bar, false)
   out = toggled(nil, true)
   check('toggle.hide_from_nil', out.enable_tab_bar, false)
   check('toggle.no_background', out.background, nil)
end

-- GX Shell 安装包内置 shell 探测（utils/gx-shell.lua）
do
   local gx_shell = require('utils.gx-shell')
   local win_dir = 'C:\\Users\\x\\AppData\\Local\\Programs\\GXShell\\wezterm'
   local win_root = 'C:\\Users\\x\\AppData\\Local\\Programs\\GXShell'
   check('gx.root.windows', gx_shell.install_root(win_dir), win_root)
   check('gx.root.trailing_separator', gx_shell.install_root(win_dir .. '\\'), win_root)
   check('gx.root.linux', gx_shell.install_root('/usr/lib/wezterm-gx'), '/usr/lib')
   check('gx.root.no_parent', gx_shell.install_root('wezterm'), nil)
   check('gx.root.nil', gx_shell.install_root(nil), nil)

   local present = {}
   local function exists(path)
      return present[path] == true
   end
   check('gx.detect.standalone_windows', gx_shell.detect(win_dir, true, exists), nil)
   present[win_root .. '\\bin\\gx-zsh.exe'] = true
   check('gx.detect.needs_herdr_too', gx_shell.detect(win_dir, true, exists), nil)
   present[win_root .. '\\bin\\herdr.exe'] = true
   local entries = gx_shell.detect(win_dir, true, exists)
   check('gx.detect.windows.gx_zsh', entries and entries.gx_zsh, win_root .. '\\bin\\gx-zsh.exe')
   check('gx.detect.windows.herdr', entries and entries.herdr, win_root .. '\\bin\\herdr.exe')

   present['/usr/lib/ohmyzsh-gx/bin/gx-zsh'] = true
   present['/usr/lib/ohmyzsh-gx/bin/herdr'] = true
   entries = gx_shell.detect('/usr/lib/wezterm-gx', false, exists)
   check('gx.detect.deb.gx_zsh', entries and entries.gx_zsh, '/usr/lib/ohmyzsh-gx/bin/gx-zsh')
   check('gx.detect.deb.herdr', entries and entries.herdr, '/usr/lib/ohmyzsh-gx/bin/herdr')
   check('gx.detect.dev_build', gx_shell.detect('/src/wezterm/target/release', false, exists), nil)
end

-- 启动菜单（config/launch.lua）在 require 里求值：不能起子进程，每项固定 domain，
-- 除 herdr 外都带 GX_SHELL_ID；WSL 列表（utils/wsl.lua）在重试间隔内只取一次。
do
   local spawned, wsl_calls = 0, 0
   local real_run, real_background = wezterm.run_child_process, wezterm.background_child_process
   local real_wsl = wezterm.default_wsl_domains
   wezterm.run_child_process = function()
      spawned = spawned + 1
      return false, '', ''
   end
   wezterm.background_child_process = function()
      spawned = spawned + 1
   end
   wezterm.default_wsl_domains = function()
      wsl_calls = wsl_calls + 1
      return {}
   end
   wezterm.GLOBAL.gx_wsl = nil
   local loaded, launch
   for _ = 1, 2 do
      package.loaded['config.domains'] = nil
      package.loaded['config.launch'] = nil
      loaded, launch = pcall(require, 'config.launch')
   end
   wezterm.run_child_process, wezterm.background_child_process = real_run, real_background
   wezterm.default_wsl_domains = real_wsl

   check('launch.loads', loaded, true)
   check('launch.no_child_process', spawned, 0)
   check('launch.wsl_listed_once', wsl_calls, require('utils.platform').is_win and 1 or 0)
   check('domains.always_table', type(require('config.domains').wsl_domains), 'table')
   if loaded then
      check('launch.has_entries', #launch.launch_menu > 0, true)
      for idx, entry in ipairs(launch.launch_menu) do
         check('launch.domain.' .. idx, type(entry.domain) == 'table' and type(entry.domain.DomainName), 'string')
         local tagged = entry.set_environment_variables ~= nil and entry.set_environment_variables.GX_SHELL_ID ~= nil
         check('launch.tag.' .. idx, tagged, entry.label ~= 'herdr')
      end
      check('launch.default_marked', require('utils.shells').default_index(launch) ~= nil, true)
   end
end

-- 插件目录名与 lua-api-crates/plugin 的 compute_repo_dir 一致（含其 Rust 测试向量）。
do
   local plugins = require('config.plugins')
   check('plugin_dir.plain', plugins.compute_repo_dir('foo'), 'foo')
   check(
      'plugin_dir.path',
      plugins.compute_repo_dir('githubsDscom/wezterm/wezterm-plugins'),
      'githubsDscomsZsweztermsZswezterm-plugins'
   )
   check('plugin_dir.port', plugins.compute_repo_dir('localhost:8080/repo'), 'localhostsCs8080sZsrepo')
   check(
      'plugin_dir.trailing_slash',
      plugins.compute_repo_dir('https://github.com/a/b/'),
      'httpssCssZssZsgithubsDscomsZsasZsb'
   )
   check('plugin_dir.other', plugins.compute_repo_dir('a b'), 'au32b')
   check(
      'plugin_dir.resurrect',
      plugins.compute_repo_dir('https://github.com/MLFlexer/resurrect.wezterm'),
      'httpssCssZssZsgithubsDscomsZsMLFlexersZsresurrectsDswezterm'
   )
end

-- 新标签按钮右键列表：launch_menu 各项按自己的 domain 启动，默认 Shell 标注一次，
-- 末项打开设置页的默认 Shell 分区。
do
   package.loaded['events.new-tab-button'] = nil
   local loaded, new_tab = pcall(require, 'events.new-tab-button')
   check('new_tab.loads', loaded, true)
   if loaded then
      local choices, choices_data = new_tab.build_choices({}, {})
      local marked = 0
      for _, choice in ipairs(choices) do
         if choice.label:find('（默认）', 1, true) then
            marked = marked + 1
         end
      end
      check('new_tab.default_marked_once', marked, 1)
      check('new_tab.settings_last', choices[#choices].id, 'open-settings')
      check('new_tab.settings_label', choices[#choices].label:find('设为默认 Shell…', 1, true) ~= nil, true)
      check('new_tab.entries', #choices_data, #require('config.launch').launch_menu)
      for idx, data in ipairs(choices_data) do
         check('new_tab.domain.' .. idx, type(data.domain), 'table')
      end
   end
   -- 末项用的按键动作要随 WezTerm GX 本体一起发布（0.2.0 新增）；旧二进制上这一项会失败。
   check('new_tab.settings_action_known', pcall(function()
      return wezterm.action.ShowDefaultShellSettings
   end), true)
end

-- gui-settings.json 与 Rust（config/src/gui_settings.rs::settings_file_in_dir）同一位置：
-- 配置目录不是 HOME 时在它旁边，~/.wezterm.lua 时退回 XDG 配置目录。
do
   local gui_settings = require('utils.gui-settings')
   check(
      'settings.next_to_config',
      gui_settings.path(wezterm.config_dir, wezterm.home_dir, os.getenv),
      wezterm.config_dir .. '/gui-settings.json'
   )
   local function no_env()
      return nil
   end
   check(
      'settings.home_config',
      gui_settings.path(wezterm.home_dir, wezterm.home_dir, no_env),
      wezterm.home_dir .. '/.config/wezterm/gui-settings.json'
   )
end

-- Windows 免确认关闭名单：保留上游默认项，补上带 .exe 的 shell；herdr 仍需确认。
do
   local function load_general(os_name)
      local saved = package.loaded['utils.platform']
      package.loaded['utils.platform'] = { os = os_name, is_win = os_name == 'windows', is_linux = os_name == 'linux' }
      package.loaded['config.general'] = nil
      local general = require('config.general')
      package.loaded['config.general'] = nil
      package.loaded['utils.platform'] = saved
      return general
   end
   local names = {}
   for _, name in ipairs(load_general('windows').skip_close_confirmation_for_processes_named or {}) do
      names[name] = true
   end
   local expected = {
      'bash', 'sh', 'zsh', 'fish', 'tmux', 'nu', 'nu.exe', 'cmd.exe', 'pwsh.exe', 'powershell.exe',
      'zsh.exe', 'bash.exe', 'sh.exe', 'fish.exe', 'gx-zsh.exe', 'env.exe',
      -- GX Zsh 的 Powerlevel10k 在 zsh 下常驻（安装包 lib/gitstatus 里的文件名，无扩展名）
      'gitstatusd-msys_nt-10.0-x86_64',
   }
   for _, name in ipairs(expected) do
      check('skip_close.windows.' .. name, names[name], true)
   end
   check('skip_close.windows.herdr', names['herdr.exe'], nil)
   check('skip_close.linux_upstream_default', load_general('linux').skip_close_confirmation_for_processes_named, nil)
end

-- 键位：Windows 与 Linux 同一套（除 Linux 专属的截图/AI 图片粘贴），不占裸 Alt，
-- 不绑 Ctrl+B/C/V，翻页要 Shift。
do
   local function load_bindings(os_name)
      local saved_platform, saved_plugins = package.loaded['utils.platform'], package.loaded['config.plugins']
      package.loaded['utils.platform'] = {
         os = os_name,
         is_win = os_name == 'windows',
         is_linux = os_name == 'linux',
         is_mac = os_name == 'mac',
      }
      package.loaded['config.plugins'] = {
         resurrect_available = true,
         resurrect = function()
            return nil
         end,
      }
      package.loaded['config.bindings'] = nil
      local loaded, bindings = pcall(require, 'config.bindings')
      package.loaded['config.bindings'] = nil
      package.loaded['utils.platform'] = saved_platform
      package.loaded['config.plugins'] = saved_plugins
      check('bindings.load.' .. os_name, loaded, true)
      return loaded and bindings or { keys = {} }
   end

   local function normalized_mods(mods)
      local parts = {}
      for part in (mods or 'NONE'):gmatch('[^|%s]+') do
         table.insert(parts, part)
      end
      table.sort(parts)
      return table.concat(parts, '|')
   end

   local function index(bindings, os_name)
      local set = {}
      for _, binding in ipairs(bindings.keys) do
         local id = binding.key .. ' ' .. normalized_mods(binding.mods)
         check('bindings.unique.' .. os_name .. '.' .. id, set[id], nil)
         set[id] = binding
      end
      return set
   end

   local linux_only = { ['S ALT|SHIFT'] = true, ['V ALT|SHIFT'] = true }
   local sets = {}
   for _, os_name in ipairs({ 'windows', 'linux' }) do
      local set = index(load_bindings(os_name), os_name)
      sets[os_name] = set
      for id, binding in pairs(set) do
         local mods = normalized_mods(binding.mods)
         if mods == 'ALT' or mods == 'ALT|SHIFT' then
            check('bindings.bare_alt.' .. os_name .. '.' .. id, os_name == 'linux' and linux_only[id], true)
         end
         if mods == 'CTRL' then
            local key = binding.key:lower()
            check('bindings.ctrl_' .. key .. '.' .. os_name, key == 'b' or key == 'c' or key == 'v', false)
         end
      end
      check('bindings.page_up_shift.' .. os_name, set['PageUp SHIFT'] ~= nil, true)
      check('bindings.page_down_shift.' .. os_name, set['PageDown SHIFT'] ~= nil, true)
      check('bindings.page_up_plain.' .. os_name, set['PageUp NONE'], nil)
      check('bindings.page_down_plain.' .. os_name, set['PageDown NONE'], nil)
      local close_pane = set['w CTRL|SHIFT']
      check('bindings.close_pane.' .. os_name, close_pane and close_pane.action.CloseCurrentPane.confirm, true)
      local close_tab = set['w ALT|CTRL|SHIFT']
      check('bindings.close_tab.' .. os_name, close_tab and close_tab.action.CloseCurrentTab.confirm, true)
      local shifted = { '{', '}', '|', ')', '(' }
      for _, key in ipairs(shifted) do
         check('bindings.shifted.' .. os_name .. '.' .. key, set[key .. ' CTRL|SHIFT'] ~= nil, true)
      end
      check('bindings.shifted_rev.' .. os_name, set['{ ALT|CTRL|SHIFT'] ~= nil, true)
      -- Ctrl+_（Ctrl+Shift+-）是 readline/zsh/emacs/nano 的撤销，必须交给应用；
      -- Ctrl++（Ctrl+Shift+=）是字号放大；窗口缩放挂 leader 层。
      for _, id in ipairs({ '_ CTRL|SHIFT', '- CTRL|SHIFT', '= CTRL|SHIFT' }) do
         check('bindings.free.' .. os_name .. '.' .. id, set[id], nil)
      end
      local ctrl_plus = set['+ CTRL|SHIFT']
      check('bindings.ctrl_plus.' .. os_name, ctrl_plus and ctrl_plus.action, 'IncreaseFontSize')
      check('bindings.window_shrink.' .. os_name, set['- LEADER'] ~= nil, true)
      check('bindings.window_grow.' .. os_name, set['= LEADER'] ~= nil, true)
      for index_key = 1, 9 do
         check('bindings.leader_tab.' .. os_name .. '.' .. index_key, set[index_key .. ' LEADER'] ~= nil, true)
      end
      check('bindings.ctrl_page_up.' .. os_name, set['PageUp CTRL'] ~= nil, true)
      check('bindings.font_reset.' .. os_name, set['0 CTRL'] ~= nil, true)
   end
   for id in pairs(sets.linux) do
      check('bindings.windows_has.' .. id, sets.windows[id] ~= nil or linux_only[id] == true, true)
   end
   for id in pairs(sets.windows) do
      check('bindings.linux_has.' .. id, sets.linux[id] ~= nil, true)
   end

   local mac = index(load_bindings('mac'), 'mac')
   check('bindings.mac.close_pane', mac['w SUPER'] ~= nil, true)
   check('bindings.mac.page_up', mac['PageUp NONE'] ~= nil, true)
   check('bindings.mac.line_start', mac['LeftArrow SUPER'] ~= nil, true)
   check('bindings.mac.window_grow', mac['= LEADER'] ~= nil, true)
end

-- 防回归：wezterm.lua 里 append 进 Config 的每个模块，每个键都必须是合法的
-- wezterm Config 字段。纯表配置按 unknown_fields=Warn 转换，未知键不会报错，
-- 只会在下次 wezterm-gui 启动时弹 Configuration Error 窗口；这里借严格模式的
-- config_builder() 逐键赋值，未知键会被拒绝。模块清单直接从 wezterm.lua 的
-- `:append(require('...'))` 解析，新增模块自动纳入。
local function appended_config_modules()
   local file = io.open(config_root .. '/wezterm.lua', 'r')
   if not file then
      return {}
   end
   local source = file:read('a')
   file:close()
   local modules = {}
   for name in source:gmatch(":append%(%s*require%(%s*'([%w%._%-]+)'%s*%)%s*%)") do
      table.insert(modules, name)
   end
   return modules
end

local config_modules = appended_config_modules()
check('config_keys.modules_found', #config_modules > 0, true)
for _, module_name in ipairs(config_modules) do
   local loaded, options = pcall(require, module_name)
   check('config_keys.load.' .. module_name, loaded, true)
   if loaded and type(options) == 'table' then
      local builder = wezterm.config_builder()
      for key, value in pairs(options) do
         local accepted = pcall(function()
            builder[key] = value
         end)
         check('config_keys.' .. module_name .. '.' .. tostring(key), accepted, true)
      end
   end
end

-- resurrect 只在会话保存/恢复键触发时加载（加载会用 git 打开全部插件仓库）。
check('plugins.resurrect_lazy', package.loaded['httpssCssZssZsgithubsDscomsZsMLFlexersZsresurrectsDswezterm'], nil)

if failures == 0 then
   print(string.format('PURE_FN_TEST: ALL PASS (%d cases)', total))
else
   print(string.format('PURE_FN_TEST: %d/%d FAILED', failures, total))
end

-- 保持这是一个能被 --config-file 加载的合法配置返回值。
return {}
