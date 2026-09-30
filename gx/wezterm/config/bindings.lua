local wezterm = require('wezterm')
local platform = require('utils.platform')
local backdrops = require('utils.backdrops')
local plugins = require('config.plugins')
local act = wezterm.action

local workspace_switcher = plugins.workspace_switcher

local mod = {}

if platform.is_mac then
   mod.SUPER = 'SUPER'
   mod.SUPER_REV = 'SUPER|CTRL'
else
   -- Linux 与 Windows 同一套：常用终端功能使用 Ubuntu 习惯的 Ctrl+Shift；壁纸控制
   -- 挂 leader 层（裸 Alt 会抢走 readline 的 Alt+. / Alt+b / Alt+f 等标准键，GX-10）。
   mod.SUPER = 'CTRL|SHIFT'
   mod.SUPER_REV = 'CTRL|ALT|SHIFT'
end

-- stylua: ignore
local keys = {
   -- misc/useful --
   { key = 'F1', mods = 'NONE', action = 'ActivateCopyMode' },
   { key = 'F2', mods = 'NONE', action = act.ActivateCommandPalette },
   { key = 'F3', mods = 'NONE', action = act.ShowLauncher },
   { key = 'F4', mods = 'NONE', action = act.ShowLauncherArgs({ flags = 'FUZZY|TABS' }) },
   {
      key = 'F5',
      mods = 'NONE',
      action = act.ShowLauncherArgs({ flags = 'FUZZY|WORKSPACES' }),
   },
   -- F8 打开 Atuin 紧凑历史菜单；Ctrl+R 仍可直接从 Shell 调用。
   { key = 'F8', mods = 'NONE', action = act.SendString '\x12' },
   { key = 'F11', mods = 'NONE',    action = act.ToggleFullScreen },
   { key = 'F12', mods = 'NONE',    action = act.ShowDebugOverlay },
   { key = 'f',   mods = mod.SUPER, action = act.Search({ CaseInSensitiveString = '' }) },
   {
      key = 'u',
      mods = mod.SUPER_REV,
      action = wezterm.action.QuickSelectArgs({
         label = 'open url',
         patterns = {
            '\\((https?://\\S+)\\)',
            '\\[(https?://\\S+)\\]',
            '\\{(https?://\\S+)\\}',
            '<(https?://\\S+)>',
            '\\bhttps?://\\S+[)/a-zA-Z0-9-]+'
         },
         action = wezterm.action_callback(function(window, pane)
            local url = window:get_selection_text_for_pane(pane)
            wezterm.log_info('opening: ' .. url)
            wezterm.open_with(url)
         end),
      }),
   },

   -- copy/paste --
   -- Ctrl+C / Ctrl+V 不拦截：前者是中断，后者交给 Claude Code/Codex/OpenCode 识别图片剪贴板。
   { key = 'c',          mods = 'CTRL|SHIFT',  action = act.CopyTo('Clipboard') },
   { key = 'v',          mods = 'CTRL|SHIFT',  action = act.PasteFrom('Clipboard') },

   -- tabs --
   -- tabs: spawn+close
   { key = 't',          mods = 'SHIFT|CTRL',  action = act.SpawnTab('DefaultDomain') },
   { key = 't',          mods = mod.SUPER_REV, action = act.SpawnTab('DefaultDomain') },
   { key = 'w',          mods = mod.SUPER_REV, action = act.CloseCurrentTab({ confirm = true }) },

   -- tabs: navigation
   { key = '[',          mods = mod.SUPER,     action = act.ActivateTabRelative(-1) },
   { key = ']',          mods = mod.SUPER,     action = act.ActivateTabRelative(1) },
   { key = '[',          mods = mod.SUPER_REV, action = act.MoveTabRelative(-1) },
   { key = ']',          mods = mod.SUPER_REV, action = act.MoveTabRelative(1) },

   -- tab: title
   { key = '0',          mods = mod.SUPER,     action = act.EmitEvent('tabs.manual-update-tab-title') },
   { key = '0',          mods = mod.SUPER_REV, action = act.EmitEvent('tabs.reset-tab-title') },

   -- tab: hide tab-bar
   { key = '9',          mods = mod.SUPER,     action = act.EmitEvent('tabs.toggle-tab-bar'), },

   -- window --
   -- window: spawn windows
   { key = 'n',          mods = mod.SUPER,     action = act.SpawnWindow },

   -- window: zoom window（挂 leader 层：Ctrl+Shift+- 就是 Ctrl+_，readline/zsh/emacs/nano
   -- 的撤销；Ctrl+Shift+= 是 Ctrl++，留给字号放大）
   {
      key = '-',
      mods = 'LEADER',
      action = wezterm.action_callback(function(window, _pane)
         local dimensions = window:get_dimensions()
         if dimensions.is_full_screen then
            return
         end
         local new_width = dimensions.pixel_width - 50
         local new_height = dimensions.pixel_height - 50
         window:set_inner_size(new_width, new_height)
      end)
   },
   {
      key = '=',
      mods = 'LEADER',
      action = wezterm.action_callback(function(window, _pane)
         local dimensions = window:get_dimensions()
         if dimensions.is_full_screen then
            return
         end
         local new_width = dimensions.pixel_width + 50
         local new_height = dimensions.pixel_height + 50
         window:set_inner_size(new_width, new_height)
      end)
   },
   {
      key = 'Enter',
      mods = mod.SUPER_REV,
      action = wezterm.action_callback(function(window, _pane)
         window:maximize()
      end)
   },

   -- 壁纸控制：统一挂 leader（Ctrl+Shift+Space 前缀），不再占用裸 Alt（GX-10）。
   {
      key = [[/]],
      mods = 'LEADER',
      action = wezterm.action_callback(function(window, _pane)
         backdrops:random(window)
      end),
   },
   {
      key = [[,]],
      mods = 'LEADER',
      action = wezterm.action_callback(function(window, _pane)
         backdrops:cycle_back(window)
      end),
   },
   {
      key = [[.]],
      mods = 'LEADER',
      action = wezterm.action_callback(function(window, _pane)
         backdrops:cycle_forward(window)
      end),
   },
   {
      -- 壁纸选择器；不用 LEADER|SHIFT+/：X11 会把 Shift+/ 解成 '?'，
      -- 用户绑定没有 shifted 变体合成（上游 #1906），物理不可达。
      key = 'i',
      mods = 'LEADER',
      action = act.InputSelector({
         title = 'InputSelector: Select Background',
         choices = backdrops:choices(),
         fuzzy = true,
         fuzzy_description = 'Select Background: ',
         action = wezterm.action_callback(function(window, _pane, idx)
            if not idx then
               return
            end
            ---@diagnostic disable-next-line: param-type-mismatch
            backdrops:set_img(window, tonumber(idx))
         end),
      }),
   },
   {
      key = 'b',
      mods = 'LEADER',
      action = wezterm.action_callback(function(window, _pane)
         backdrops:toggle_focus(window)
      end)
   },

   -- panes --
   -- panes: split panes
   {
      key = [[\]],
      mods = mod.SUPER,
      action = act.SplitVertical({ domain = 'CurrentPaneDomain' }),
   },
   {
      key = [[\]],
      mods = mod.SUPER_REV,
      action = act.SplitHorizontal({ domain = 'CurrentPaneDomain' }),
   },

   -- panes: zoom+close pane
   { key = 'Enter', mods = mod.SUPER,     action = act.TogglePaneZoomState },
   -- 裸 Alt+w 曾无确认销毁 pane（GX-10）；关闭窗格与关闭标签都先确认。
   { key = 'w',     mods = mod.SUPER,     action = act.CloseCurrentPane({ confirm = true }) },

   -- panes: navigation
   { key = 'k',     mods = mod.SUPER_REV, action = act.ActivatePaneDirection('Up') },
   { key = 'j',     mods = mod.SUPER_REV, action = act.ActivatePaneDirection('Down') },
   { key = 'h',     mods = mod.SUPER_REV, action = act.ActivatePaneDirection('Left') },
   { key = 'l',     mods = mod.SUPER_REV, action = act.ActivatePaneDirection('Right') },
   {
      key = 'p',
      mods = mod.SUPER_REV,
      action = act.PaneSelect({ alphabet = '1234567890', mode = 'SwapWithActiveKeepFocus' }),
   },

   -- panes: scroll pane
   { key = 'u',        mods = mod.SUPER, action = act.ScrollByLine(-5) },
   { key = 'd',        mods = mod.SUPER, action = act.ScrollByLine(5) },
   -- WEZ-CFG-04：alt-screen 应用（herdr/Claude Code/vim）里 Shift+PageUp/Down
   -- 透传给应用；宿主 ScrollByPage 在 alt screen 下是静默空操作。
   {
      key = 'PageUp',
      mods = platform.is_mac and 'NONE' or 'SHIFT',
      action = wezterm.action_callback(function(window, pane)
         if pane:is_alt_screen_active() then
            window:perform_action(act.SendString('\x1b[5;2~'), pane)
         else
            window:perform_action(act.ScrollByPage(-0.75), pane)
         end
      end),
   },
   {
      key = 'PageDown',
      mods = platform.is_mac and 'NONE' or 'SHIFT',
      action = wezterm.action_callback(function(window, pane)
         if pane:is_alt_screen_active() then
            window:perform_action(act.SendString('\x1b[6;2~'), pane)
         else
            window:perform_action(act.ScrollByPage(0.75), pane)
         end
      end),
   },

   -- key-tables --
   -- resizes fonts
   {
      key = 'f',
      mods = 'LEADER',
      action = act.ActivateKeyTable({
         name = 'resize_font',
         one_shot = false,
         timeout_milliseconds = 1000,
      }),
   },
   -- resize panes
   {
      key = 'p',
      mods = 'LEADER',
      action = act.ActivateKeyTable({
         name = 'resize_pane',
         one_shot = false,
         timeout_milliseconds = 1000,
      }),
   },

   -- 浮层入口（WZ-16/WEZ-UX-01）：herdr 抓鼠标时键盘仍可达。
   { key = 'k', mods = 'LEADER', action = act.ShowKeybinds },
   { key = 'm', mods = 'LEADER', action = act.ShowMainMenu },
   { key = 's', mods = 'LEADER', action = act.OpenSettings },
   { key = 'w', mods = 'LEADER', action = act.ShowWallpaperOverlay },

   -- plugins: workspace switcher (智能项目切换；插件缺失时跳过，WEZ-CFG-03)
   {
      key = 's',
      mods = mod.SUPER,
      action = workspace_switcher and workspace_switcher.switch_workspace() or act.Nop,
   },

   -- plugins: resurrect (会话保存/恢复；按键时才加载，插件缺失时跳过)
   {
      key = 'S',
      mods = mod.SUPER_REV,
      action = plugins.resurrect_available and wezterm.action_callback(function(win, _pane)
         local resurrect = plugins.resurrect()
         if not resurrect then
            win:toast_notification('WezTerm', 'resurrect 插件加载失败，未保存', nil, 3000)
            return
         end
         resurrect.state_manager.save_state(resurrect.workspace_state.get_workspace_state())
         win:toast_notification('WezTerm', 'Workspace 状态已保存', nil, 2500)
      end) or act.Nop,
   },
   {
      key = 'r',
      mods = mod.SUPER_REV,
      action = plugins.resurrect_available and wezterm.action_callback(function(win, pane)
         local resurrect = plugins.resurrect()
         if not resurrect then
            win:toast_notification('WezTerm', 'resurrect 插件加载失败，无法恢复', nil, 3000)
            return
         end
         resurrect.fuzzy_loader.fuzzy_load(win, pane, function(id, _label)
            local state_type = string.match(id, '^([^/]+)')
            id = string.match(id, '([^/]+)$')
            id = string.match(id, '(.+)%..+$')

            local opts = {
               relative = true,
               restore_text = true,
               on_pane_restore = resurrect.tab_state.default_on_pane_restore,
            }

            if state_type == 'workspace' then
               local state = resurrect.state_manager.load_state(id, 'workspace')
               resurrect.workspace_state.restore_workspace(state, opts)
            elseif state_type == 'window' then
               local state = resurrect.state_manager.load_state(id, 'window')
               resurrect.window_state.restore_window(pane:window(), state, opts)
            elseif state_type == 'tab' then
               local state = resurrect.state_manager.load_state(id, 'tab')
               resurrect.tab_state.restore_tab(pane:tab(), state, opts)
            end
         end)
      end) or act.Nop,
   },
}

