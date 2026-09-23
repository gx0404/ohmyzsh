local wezterm = require('wezterm')
-- --config-file 指向独立配置时，也从同目录加载模块，避免混入本机旧配置。
package.path = wezterm.config_dir .. '/?.lua;' .. wezterm.config_dir .. '/?/init.lua;' .. package.path

local Config = require('config')
local general = require('config.general')

require('utils.backdrops')
   -- :set_focus('#000000')
   -- :set_images_dir(require('wezterm').home_dir .. '/Pictures/Wallpapers/')
   :set_images()
   :set_default('nord-space.png')
   -- fork（批 13）：壁纸管理浮层的持久化选择优先于硬编码默认
   :set_default_from_sidecar()

require('events.status').setup({ date_format = '%a %H:%M', herdr_app_mode = general.herdr_app_mode })
require('events.tab-title').setup({ hide_active_tab_unseen = true, unseen_icon = 'numbered_box' })
require('events.new-tab-button').setup()
require('events.gui-startup').setup()

return Config:init()
   :append(require('config.appearance'))
   :append(require('config.bindings'))
   :append(require('config.domains'))
   :append(require('config.fonts'))
   :append(general)
   :append(require('config.launch')).options
