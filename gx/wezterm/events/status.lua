local wezterm = require('wezterm')

local M = {}
local last_status_by_window = {}

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

M.setup = function(opts)
   local date_format = (opts and opts.date_format) or '%a %H:%M'
   wezterm.on('update-status', function(window, _pane)
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
   end)
end

return M
