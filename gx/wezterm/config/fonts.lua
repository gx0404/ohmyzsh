local wezterm = require('wezterm')
local platform = require('utils.platform')

-- local font_family = 'Maple Mono NF'
local font_family = 'JetBrainsMono Nerd Font'
-- local font_family = 'CartographCF Nerd Font'

-- 本机沿用旧字号 12（源机器为 12.5）。
local font_size = platform.is_mac and 12 or 12

local fallback = {
   { family = font_family, weight = 'Regular' },
   -- 正文字重保持 Regular，选中和标题交给 TUI 自己强调；CJK 轻微校正高度。
   { family = 'Noto Sans CJK SC', weight = 'Regular', scale = 1.05 },
}

-- 末位兜底：Noto Sans CJK 2.001 不含 Unicode 14 新增的 U+9FFD–9FFF 等码位，缺字形时
-- wezterm 会弹 "No fonts contain glyphs" 告警。Unifont 覆盖整个 BMP，只在前面都
-- 没有字形时才会被选中。仅当字体文件存在才加入，避免没装的机器反而多一条
-- 「字体未找到」告警。盲文与方块字符由 wezterm 自绘（custom_block_glyphs），不走这里。
local unifont = io.open('/usr/share/fonts/truetype/unifont/unifont.ttf', 'r')
if unifont then
   unifont:close()
   table.insert(fallback, { family = 'Unifont' })
end

return {
   font = wezterm.font_with_fallback(fallback),
   font_size = font_size,

   --ref: https://wezfurlong.org/wezterm/config/lua/config/freetype_pcf_long_family_names.html#why-doesnt-wezterm-use-the-distro-freetype-or-match-its-configuration
   freetype_load_target = 'Normal', ---@type 'Normal'|'Light'|'Mono'|'HorizontalLcd'
   freetype_render_target = 'Normal', ---@type 'Normal'|'Light'|'Mono'|'HorizontalLcd'
}