if platform.is_linux then
   -- 截图（flameshot）与 AI 图片粘贴脚本只在 Linux 上存在；Windows 用 Win+Shift+S 截图，
   -- 图片直接 Ctrl+V 给 Claude Code/Codex。
   table.insert(keys, {
      key = 'S',
      mods = 'ALT|SHIFT',
      action = wezterm.action_callback(function(window, _pane)
         local ok = wezterm.background_child_process({ 'flameshot', 'gui', '--clipboard' })
         if ok == false then
            window:toast_notification('WezTerm', '无法启动 Flameshot', nil, 3000)
         end
      end),
   })
   table.insert(keys, {
      key = 'V',
      mods = 'ALT|SHIFT',
      action = wezterm.action_callback(function(window, pane)
         local success, stdout, stderr = wezterm.run_child_process({
            wezterm.home_dir .. '/.local/bin/ai-image-paste',
         })

         if success then
            local path = stdout:gsub('%s+$', '')
            window:perform_action(act.SendString(path), pane)
            window:toast_notification('图片已附加', path, nil, 2500)
         else
            local message = (stderr or '剪贴板中没有可用图片'):gsub('%s+$', '')
            window:toast_notification('图片粘贴失败', message, nil, 3500)
         end
      end),
   })
end

if not platform.is_mac then
   -- 原始 PageUp/PageDown 留给 less、vim 等程序；常用标签页与字体操作匹配 Ubuntu。
   -- 主键盘的 Ctrl++ 实际按的是 Ctrl+Shift+=，上报为带 SHIFT 的 '+'；小键盘的不带。
   local ubuntu_keys = {
      { key = 'PageUp', mods = 'CTRL', action = act.ActivateTabRelative(-1) },
      { key = 'PageDown', mods = 'CTRL', action = act.ActivateTabRelative(1) },
      { key = '=', mods = 'CTRL', action = act.IncreaseFontSize },
      { key = '+', mods = 'CTRL', action = act.IncreaseFontSize },
      { key = '+', mods = 'CTRL|SHIFT', action = act.IncreaseFontSize },
      { key = '-', mods = 'CTRL', action = act.DecreaseFontSize },
      { key = '0', mods = 'CTRL', action = act.ResetFontSize },
   }
   for _, binding in ipairs(ubuntu_keys) do
      table.insert(keys, binding)
   end
   for index = 1, 9 do
      -- 标签直达走 leader 层，裸 Alt+数字留给 readline/应用（GX-10）。
      table.insert(keys, { key = tostring(index), mods = 'LEADER', action = act.ActivateTab(index - 1) })
   end

   -- 用户键位没有 Shift 变体合成（上游 #1906）：Windows 与 X11 把 Ctrl+Shift+[ 报成 '{'，
   -- 只绑 '[' 按不到。带 SHIFT 的标点/数字键位补一份美式布局的 Shift 字符。'-' 与 '='
   -- 不在此列：Ctrl+_（撤销）要留给 shell，Ctrl++ 是字号放大。
   local shifted = { ['['] = '{', [']'] = '}', ['\\'] = '|', ['0'] = ')', ['9'] = '(' }
   local aliases = {}
   for _, binding in ipairs(keys) do
      if shifted[binding.key] and binding.mods and binding.mods:find('SHIFT', 1, true) then
         table.insert(aliases, { key = shifted[binding.key], mods = binding.mods, action = binding.action })
      end
   end
   for _, binding in ipairs(aliases) do
      table.insert(keys, binding)
   end
