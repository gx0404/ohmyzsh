local platform = require('utils.platform')
local backdrops = require('utils.backdrops')
local colors = require('colors.custom')

-- 各平台的渲染后端只在这里调整。GNOME X11 下优先稳定性；Windows 未经实机 A/B
-- （paint 日志）前同样保持 OpenGL。WebGPU 仅在隔离配置中做 A/B 测试。
---@type table<PlatformType, 'WebGpu' | 'OpenGL' | 'Software'>
local front_end = { linux = 'OpenGL', windows = 'OpenGL', mac = 'OpenGL' }

return {
   max_fps = 60,
   front_end = front_end[platform.os],
   underline_thickness = '1.5pt',

   -- cursor：非 Constant 的闪烁缓动会让空闲窗口按 animation_fps 持续重绘，
   -- Constant 只在亮灭切换时各画一帧。
   animation_fps = 10,
   cursor_blink_ease_in = 'Constant',
   cursor_blink_ease_out = 'Constant',
   default_cursor_style = 'BlinkingBlock',
   cursor_blink_rate = 650,

   -- color scheme
   colors = colors,

   -- background: pass in `true` if you want wezterm to start with focus mode on (no bg images)
   background = backdrops:initial_options(false),

   -- scrollbar
   enable_scroll_bar = true,

   -- tab bar
   enable_tab_bar = true,
   hide_tab_bar_if_only_one_tab = false,
   use_fancy_tab_bar = false,
   tab_max_width = 32,
   show_tab_index_in_tab_bar = false,
   switch_to_last_active_tab_when_closing_tab = true,

   -- command palette
   command_palette_fg_color = '#b4befe',
   command_palette_bg_color = '#11111b',
   command_palette_font_size = 12,
   command_palette_rows = 25,

   -- window
   window_padding = {
      left = 10,
      right = 10,
      top = 8,
      bottom = 8,
   },
   adjust_window_size_when_changing_font_size = false,
   window_close_confirmation = 'NeverPrompt',
   window_frame = {
      active_titlebar_bg = '#090909',
      -- font = fonts.font,
      -- font_size = fonts.font_size,
   },
   -- inactive_pane_hsb = {
   --    saturation = 0.9,
   --    brightness = 0.65,
   -- },
   inactive_pane_hsb = {
      saturation = 0.85,
      brightness = 0.72,
   },

   visual_bell = {
      fade_in_function = 'EaseIn',
      fade_in_duration_ms = 250,
      fade_out_function = 'EaseOut',
      fade_out_duration_ms = 250,
      target = 'CursorColor',
   },
}
