-- 默认 Shell 的纯函数层：探测本机 Shell、解析 gui-settings.json 的 default_shell、
-- 生成 launch_menu，并给 herdr 映射可执行文件的绝对路径。
-- 加载时不 require('wezterm')：环境变量与文件存在性由 config/launch.lua 注入，
-- 可用独立 lua5.4 测试（wezterm/scripts/tests/gx_shells.lua）。
-- 探测只做 io.open，不起子进程：配置在 require 里求值，run_child_process 会报
-- "attempt to yield across a C-call boundary"。

---@class GxShell
---@field id string gui-settings.json 的 default_shell 取值，也写进 GX_SHELL_ID
---@field label string
---@field exe string herdr default_shell 使用的绝对路径
---@field herdr_label string|nil herdr 实际得到的 Shell 与 label 不同时的说明（用于 toast）
---@field args string[]|nil 为 nil 时由 domain 的默认程序启动（WSL）
---@field domain string 'local' 或 'WSL:<发行版>'

---@class GxShellContext
---@field os 'windows'|'linux'|'mac'
---@field getenv fun(name: string): string|nil
---@field exists fun(path: string): boolean
---@field gx {root: string, gx_zsh: string, herdr: string}|nil GX Shell 安装包入口
---@field wsl {name: string, distribution: string|nil}[]|nil utils/wsl.lua 的发行版 domain 列表

local M = {}

local ENOENT = 2

---能打开才算存在。唯一例外是 WindowsApps 下的应用执行别名（应用商店版 pwsh.exe、
---wsl.exe）：打开报 EINVAL，却能正常启动。其他位置的打开失败（失效的 PATH 条目、
---没插盘的可移动驱动器）一律算不存在，免得挡住后面真正的可执行文件。
---@param path string
---@return boolean
function M.exists(path)
   local file, _, code = io.open(path, 'rb')
   if file then
      file:close()
      return true
   end
   local alias = path:lower():gsub('/', '\\'):find('\\windowsapps\\', 1, true) ~= nil
   return alias and code ~= nil and code ~= ENOENT
end

---PATH 拆成去重的绝对目录。Windows 以 ';' 分隔、忽略大小写，去掉引号与结尾分隔符；
---相对路径和含非法字符的条目丢弃（非法路径打开也报 EINVAL，会被误判为存在）。
---@param value string|nil
---@param is_win boolean
---@return string[]
function M.path_dirs(value, is_win)
   local dirs, seen = {}, {}
   for entry in (value or ''):gmatch(is_win and '[^;]+' or '[^:]+') do
      local dir = entry:match('^%s*"?(.-)"?%s*$')
      local key
      if is_win then
         if (dir:match('^%a:[\\/]') or dir:match('^[\\/][\\/]')) and not dir:find('[<>"|?*]') then
            dir = dir:gsub('/', '\\'):gsub('\\+$', '')
            key = dir:lower()
         end
      elseif dir:sub(1, 1) == '/' then
         dir = dir:gsub('/+$', '')
         key = dir
      end
      if key and not seen[key] then
         seen[key] = true
         table.insert(dirs, dir)
      end
   end
   return dirs
end

---System32 与 WindowsApps 下的 bash.exe 是 WSL 启动器，不是 Git Bash / MSYS2。
---@param path string
---@return boolean
function M.is_wsl_bash(path)
   local lower = path:lower():gsub('/', '\\')
   return lower:find('\\system32\\', 1, true) ~= nil or lower:find('\\windowsapps\\', 1, true) ~= nil
end

---@param base string|nil
---@return string|nil
local function join(base, ...)
   if base == nil or base == '' then
      return nil
   end
   local trimmed = base:gsub('[\\/]+$', '')
   return table.concat({ trimmed, ... }, '\\')
end

---@return string[]
local function compact(...)
   local list = {}
   for i = 1, select('#', ...) do
      local value = select(i, ...)
      if value then
         table.insert(list, value)
      end
   end
   return list
end

local ROOT_SUFFIXES = {
   '\\cmd',
   '\\usr\\bin',
   '\\mingw64\\bin',
   '\\mingw32\\bin',
   '\\ucrt64\\bin',
   '\\clang64\\bin',
   '\\clangarm64\\bin',
   '\\bin',
}

