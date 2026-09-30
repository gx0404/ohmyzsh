-- 设置页 sidecar gui-settings.json 的位置，与 config/src/gui_settings.rs::settings_file_in_dir
-- 保持一致：配置目录不是 HOME 时就在 wezterm.lua 旁边；配置是 ~/.wezterm.lua（目录即
-- HOME）时依次退回 WEZTERM_CONFIG_DIR（不等于 HOME 时）、$XDG_CONFIG_HOME/wezterm、
-- ~/.config/wezterm。纯函数：不 require('wezterm')，环境变量由调用方注入。

local M = {}

local FILE = 'gui-settings.json'

---@param base string
---@param name string
---@return string
local function join(base, name)
   if base == '' then
      return name
   end
   if base:match('[/\\]$') then
      return base .. name
   end
   return base .. '/' .. name
end

---Rust 按路径分量比较目录：分隔符写法、重复或结尾的分隔符不影响结果，盘符不分大小写。
---@param path string
---@return string
local function normalize(path)
   path = path:gsub('\\', '/'):gsub('/+', '/')
   if #path > 1 then
      path = path:gsub('/$', '')
   end
   return (path:gsub('^%a:', string.upper))
end

---@param config_dir string wezterm.config_dir（生效的 wezterm.lua 所在目录）
---@param home_dir string wezterm.home_dir
---@param getenv fun(name: string): string|nil os.getenv；WezTerm 的版本遇到非 UTF-8 值会抛错，按未设置处理
---@return string
function M.path(config_dir, home_dir, getenv)
   local home = normalize(home_dir)
   if normalize(config_dir) ~= home then
      return join(config_dir, FILE)
   end
   local function env(name)
      local ok, value = pcall(getenv, name)
      if ok then
         return value
      end
      return nil
   end
   local env_dir = env('WEZTERM_CONFIG_DIR')
   if env_dir and normalize(env_dir) ~= home then
      return join(env_dir, FILE)
   end
   return join(join(env('XDG_CONFIG_HOME') or join(home_dir, '.config'), 'wezterm'), FILE)
end

return M
