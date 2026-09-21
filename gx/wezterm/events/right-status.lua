local wezterm = require('wezterm')
local umath = require('utils.math')
local Cells = require('utils.cells')
local OptsValidator = require('utils.opts-validator')

---@alias Event.RightStatusOptions { date_format?: string }

---Setup options for the right status bar
local EVENT_OPTS = {}

---@type OptsSchema
EVENT_OPTS.schema = {
   {
      name = 'date_format',
      type = 'string',
      default = '%a %H:%M:%S',
   },
}
EVENT_OPTS.validator = OptsValidator:new(EVENT_OPTS.schema)

local nf = wezterm.nerdfonts
local attr = Cells.attr

local M = {}

local ICON_SEPARATOR = nf.oct_dash
local ICON_DATE = nf.fa_calendar

---@type string[]
local discharging_icons = {
   nf.md_battery_10,
   nf.md_battery_20,
   nf.md_battery_30,
   nf.md_battery_40,
   nf.md_battery_50,
   nf.md_battery_60,
   nf.md_battery_70,
   nf.md_battery_80,
   nf.md_battery_90,
   nf.md_battery,
}
---@type string[]
local charging_icons = {
   nf.md_battery_charging_10,
   nf.md_battery_charging_20,
   nf.md_battery_charging_30,
   nf.md_battery_charging_40,
   nf.md_battery_charging_50,
   nf.md_battery_charging_60,
   nf.md_battery_charging_70,
   nf.md_battery_charging_80,
   nf.md_battery_charging_90,
   nf.md_battery_charging,
}

---@type table<string, Cells.SegmentColors>
-- stylua: ignore
local colors = {
   date      = { fg = '#fab387', bg = 'rgba(0, 0, 0, 0.4)' },
   battery   = { fg = '#f9e2af', bg = 'rgba(0, 0, 0, 0.4)' },
   separator = { fg = '#74c7ec', bg = 'rgba(0, 0, 0, 0.4)' }
}

local cells = Cells:new()
local last_status_by_window = {}

cells
   :add_segment('date_icon', ICON_DATE .. '  ', colors.date, attr(attr.intensity('Bold')))
   :add_segment('date_text', '', colors.date, attr(attr.intensity('Bold')))
   :add_segment('separator', ' ' .. ICON_SEPARATOR .. '  ', colors.separator)
   :add_segment('battery_icon', '', colors.battery)
   :add_segment('battery_text', '', colors.battery, attr(attr.intensity('Bold')))

-- fork（WEZ-PERF-04）：无电池机器首次枚举为空即记住，后续早退
local no_battery = false

---@return string, string
local function battery_info()
   -- fork（WEZ-PERF-04）：无电池机器（台式机）每 2 秒枚举一次 D-Bus
   -- 是白跑；首次枚举为空即记住，之后早退。
   if no_battery then
      return '', ''
   end

   local charge = ''
   local icon = ''

   local found = false
   for _, b in ipairs(wezterm.battery_info()) do
      found = true
      local idx = umath.clamp(umath.round(b.state_of_charge * 10), 1, 10)
      charge = string.format('%.0f%%', b.state_of_charge * 100)

      if b.state == 'Charging' then
         icon = charging_icons[idx]
      else
         icon = discharging_icons[idx]
      end
   end
   if not found then
      no_battery = true
   end

   return charge, icon .. ' '
end

---@param opts? Event.RightStatusOptions Default: {date_format = '%a %H:%M:%S'}
M.setup = function(opts)
   local valid_opts, err = EVENT_OPTS.validator:validate(opts or {})

   if err then
      wezterm.log_error(err)
   end

   wezterm.on('update-right-status', function(window, _pane)
      local battery_text, battery_icon = battery_info()

      cells
         :update_segment_text('date_text', wezterm.strftime(valid_opts.date_format))
         :update_segment_text('battery_icon', battery_icon)
         :update_segment_text('battery_text', battery_text)

      local status = wezterm.format(
         cells:render({ 'date_icon', 'date_text', 'separator', 'battery_icon', 'battery_text' })
      )
      local window_id = window:window_id()

      -- fork（WEZ-PERF-04）：窗口关闭后表项回收，不随窗口数无限增长
      local alive = {}
      for _, w in ipairs(wezterm.gui.gui_windows()) do
         alive[w:window_id()] = true
      end
      for id in pairs(last_status_by_window) do
         if not alive[id] then
            last_status_by_window[id] = nil
         end
      end

      -- update-right-status 每秒触发；内容未变化时跳过 GUI 更新，避免顶部栏重绘。
      if last_status_by_window[window_id] ~= status then
         last_status_by_window[window_id] = status
         window:set_right_status(status)
      end
   end)
end

return M
