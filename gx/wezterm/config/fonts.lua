local wezterm = require('wezterm')
local platform = require('utils.platform')

-- local font_family = 'Maple Mono NF'
local font_family = 'JetBrainsMono Nerd Font'
-- local font_family = 'CartographCF Nerd Font'

-- 本机沿用旧字号 12（源机器为 12.5）。
local font_size = platform.is_mac and 12 or 12

return {
   font = wezterm.font_with_fallback({
      { family = font_family, weight = 'Regular' },
      -- 正文字重保持 Regular，选中和标题交给 TUI 自己强调；CJK 轻微校正高度。
      { family = 'Noto Sans CJK SC', weight = 'Regular', scale = 1.05 },
   }),
   font_size = font_size,

   --ref: https://wezfurlong.org/wezterm/config/lua/config/freetype_pcf_long_family_names.html#why-doesnt-wezterm-use-the-distro-freetype-or-match-its-configuration
   freetype_load_target = 'Normal', ---@type 'Normal'|'Light'|'Mono'|'HorizontalLcd'
   freetype_render_target = 'Normal', ---@type 'Normal'|'Light'|'Mono'|'HorizontalLcd'
}
