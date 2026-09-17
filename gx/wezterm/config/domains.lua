local wezterm = require('wezterm')
local platform = require('utils.platform')

local options = { ssh_domains = {}, unix_domains = {}, wsl_domains = {} }
if platform.is_win then
   -- 使用真实发行版及其默认 Linux 用户/登录 shell；Windows 用户名不等于 WSL 用户。
   local ok, domains = pcall(wezterm.default_wsl_domains)
   if ok then options.wsl_domains = domains end
end
return options
