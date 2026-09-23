return {
   -- behaviours
   automatically_reload_config = true,
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

   -- herdr 应用模式：单 tab 且前台是 herdr 时自动隐藏宿主 tab bar，观感更接近
   -- Codex/Claude Code 桌面版等成熟商用软件；由 events/status.lua 的
   -- update-status 钩子读取生效。注意这不是 wezterm 原生 config 字段，wezterm
   -- 会忽略它；仅供 wezterm.lua 转发给 events.status.setup 使用。
   herdr_app_mode = true,

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
