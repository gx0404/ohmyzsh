local wezterm = require('wezterm')
local tab_title = require('events.tab-title')

local M = {}
local last_status_by_window = {}
-- herdr 应用模式：per-window 记录「当前是否已隐藏 tab bar」与隐藏前的
-- enable_tab_bar 原值，只在该状态发生翻转时才调用 set_config_overrides
-- （见 apply_herdr_app_mode）。
local herdr_tab_bar_state_by_window = {}

local colors = {
   surface = '#181825',
   text = '#cdd6f4',
   blue = '#89b4fa',
   peach = '#fab387',
   yellow = '#f9e2af',
   mauve = '#cba6f7',
}

local function segment(icon, text, color)
   return {
      { Background = { Color = colors.surface } },
      { Foreground = { Color = color } },
      { Attribute = { Intensity = 'Bold' } },
      { Text = string.format(' %s %s ', icon, text) },
   }
end

local function battery_segment()
   for _, battery in ipairs(wezterm.battery_info()) do
      local percent = math.floor(battery.state_of_charge * 100 + 0.5)
      local icon = battery.state == 'Charging' and wezterm.nerdfonts.md_battery_charging
         or wezterm.nerdfonts.md_battery
      return segment(icon, string.format('%d%%', percent), colors.yellow)
   end
   return {}
end

local function render_status(window, date_format)
   local left = {}
   local workspace = window:active_workspace()
   local key_table = window:active_key_table()

   for _, item in ipairs(segment(wezterm.nerdfonts.cod_terminal, workspace, colors.blue)) do
      table.insert(left, item)
   end

   if key_table then
      for _, item in ipairs(segment(wezterm.nerdfonts.md_table_key, string.upper(key_table), colors.mauve)) do
         table.insert(left, item)
      end
   elseif window:leader_is_active() then
      for _, item in ipairs(segment(wezterm.nerdfonts.md_key, 'LEADER', colors.mauve)) do
         table.insert(left, item)
      end
   end

   local right = battery_segment()
   for _, item in ipairs(segment(wezterm.nerdfonts.fa_clock_o, wezterm.strftime(date_format), colors.peach)) do
      table.insert(right, item)
   end

   return wezterm.format(left), wezterm.format(right)
end

---herdr 应用模式：是否应该隐藏宿主 tab bar。纯函数，不读取/修改任何
---window 或全局状态，只依据显式入参判断，可脱离 wezterm 运行时单独测试
---（见 tests/pure_fn_test.lua）。
---@param herdr_app_mode boolean
---@param tab_count number
---@param process_name string 已经过 clean_process_name 清洗的前台进程名
---@return boolean
local function should_hide_tab_bar(herdr_app_mode, tab_count, process_name)
   return herdr_app_mode == true and tab_count == 1 and process_name == 'herdr'
end

---按 herdr 应用模式決定是否隐藏 tab bar；只在「是否应隐藏」这一判定发生
---翻转时才调用 set_config_overrides，避免每次 update-status（2s）轮询都
---重设一次。翻转之间（判定不变）不覆盖，因此手动 `tabs.toggle-tab-bar`
---切出的状态会一直保留，直到前台进程/tab 数量变化触发下一次翻转。
---@param window any WezTerm GuiWindow
---@param pane any? WezTerm Pane，可能为 nil（窗口刚创建等边界情况）
---@param herdr_app_mode boolean
local function apply_herdr_app_mode(window, pane, herdr_app_mode)
   local window_id = window:window_id()
   local tab_count = #window:mux_window():tabs()
   local process_name = ''
   if pane then
      process_name = tab_title.clean_process_name(pane:get_foreground_process_name() or '')
   end

   local hide = should_hide_tab_bar(herdr_app_mode, tab_count, process_name)
   local state = herdr_tab_bar_state_by_window[window_id]
   local was_hidden = (state and state.hidden) or false

   if was_hidden == hide then
      herdr_tab_bar_state_by_window[window_id] = state or { hidden = false }
      return
   end

   local effective_config = window:effective_config()
   if hide then
      herdr_tab_bar_state_by_window[window_id] =
         { hidden = true, restore_value = effective_config.enable_tab_bar }
      window:set_config_overrides({ enable_tab_bar = false, background = effective_config.background })
   else
      local restore_value = state and state.restore_value
      if restore_value == nil then
         restore_value = true
      end
      herdr_tab_bar_state_by_window[window_id] = { hidden = false }
      window:set_config_overrides({ enable_tab_bar = restore_value, background = effective_config.background })
   end
end

---@param opts? { date_format?: string, herdr_app_mode?: boolean } Default: {date_format = '%a %H:%M', herdr_app_mode = true}
M.setup = function(opts)
   local date_format = (opts and opts.date_format) or '%a %H:%M'
   local herdr_app_mode = true
   if opts and opts.herdr_app_mode ~= nil then
      herdr_app_mode = opts.herdr_app_mode
   end

   wezterm.on('update-status', function(window, pane)
      local left, right = render_status(window, date_format)
      local window_id = window:window_id()
      local previous = last_status_by_window[window_id]

      if not previous or previous.left ~= left then
         window:set_left_status(left)
      end
      if not previous or previous.right ~= right then
         window:set_right_status(right)
      end

      last_status_by_window[window_id] = { left = left, right = right }

      apply_herdr_app_mode(window, pane, herdr_app_mode)
   end)
end

-- 导出：供 tests/pure_fn_test.lua 单独驱动断言，无需起 GUI 窗口。
M.should_hide_tab_bar = should_hide_tab_bar

return M