else
   -- macOS 保留原有的 Cmd+←/→/Backspace 行首、行尾、清行映射。
   table.insert(keys, { key = 'LeftArrow', mods = mod.SUPER, action = act.SendString '\u{1b}OH' })
   table.insert(keys, { key = 'RightArrow', mods = mod.SUPER, action = act.SendString '\u{1b}OF' })
   table.insert(keys, { key = 'Backspace', mods = mod.SUPER, action = act.SendString '\u{15}' })
end

-- stylua: ignore
local key_tables = {
   resize_font = {
      { key = 'k',      action = act.IncreaseFontSize },
      { key = 'j',      action = act.DecreaseFontSize },
      { key = 'r',      action = act.ResetFontSize },
      { key = 'Escape', action = 'PopKeyTable' },
      { key = 'q',      action = 'PopKeyTable' },
   },
   resize_pane = {
      { key = 'k',      action = act.AdjustPaneSize({ 'Up', 1 }) },
      { key = 'j',      action = act.AdjustPaneSize({ 'Down', 1 }) },
      { key = 'h',      action = act.AdjustPaneSize({ 'Left', 1 }) },
      { key = 'l',      action = act.AdjustPaneSize({ 'Right', 1 }) },
      { key = 'Escape', action = 'PopKeyTable' },
      { key = 'q',      action = 'PopKeyTable' },
   },
}

