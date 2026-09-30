local wezterm = require('wezterm')

-- fork（WEZ-CFG-03）：插件 require 失败（离线机器/插件目录损坏）不该拖垮整份配置
-- 加载，失败时返回 nil：workspace switcher 的键位降级为 Nop，resurrect 的键位在按下
-- 时提示加载失败。
local function try_require(url)
   local ok, plugin = pcall(wezterm.plugin.require, url)
   if ok then
      return plugin
   end
   wezterm.log_error('plugin load failed (its keybindings do nothing): ' .. url)
   return nil
end

---与 lua-api-crates/plugin 的 compute_repo_dir 相同的目录名转义。
---@param url string
---@return string
local function compute_repo_dir(url)
   local dir = {}
   for _, code in utf8.codes(url) do
      local c = utf8.char(code)
      if c == '/' or c == '\\' then
         table.insert(dir, 'sZs')
      elseif c == ':' then
         table.insert(dir, 'sCs')
      elseif c == '.' then
         table.insert(dir, 'sDs')
      elseif c == '-' or c == '_' or c:match('^%w$') or code > 127 then
         table.insert(dir, c)
      else
         table.insert(dir, 'u' .. code)
      end
   end
   return (table.concat(dir):gsub('sZs$', ''))
end

-- 插件根目录与加载器一致：取 package.path 里的 <数据目录>/plugins/?/plugin/init.lua。
local plugins_dir = nil
for entry in package.path:gmatch('[^;]+') do
   plugins_dir = entry:match('^(.+)[/\\]%?[/\\]plugin[/\\]init%.lua$')
   if plugins_dir then
      break
   end
end

---插件目录缺失时 plugin.require 会在配置求值里同步 git clone（没有超时，离线时每次
---求值都重来）；插件由安装包/启动器预置，缺了就记日志跳过。
---@param url string
---@return boolean
local function installed(url)
   local file = plugins_dir and io.open(plugins_dir .. '/' .. compute_repo_dir(url) .. '/plugin/init.lua', 'rb')
   if file then
      file:close()
      return true
   end
   wezterm.log_warn('plugin not installed (skipping its keybindings): ' .. url)
   return false
end

local RESURRECT = 'https://github.com/MLFlexer/resurrect.wezterm'
local WORKSPACE_SWITCHER = 'https://github.com/MLFlexer/smart_workspace_switcher.wezterm'

local M = {
   compute_repo_dir = compute_repo_dir,
   -- smart_workspace_switcher: 智能 workspace 切换
   workspace_switcher = installed(WORKSPACE_SWITCHER) and try_require(WORKSPACE_SWITCHER) or nil,
   -- resurrect 的 init.lua 还会 plugin.require dev.wezterm，两者都在才算可用。
   resurrect_available = installed(RESURRECT) and installed('https://github.com/chrisgve/dev.wezterm'),
}
-- fork（WEZ-CFG-05）：不调用 apply_to_config——本配置只手动绑定
-- switch_workspace()（SUPER+s），避免插件默认键位/事件与本仓 leader
-- 层冲突；原先给 apply_to_config 打的 stub 是死代码，已删除。

local resurrect = nil

---resurrect: 会话保存与恢复。加载时 dev.wezterm 会用 git 打开全部插件仓库，
---所以等保存/恢复键第一次触发才加载。
---@return table|nil
function M.resurrect()
   if resurrect == nil and M.resurrect_available then
      resurrect = try_require(RESURRECT) or false
   end
   return resurrect or nil
end

return M
