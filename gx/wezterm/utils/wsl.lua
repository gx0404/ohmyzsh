local wezterm = require('wezterm')

-- WSL 发行版列表，config/domains.lua（wsl_domains）与 config/launch.lua（启动菜单）共用，
-- 改 domains.lua 加 SSH 域不会连带挡住启动菜单的升级。
-- default_wsl_domains 会同步运行 wsl.exe：结果以 JSON 缓存在 wezterm.GLOBAL（GLOBAL 取回的
-- 是共享代理，经 JSON 还原成普通表）。找到发行版时整个 GUI 进程只取一次；列表为空或
-- wsl.exe 失败（例如登录后 WSL 服务还没就绪）只缓存 RETRY_S 秒，之后的配置求值再试。

local M = {}

local KEY = 'gx_wsl'
local RETRY_S = 300

---@param now? integer os.time()，缺省取当前时间
---@return table[] 与 wezterm.default_wsl_domains() 同形的普通表
function M.domains(now)
   now = now or os.time()
   local cached = wezterm.GLOBAL[KEY]
   local fresh = false
   if cached ~= nil then
      local age = now - cached.at
      fresh = cached.found or (age >= 0 and age < RETRY_S)
   end
   if not fresh then
      local ok, domains = pcall(wezterm.default_wsl_domains)
      local list = ok and type(domains) == 'table' and domains or {}
      cached = { json = wezterm.json_encode(list), at = now, found = #list > 0 }
      wezterm.GLOBAL[KEY] = cached
   end
   local ok, domains = pcall(wezterm.json_parse, cached.json)
   if ok and type(domains) == 'table' then
      return domains
   end
   return {}
end

return M
