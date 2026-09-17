local wezterm = require('wezterm')
local platform = require('utils.platform')

local options = {
   default_prog = {},
   launch_menu = {},
}

if platform.is_win then
   local function available(name)
      local ok, success = pcall(wezterm.run_child_process, { 'where.exe', name })
      return ok and success
   end
   options.default_prog = available('pwsh.exe') and { 'pwsh.exe', '-NoLogo' }
      or { 'powershell.exe', '-NoLogo' }
   options.launch_menu = { { label = 'PowerShell 5.1', args = { 'powershell.exe', '-NoLogo' } },
      { label = 'Command Prompt', args = { 'cmd.exe' } } }
   if available('pwsh.exe') then
      table.insert(options.launch_menu, 1, { label = 'PowerShell 7', args = { 'pwsh.exe', '-NoLogo' } })
   end
   for _, entry in ipairs({ { 'Nushell', 'nu.exe' }, { 'MSYS2', 'ucrt64.cmd' } }) do
      if available(entry[2]) then table.insert(options.launch_menu, { label = entry[1], args = { entry[2] } }) end
   end
   local git_bash = wezterm.home_dir .. '/scoop/apps/git/current/bin/bash.exe'
   local file = io.open(git_bash, 'rb')
   if file then
      file:close()
      table.insert(options.launch_menu, { label = 'Git Bash', args = { git_bash, '-l' } })
   end
   if available('wsl.exe') then
      table.insert(options.launch_menu, { label = 'WSL (default)', args = { 'wsl.exe', '--cd', '~' } })
   end
elseif platform.is_mac then
   options.default_prog = { '/opt/homebrew/bin/fish', '-l' }
   options.launch_menu = {
      { label = 'Bash', args = { 'bash', '-l' } },
      { label = 'Fish', args = { '/opt/homebrew/bin/fish', '-l' } },
      { label = 'Nushell', args = { '/opt/homebrew/bin/nu', '-l' } },
      { label = 'Zsh', args = { 'zsh', '-l' } },
   }
elseif platform.is_linux then
   options.default_prog = { 'zsh', '-l' }
   options.launch_menu = {
      { label = 'Zsh', args = { 'zsh', '-l' } },
      { label = 'Bash (fallback)', args = { 'bash', '-l' } },
   }
end

return options