local mouse_bindings = {
   -- 应用启用鼠标协议时保留完整事件给 Herdr；Shift 拖选由宿主负责。
   { event = { Down = { streak = 1, button = 'Left' } }, mods = 'SHIFT',
     action = act.SelectTextAtMouseCursor('Cell') },
   { event = { Drag = { streak = 1, button = 'Left' } }, mods = 'SHIFT',
     action = act.ExtendSelectionToMouseCursor('Cell') },
   { event = { Up = { streak = 1, button = 'Left' } }, mods = 'SHIFT',
     action = act.CompleteSelection('ClipboardAndPrimarySelection') },
   { event = { Down = { streak = 1, button = 'Left' } }, mods = 'CTRL',
     mouse_reporting = false, action = act.Nop },
   { event = { Up = { streak = 1, button = 'Left' } }, mods = 'CTRL',
     mouse_reporting = false, action = act.OpenLinkAtMouseCursor },
   -- Ctrl+滚轮 调整字体大小
   {
      event = { Down = { streak = 1, button = { WheelUp = 1 } } },
      mods = 'CTRL',
      action = act.IncreaseFontSize,
   },
   {
      event = { Down = { streak = 1, button = { WheelDown = 1 } } },
      mods = 'CTRL',
      action = act.DecreaseFontSize,
   },
}

return {
   disable_default_key_bindings = true,
   -- disable_default_mouse_bindings = true,
   -- 与 Herdr 的 Ctrl+B 分开；Linux、Windows、WSL 使用同一个终端前缀。
   leader = { key = 'Space', mods = 'CTRL|SHIFT', timeout_milliseconds = 1000 },
   keys = keys,
   key_tables = key_tables,
   mouse_bindings = mouse_bindings,
}