---由 PATH 目录反推 Git for Windows / MSYS2 根目录。
---@param dir string
---@return string|nil
local function root_of(dir)
   local lower = dir:lower()
   for _, suffix in ipairs(ROOT_SUFFIXES) do
      if #lower > #suffix and lower:sub(-#suffix) == suffix then
         return dir:sub(1, #dir - #suffix)
      end
   end
   return nil
end

---GX Shell 私有运行时 <安装根>\runtime\msys64 形似 MSYS2，但不是给用户用的。
---@param root string
---@param exists fun(path: string): boolean
---@return boolean
local function is_gx_runtime(root, exists)
   local base = root:lower():match('^(.*)\\runtime\\msys64$')
   return base ~= nil and exists(root:sub(1, #base) .. '\\bin\\gx-zsh.exe')
end

---@param id string
---@param label string
---@param exe string
---@param args string[]|nil
---@param domain string|nil
---@return GxShell
local function shell(id, label, exe, args, domain)
   return { id = id, label = label, exe = exe, args = args, domain = domain or 'local' }
end

---WezTerm 的 os.getenv 遇到不是 UTF-8 的值会抛错（Linux 上可能出现），按未设置处理。
---@param getenv fun(name: string): string|nil
---@return fun(name: string): string|nil
local function safe(getenv)
   return function(name)
      local ok, value = pcall(getenv, name)
      if ok then
         return value
      end
      return nil
   end
end

---@param ctx GxShellContext
---@return GxShell[]
local function windows_shells(ctx)
   local env, exists = safe(ctx.getenv), ctx.exists
   local dirs = M.path_dirs(env('PATH'), true)
   local system_root = env('SystemRoot') or env('windir') or 'C:\\Windows'
   local system_drive = env('SystemDrive') or 'C:'
   local program_files = env('ProgramFiles')
   local scoop = env('SCOOP') or join(env('USERPROFILE'), 'scoop')

   local function on_path(name)
      for _, dir in ipairs(dirs) do
         local path = dir .. '\\' .. name
         if exists(path) then
            return path
         end
      end
      return nil
   end

   local function first(candidates)
      for _, path in ipairs(candidates) do
         if exists(path) then
            return path
         end
      end
      return nil
   end

   local roots, seen = {}, {}
   local function add_root(root)
      if root and not seen[root:lower()] and not is_gx_runtime(root, exists) then
         seen[root:lower()] = true
         table.insert(roots, root)
      end
   end
   for _, dir in ipairs(dirs) do
      local bash = dir .. '\\bash.exe'
      if exists(dir .. '\\git.exe') or (not M.is_wsl_bash(bash) and exists(bash)) then
         add_root(root_of(dir))
      end
   end
   local known_roots = compact(
      join(program_files, 'Git'),
      join(env('ProgramFiles(x86)'), 'Git'),
      join(env('LOCALAPPDATA'), 'Programs', 'Git'),
      join(scoop, 'apps', 'git', 'current'),
      join(system_drive, 'msys64'),
      join(system_drive, 'tools', 'msys64'),
      join(scoop, 'apps', 'msys2', 'current')
   )
   for _, root in ipairs(known_roots) do
      add_root(root)
   end

   local list = {}
   if ctx.gx then
      local zsh = ctx.gx.root .. '\\runtime\\msys64\\usr\\bin\\zsh.exe'
      table.insert(list, shell('gx-zsh', 'GX Zsh', zsh, { ctx.gx.gx_zsh }))
   end

   local pwsh = on_path('pwsh.exe')
      or first(compact(
         join(program_files, 'PowerShell', '7', 'pwsh.exe'),
         join(program_files, 'PowerShell', '7-preview', 'pwsh.exe'),
         join(scoop, 'apps', 'pwsh', 'current', 'pwsh.exe')
      ))
   if pwsh then
      table.insert(list, shell('pwsh', 'PowerShell 7', pwsh, { pwsh, '-NoLogo' }))
   end

   local powershell = first({ join(system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe') })
      or on_path('powershell.exe')
   if powershell then
      table.insert(list, shell('powershell', 'PowerShell 5.1', powershell, { powershell, '-NoLogo' }))
   end

   local cmd = first(compact(env('ComSpec'), join(system_root, 'System32', 'cmd.exe')))
   if cmd then
      table.insert(list, shell('cmd', 'Command Prompt', cmd, { cmd }))
   end

   for _, root in ipairs(roots) do
      local bash = root .. '\\bin\\bash.exe'
      if exists(bash) and (exists(root .. '\\cmd\\git.exe') or exists(root .. '\\git-bash.exe')) then
         table.insert(list, shell('git-bash', 'Git Bash', bash, { bash, '--login', '-i' }))
         break
      end
   end

   for _, root in ipairs(roots) do
      local usr_bin = root .. '\\usr\\bin\\'
      if exists(root .. '\\msys2_shell.cmd') and exists(usr_bin .. 'env.exe') and exists(usr_bin .. 'bash.exe') then
         local args = { usr_bin .. 'env.exe', 'MSYSTEM=UCRT64', 'CHERE_INVOKING=1', '/usr/bin/bash', '--login', '-i' }
         local entry = shell('msys2-ucrt64', 'MSYS2 UCRT64', usr_bin .. 'bash.exe', args)
         -- herdr 的 default_shell 只能是一个可执行文件，拿不到 MSYSTEM=UCRT64。
         entry.herdr_label = 'MSYS2 bash（MSYS 环境，不是 UCRT64）'
         table.insert(list, entry)
         break
      end
   end

   local nu = on_path('nu.exe')
      or first(compact(join(program_files, 'nu', 'bin', 'nu.exe'), join(scoop, 'apps', 'nu', 'current', 'nu.exe')))
   if nu then
      table.insert(list, shell('nu', 'Nushell', nu, { nu }))
   end

   local wsl = join(system_root, 'System32', 'wsl.exe')
   for _, domain in ipairs(ctx.wsl or {}) do
      local distribution = domain.distribution or domain.name:gsub('^WSL:', '')
      local entry = shell('wsl:' .. distribution, 'WSL: ' .. distribution, wsl, nil, domain.name)
      -- herdr 只拿到 wsl.exe，不能带 -d：它的窗格进入默认发行版。
      entry.herdr_label = 'WSL 默认发行版（herdr 不能指定发行版）'
      table.insert(list, entry)
   end
   return list
end

---@param ctx GxShellContext
---@return GxShell[]
local function linux_shells(ctx)
   local dirs = M.path_dirs(safe(ctx.getenv)('PATH'), false)
   local function on_path(name)
      for _, dir in ipairs(dirs) do
         local path = dir .. '/' .. name
         if ctx.exists(path) then
            return path
         end
      end
      return nil
   end

   local list = {}
   local gx_zsh = ctx.gx and ctx.gx.root .. '/ohmyzsh-gx/libexec/zsh/zsh'
   if ctx.gx then
      table.insert(list, shell('gx-zsh', 'GX Zsh', gx_zsh, { ctx.gx.gx_zsh }))
   end
   for _, name in ipairs({ 'zsh', 'bash' }) do
      local path = on_path(name)
      if path then
         local entry = shell(name, name == 'zsh' and 'Zsh' or 'Bash', path, { path, '-l' })
         if name == 'zsh' and gx_zsh then
            -- herdr 服务端带着 GX 的 zsh 环境（ZDOTDIR 等），系统 zsh 在它的窗格里照样加载
            -- GX 配置；直接让 herdr 用 GX Zsh，toast 如实说明。
            entry.exe = gx_zsh
            entry.herdr_label = 'GX Zsh（系统 zsh 在 herdr 里也会加载 GX 配置）'
         end
         table.insert(list, entry)
      end
   end
   return list
end

---@return GxShell[]
local function mac_shells()
   return {
      shell('fish', 'Fish', '/opt/homebrew/bin/fish', { '/opt/homebrew/bin/fish', '-l' }),
      shell('bash', 'Bash', 'bash', { 'bash', '-l' }),
      shell('nu', 'Nushell', '/opt/homebrew/bin/nu', { '/opt/homebrew/bin/nu', '-l' }),
      shell('zsh', 'Zsh', 'zsh', { 'zsh', '-l' }),
   }
end

---按 launch_menu 顺序列出本机可用的 Shell（安装包内 GX Zsh 永远在最前）。
---@param ctx GxShellContext
---@return GxShell[]
function M.detect(ctx)
   if ctx.os == 'windows' then
      return windows_shells(ctx)
   elseif ctx.os == 'linux' then
      return linux_shells(ctx)
   end
   return mac_shells()
end

---读 gui-settings.json 的 default_shell；文件缺失、JSON 损坏或类型不对都视为没选。
---@param text string|nil
---@param json_parse fun(text: string): any
---@return string|nil
function M.read_choice(text, json_parse)
   if type(text) ~= 'string' then
      return nil
   end
   local ok, settings = pcall(json_parse, text)
   if ok and type(settings) == 'table' then
      local id = settings.default_shell
      if type(id) == 'string' and id ~= '' then
         return id
      end
   end
   return nil
end

local FALLBACK = {
   windows = { 'gx-zsh', 'pwsh', 'powershell' },
   linux = { 'gx-zsh', 'zsh' },
   mac = { 'fish' },
}

---解析默认 Shell：有效选择优先，否则 GX Zsh → PowerShell 7 → PowerShell 5.1
---（Windows）/ Zsh（Linux），都没有时取第一项。
---@param shells GxShell[]
---@param choice string|nil
---@param os_name string
---@return GxShell|nil shell
---@return boolean fell_back 选择存在却不可用
function M.resolve(shells, choice, os_name)
   local by_id = {}
   for _, entry in ipairs(shells) do
      by_id[entry.id] = entry
   end
   if choice and by_id[choice] then
      return by_id[choice], false
   end
   for _, id in ipairs(FALLBACK[os_name] or {}) do
      if by_id[id] then
         return by_id[id], choice ~= nil
      end
   end
   return shells[1], choice ~= nil
end

---生成 default_prog / launch_menu / default_domain（只含真实配置键，多余的键会让
---WezTerm 弹配置错误）。每项都固定 domain 并带 GX_SHELL_ID；herdr 紧跟 GX Zsh、
---不带标记。
---@param shells GxShell[]
---@param default GxShell|nil
---@param gx {herdr: string}|nil
---@param os_name string
---@return table
function M.launch_options(shells, default, gx, os_name)
   local menu = {}
   for _, entry in ipairs(shells) do
      table.insert(menu, {
         label = entry.label,
         args = entry.args,
         domain = { DomainName = entry.domain },
         set_environment_variables = { GX_SHELL_ID = entry.id },
      })
      if entry.id == 'gx-zsh' and gx then
         table.insert(menu, { label = 'herdr', args = { gx.herdr }, domain = { DomainName = 'local' } })
      end
   end

   local options = { launch_menu = menu }
   if default and default.domain ~= 'local' then
      -- 选中 WSL 时新标签默认进该发行版；本地 domain 的默认程序仍按回退顺序取。
      options.default_domain = default.domain
      local locals = {}
      for _, entry in ipairs(shells) do
         if entry.domain == 'local' then
            table.insert(locals, entry)
         end
      end
      default = M.resolve(locals, nil, os_name)
   end
   if default then
      options.default_prog = default.args
   end
   return options
end

---@param a string[]|nil
---@param b string[]|nil
---@return boolean
local function same_args(a, b)
   if a == nil or b == nil or #a ~= #b then
      return false
   end
   for i = 1, #a do
      if a[i] ~= b[i] then
         return false
      end
   end
   return true
end

---launch_options 结果里默认 Shell 所在的 launch_menu 下标（新标签按钮标注用）。
---@param options {launch_menu: table[]|nil, default_prog: string[]|nil, default_domain: string|nil}
---@return integer|nil
function M.default_index(options)
   for idx, entry in ipairs(options.launch_menu or {}) do
      local tagged = entry.set_environment_variables and entry.set_environment_variables.GX_SHELL_ID
      local domain = entry.domain and entry.domain.DomainName
      if tagged then
         if options.default_domain then
            if domain == options.default_domain then
               return idx
            end
         elseif domain == 'local' and same_args(entry.args, options.default_prog) then
            return idx
         end
      end
   end
   return nil
end

---归类 `herdr --gx-set-default-shell` 的结果。run_child_process 只给成功与否、
---拿不到退出码 3（配置不归 GX 管），只能认 Oh My Zsh GX 启动器的原话。
---@param success boolean
---@param stdout string|nil
---@param stderr string|nil
---@return 'ok'|'custom'|'error'
function M.herdr_outcome(success, stdout, stderr)
   if success then
      return 'ok'
   end
   if (stderr or ''):find('herdr uses a custom configuration', 1, true) then
      return 'custom'
   end
   return 'error'
end

return M
