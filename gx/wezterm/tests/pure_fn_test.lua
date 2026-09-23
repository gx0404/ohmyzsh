-- 纯函数用例：herdr 应用模式判定与状态转移 + tab 标题进程名清洗 + Config 字段守门。
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

   -- 取测试进程内不会与真实窗口冲突的大 id
   local window = fake_window(900001)
   local herdr = fake_pane('/usr/local/bin/herdr')
   local shell = fake_pane('/usr/bin/zsh')

   status.apply_herdr_app_mode(window, shell, true)
   check('apply.visible_no_write', window.writes, 0)

   status.apply_herdr_app_mode(window, herdr, true)
   check('apply.hide.writes', window.writes, 1)
   check('apply.hide.enable_tab_bar', tab_bar_override(window), false)
   check('apply.hide.no_background', window.overrides and window.overrides.background, nil)

   status.apply_herdr_app_mode(window, herdr, true)
   check('apply.steady_no_rewrite', window.writes, 1)

   local reloaded = reload_status()
   check('apply.reload.fresh_module', reloaded ~= status, true)
   reloaded.apply_herdr_app_mode(window, herdr, true)
   check('apply.reload.no_rewrite', window.writes, 1)

   reloaded.apply_herdr_app_mode(window, shell, true)
   check('apply.reload.restore.writes', window.writes, 2)
   check('apply.reload.restore.enable_tab_bar', tab_bar_override(window), nil)

   -- 手动隐藏后启动 herdr，中途重载，再退出：GLOBAL 里的 prev=false 生效
   -- （也覆盖 false 值经 GLOBAL 往返不被读成 nil）
   local manual = fake_window(900002)
   manual.overrides = { enable_tab_bar = false }
   reloaded.apply_herdr_app_mode(manual, shell, true)
   reloaded.apply_herdr_app_mode(manual, herdr, true)
   reloaded = reload_status()
   reloaded.apply_herdr_app_mode(manual, shell, true)
   check('apply.manual_prev_false.restore', tab_bar_override(manual), false)

   -- 同上但手动值为 true：能区分「按 GLOBAL 记录还原」与「重载丢状态后卡在 false」
   local manual_shown = fake_window(900004)
   manual_shown.overrides = { enable_tab_bar = true }
   reloaded.apply_herdr_app_mode(manual_shown, shell, true)
   reloaded.apply_herdr_app_mode(manual_shown, herdr, true)
   check('apply.manual_prev_true.hidden', tab_bar_override(manual_shown), false)
   reloaded = reload_status()
   reloaded.apply_herdr_app_mode(manual_shown, shell, true)
   check('apply.manual_prev_true.restore', tab_bar_override(manual_shown), true)

   -- 多 tab：隐藏后开第二个 tab 即恢复
   local multi = fake_window(900003)
   reloaded.apply_herdr_app_mode(multi, herdr, true)
   multi.tab_count = 2
   reloaded.apply_herdr_app_mode(multi, herdr, true)
   check('apply.multi_tab.restore', tab_bar_override(multi), nil)
   check('apply.multi_tab.writes', multi.writes, 2)
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

if failures == 0 then
   print(string.format('PURE_FN_TEST: ALL PASS (%d cases)', total))
else
   print(string.format('PURE_FN_TEST: %d/%d FAILED', failures, total))
end

-- 保持这是一个能被 --config-file 加载的合法配置返回值。
return {}
