local platform = require('utils.platform')

-- 空闲 shell 窗格关闭时不弹确认；窗格里的每个进程都在名单内才算空闲。Windows 进程名带
-- .exe，上游默认名单（zsh、bash……）匹配不到，这里补上；MSYS2 的 env.exe 会作为 bash
-- 的父进程留在窗格里；GX Zsh 的 Powerlevel10k 在 zsh 下常驻 gitstatusd（安装包
-- lib/gitstatus 里的文件没有扩展名）。herdr 等其他进程仍需确认。
local skip_close_confirmation = nil
if platform.is_win then
   skip_close_confirmation = {
      'bash', 'sh', 'zsh', 'fish', 'tmux', 'nu', 'nu.exe', 'cmd.exe', 'pwsh.exe', 'powershell.exe',
      'zsh.exe', 'bash.exe', 'sh.exe', 'fish.exe', 'gx-zsh.exe', 'env.exe',
      'gitstatusd-msys_nt-10.0-x86_64', 'gitstatusd-msys_nt-10.0-x86_64.exe',
   }
end

return {
   -- behaviours
   automatically_reload_config = true,
   -- GX 版本随自己的安装包升级；上游更新检查只会提示上游 WezTerm 版本。
   check_for_updates = false,
   skip_close_confirmation_for_processes_named = skip_close_confirmation,
   -- 界面文案语言（命令面板/菜单/浮层/CLI 帮助）；WEZTERM_LANG 环境变量优先级更高
   language = 'zh-CN',
   exit_behavior = 'CloseOnCleanExit', -- if the shell program exited with a successful status
   exit_behavior_messaging = 'Verbose',
   -- 状态内容按变化缓存；2 秒轮询可兼顾模式提示及时性和低重绘。
   status_update_interval = 2000,
   audible_bell = 'Disabled',
   hide_mouse_cursor_when_typing = true,
   mouse_wheel_scrolls_tabs = false,
   bypass_mouse_reporting_modifiers = 'SHIFT',

   -- GNOME X11 下固定使用 Fcitx4 的 XIM 服务，避免登录顺序变化导致 WezTerm 无法呼出输入法。
   use_ime = true,
   xim_im_name = 'fcitx',

   -- 本机（Ubuntu 20.04）没有 10808 代理服务，注入会导致所有网络请求连接拒绝；
   -- 部署本地代理后取消下面的注释即可恢复。
   -- set_environment_variables = {
   --    HTTP_PROXY = 'http://127.0.0.1:10808',
   --    HTTPS_PROXY = 'http://127.0.0.1:10808',
   --    ALL_PROXY = 'socks5://127.0.0.1:10808',
   --    NO_PROXY = 'localhost,127.0.0.1,::1',
   --    http_proxy = 'http://127.0.0.1:10808',
   --    https_proxy = 'http://127.0.0.1:10808',
   --    all_proxy = 'socks5://127.0.0.1:10808',
   --    no_proxy = 'localhost,127.0.0.1,::1',
   -- },

   scrollback_lines = 50000,

   hyperlink_rules = {
      -- Matches: a URL in parens: (URL)
      {
         regex = '\\((\\w+://\\S+)\\)',
         format = '$1',
         highlight = 1,
      },
      -- Matches: a URL in brackets: [URL]
      {
         regex = '\\[(\\w+://\\S+)\\]',
         format = '$1',
         highlight = 1,
      },
      -- Matches: a URL in curly braces: {URL}
      {
         regex = '\\{(\\w+://\\S+)\\}',
         format = '$1',
         highlight = 1,
      },
      -- Matches: a URL in angle brackets: <URL>
      {
         regex = '<(\\w+://\\S+)>',
         format = '$1',
         highlight = 1,
      },
      -- Then handle URLs not wrapped in brackets
      {
         regex = '\\b\\w+://\\S+[)/a-zA-Z0-9-]+',
         format = '$0',
      },
      -- implicit mailto link
      {
         regex = '\\b\\w+@[\\w-]+(\\.[\\w-]+)+\\b',
         format = 'mailto:$0',
      },
   },
}
