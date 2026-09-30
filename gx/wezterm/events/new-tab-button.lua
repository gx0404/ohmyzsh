local wezterm = require('wezterm')
local launch = require('config.launch')
local shells = require('utils.shells')
local Cells = require('utils.cells')

local nf = wezterm.nerdfonts
local act = wezterm.action
local attr = Cells.attr

local M = {}

local OPEN_SETTINGS = 'open-settings'

---@type table<string, Cells.SegmentColors>
-- stylua: ignore
local colors = {
   label_text    = { fg = '#CDD6F4' },
   icon_default  = { fg = '#89B4FA' },
   icon_wsl      = { fg = '#FAB387' },
   icon_ssh      = { fg = '#F38BA8' },
   icon_unix     = { fg = '#CBA6F7' },
   icon_settings = { fg = '#A6E3A1' },
}

local cells = Cells:new()
   :add_segment('icon_default', ' ' .. nf.oct_terminal .. ' ', colors.icon_default)
   :add_segment('icon_wsl', ' ' .. nf.cod_terminal_linux .. ' ', colors.icon_wsl)
   :add_segment('icon_ssh', ' ' .. nf.md_ssh .. ' ', colors.icon_ssh)
   :add_segment('icon_unix', ' ' .. nf.dev_gnu .. ' ', colors.icon_unix)
   :add_segment('icon_settings', ' ' .. nf.md_cog .. ' ', colors.icon_settings)
   :add_segment('label_text', '', colors.label_text, attr(attr.intensity('Bold')))

---右键列表：launch_menu 各项、SSH/Unix 域，末项打开设置页的默认 Shell 分区。
---SSH/Unix 域取自点击时窗口的生效配置，不依赖 config/domains.lua 模块本身。
---@param ssh_domains table[]|nil
---@param unix_domains table[]|nil
---@return table[] choices
---@return table[] choices_data 与 choices 前若干项一一对应的 SpawnCommand
function M.build_choices(ssh_domains, unix_domains)
   local choices = {}
   local choices_data = {}

   local function add(icon, label, data)
      cells:update_segment_text('label_text', label)
      table.insert(choices, {
         id = tostring(#choices + 1),
         label = wezterm.format(cells:render({ icon, 'label_text' })),
      })
      table.insert(choices_data, data)
   end

   -- launch_menu 各项按自己的 domain 启动（local / WSL:<发行版>），标出当前默认 Shell
   local default_idx = shells.default_index(launch)
   for idx, v in ipairs(launch.launch_menu) do
      local domain = v.domain and v.domain.DomainName or 'local'
      add(domain == 'local' and 'icon_default' or 'icon_wsl', idx == default_idx and v.label .. '（默认）' or v.label, {
         args = v.args,
         domain = v.domain,
         set_environment_variables = v.set_environment_variables,
      })
   end

   -- Add SSH domains
   for _, v in ipairs(ssh_domains or {}) do
      add('icon_ssh', v.name, { domain = { DomainName = v.name } })
   end

   -- Add Unix domains
   for _, v in ipairs(unix_domains or {}) do
      add('icon_unix', v.name, { domain = { DomainName = v.name } })
   end

   cells:update_segment_text('label_text', '设为默认 Shell…')
   table.insert(choices, {
      id = OPEN_SETTINGS,
      label = wezterm.format(cells:render({ 'icon_settings', 'label_text' })),
   })

   return choices, choices_data
end

M.setup = function()
   wezterm.on('new-tab-button-click', function(window, pane, button, default_action)
      if default_action and button == 'Left' then
         window:perform_action(default_action, pane)
      end

      if default_action and button == 'Right' then
         local config = window:effective_config()
         local choices, choices_data = M.build_choices(config.ssh_domains, config.unix_domains)
         window:perform_action(
            act.InputSelector({
               title = 'InputSelector: Launch Menu',
               choices = choices,
               fuzzy = true,
               fuzzy_description = nf.md_rocket .. ' Select a lauch item: ',
               action = wezterm.action_callback(function(_window, _pane, id, label)
                  if not id and not label then
                     return
                  elseif id == OPEN_SETTINGS then
                     window:perform_action(act.ShowDefaultShellSettings, pane)
                  else
                     wezterm.log_info('you selected ', id, label)
                     wezterm.log_info(choices_data[tonumber(id)])
                     window:perform_action(
                        act.SpawnCommandInNewTab(choices_data[tonumber(id)]),
                        pane
                     )
                  end
               end),
            }),
            pane
         )
      end
      return false
   end)
end

return M
