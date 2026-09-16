local wezterm = require('wezterm')

-- resurrect: 会话保存与恢复
local resurrect = wezterm.plugin.require('https://github.com/MLFlexer/resurrect.wezterm')

-- smart_workspace_switcher: 智能 workspace 切换
local workspace_switcher = wezterm.plugin.require('https://github.com/MLFlexer/smart_workspace_switcher.wezterm')
workspace_switcher.apply_to_config = workspace_switcher.apply_to_config or function() end

return {
   resurrect = resurrect,
   workspace_switcher = workspace_switcher,
}
