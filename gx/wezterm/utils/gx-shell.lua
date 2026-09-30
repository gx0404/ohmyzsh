-- GX Shell 安装包内的 WezTerm 与 GX Zsh / herdr 同装：
-- Windows `<root>\wezterm\wezterm-gui.exe` + `<root>\bin\{gx-zsh,herdr}.exe`，
-- deb `/usr/lib/wezterm-gx/` + `/usr/lib/ohmyzsh-gx/bin/{gx-zsh,herdr}`。
-- 独立安装的 WezTerm 找不到这两个入口，保持原有 shell 选择。

---@class GxShellEntries
---@field gx_zsh string
---@field herdr string

local M = {}

---@param executable_dir string|nil
---@return string|nil
function M.install_root(executable_dir)
   if type(executable_dir) ~= 'string' then
      return nil
   end
   local trimmed = executable_dir:gsub('[\\/]+$', '')
   return trimmed:match('^(.+)[\\/][^\\/]+$')
end

---@param root string|nil
---@param is_win boolean
---@return GxShellEntries|nil
function M.entry_points(root, is_win)
   if not root or root == '' then
      return nil
   end
   if is_win then
      return { gx_zsh = root .. '\\bin\\gx-zsh.exe', herdr = root .. '\\bin\\herdr.exe' }
   end
   return { gx_zsh = root .. '/ohmyzsh-gx/bin/gx-zsh', herdr = root .. '/ohmyzsh-gx/bin/herdr' }
end

---@param path string
---@return boolean
local function readable(path)
   local file = io.open(path, 'rb')
   if file then
      file:close()
      return true
   end
   return false
end

---@param executable_dir string|nil
---@param is_win boolean
---@param exists? fun(path: string): boolean
---@return GxShellEntries|nil
function M.detect(executable_dir, is_win, exists)
   exists = exists or readable
   local entries = M.entry_points(M.install_root(executable_dir), is_win)
   if entries and exists(entries.gx_zsh) and exists(entries.herdr) then
      return entries
   end
   return nil
end

return M
