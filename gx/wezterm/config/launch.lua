local wezterm = require('wezterm')
local platform = require('utils.platform')
local gx_shell = require('utils.gx-shell')
local gui_settings = require('utils.gui-settings')
local shells = require('utils.shells')
local wsl = require('utils.wsl')

-- 默认 Shell 取自设置页写入 gui-settings.json 的 default_shell；缺失或不可用时回退
-- GX Zsh（安装包内）→ PowerShell 7 → PowerShell 5.1（Windows）/ Zsh（Linux）。
-- 探测见 utils/shells.lua：只做 io.open，配置求值期间不起任何子进程。
local getenv = os.getenv
local gx = nil
if platform.is_win or platform.is_linux then
   local entries = gx_shell.detect(wezterm.executable_dir, platform.is_win, shells.exists)
   if entries then
      gx = { root = gx_shell.install_root(wezterm.executable_dir), gx_zsh = entries.gx_zsh, herdr = entries.herdr }
   end
end

local catalog = shells.detect({
   os = platform.os,
   getenv = getenv,
   exists = shells.exists,
   gx = gx,
   wsl = platform.is_win and wsl.domains() or nil,
})

---@return GxShell|nil
local function default_shell()
   local choice = nil
   local file = io.open(gui_settings.path(wezterm.config_dir, wezterm.home_dir, getenv), 'rb')
   if file then
      choice = shells.read_choice(file:read('a'), wezterm.json_parse)
      file:close()
   end
   local shell, fell_back = shells.resolve(catalog, choice, platform.os)
   if fell_back then
      wezterm.log_warn(
         string.format('default_shell %q is not available, using %s', choice, shell and shell.id or 'the built-in default')
      )
   end
   return shell
end

-- 设置页切换默认 Shell 后发出该事件：让安装包内 herdr 的新窗格跟随同一个 Shell。
-- herdr 只接受一个可执行文件，做不到的部分（WSL 发行版、MSYS2 的 UCRT64 环境）由
-- herdr_label 在 toast 里说明。事件可能先于配置重载到达，所以这里重新读一次选择。
wezterm.on('gx-default-shell-changed', function(window, _pane)
   local shell = gx and default_shell()
   if not shell then
      return
   end
   local ok, success, stdout, stderr =
      pcall(wezterm.run_child_process, { gx.herdr, '--gx-set-default-shell', shell.exe })
   local outcome = ok and shells.herdr_outcome(success, stdout, stderr) or 'error'
   if outcome == 'ok' then
      window:toast_notification('GX Shell', 'herdr 新窗格将使用 ' .. (shell.herdr_label or shell.label), nil, 4000)
   elseif outcome == 'custom' then
      window:toast_notification('GX Shell', 'herdr 使用自定义 Shell 配置，未修改', nil, 4000)
   else
      local detail = ok and ((stderr ~= nil and stderr ~= '') and stderr or stdout) or success
      local message = tostring(detail or ''):gsub('%s+$', '')
      window:toast_notification('herdr 默认 Shell 同步失败', message, nil, 6000)
   end
end)

return shells.launch_options(catalog, default_shell(), gx, platform.os)
