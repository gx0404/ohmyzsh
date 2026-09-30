local platform = require('utils.platform')
local wsl = require('utils.wsl')

local options = { ssh_domains = {}, unix_domains = {}, wsl_domains = {} }
if platform.is_win then
   -- 使用真实发行版及其默认 Linux 用户/登录 shell；Windows 用户名不等于 WSL 用户。
   -- wsl_domains 必须始终赋值：留空时 Rust 侧每次 domain 查询都会再跑 wsl.exe。
   options.wsl_domains = wsl.domains()
end
return options
