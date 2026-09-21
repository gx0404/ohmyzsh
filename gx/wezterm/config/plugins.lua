local wezterm = require('wezterm')

-- fork（WEZ-CFG-03）：插件 require 失败（离线机器/插件目录损坏）不该
-- 拖垮整份配置加载；失败时返回 nil，bindings.lua 的插件键位跳过注册。
local function try_require(url)
   local ok, plugin = pcall(wezterm.plugin.require, url)
   if ok then
      return plugin
   end
   wezterm.log_error('plugin load failed (skipping its keybindings): ' .. url)
   return nil
end

-- resurrect: 会话保存与恢复
local resurrect = try_require('https://github.com/MLFlexer/resurrect.wezterm')

-- smart_workspace_switcher: 智能 workspace 切换
local workspace_switcher = try_require('https://github.com/MLFlexer/smart_workspace_switcher.wezterm')
-- fork（WEZ-CFG-05）：不调用 apply_to_config——本配置只手动绑定
-- switch_workspace()（SUPER+s），避免插件默认键位/事件与本仓 leader
-- 层冲突；原先给 apply_to_config 打的 stub 是死代码，已删除。

return {
   resurrect = resurrect,
   workspace_switcher = workspace_switcher,
}
