local wezterm = require('wezterm')
local platform = require('utils.platform')

-- local font_family = 'Maple Mono NF'
local font_family = 'JetBrainsMono Nerd Font'
-- local font_family = 'CartographCF Nerd Font'

-- 本机沿用旧字号 12（源机器为 12.5）。
local font_size = platform.is_mac and 12 or 12

return {
   font = wezterm.font_with_fallback({
      { family = font_family, weight = 'DemiBold' },
      -- CJK 字形放大到填满双宽单元格，消除汉字间的空隙（2×10px 单元格 / 17px 原始步进）。
      { family = 'Noto Sans CJK SC', weight = 'Bold', scale = 1.18 },
   }),
   font_size = font_size,

   --ref: https://wezfurlong.org/wezterm/config/lua/config/freetype_pcf_long_family_names.html#why-doesnt-wezterm-use-the-distro-freetype-or-match-its-configuration
   freetype_load_target = 'Normal', ---@type 'Normal'|'Light'|'Mono'|'HorizontalLcd'
   freetype_render_target = 'Normal', ---@type 'Normal'|'Light'|'Mono'|'HorizontalLcd'
}
