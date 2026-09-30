<h2 align="center">My WezTerm Config</h2>

<p align="center">
  <a href="https://github.com/KevinSilvester/wezterm-config/stargazers">
    <img alt="Stargazers" src="https://img.shields.io/github/stars/KevinSilvester/wezterm-config?style=for-the-badge&logo=starship&color=C9CBFF&logoColor=D9E0EE&labelColor=302D41">
  </a>
  <a href="https://github.com/KevinSilvester/wezterm-config/issues">
    <img alt="Issues" src="https://img.shields.io/github/issues/KevinSilvester/wezterm-config?style=for-the-badge&logo=gitbook&color=B5E8E0&logoColor=D9E0EE&labelColor=302D41">
  </a>
  <a href="https://github.com/KevinSilvester/wezterm-config/actions/workflows/lint.yml">
    <img alt="Build" src="https://img.shields.io/github/actions/workflow/status/KevinSilvester/wezterm-config/lint.yml?&style=for-the-badge&logo=githubactions&label=CI&color=A6E3A1&logoColor=D9E0EE&labelColor=302D41">
  </a>
</p>

![screenshot](./.github/screenshots/wezterm.gif)

---

### Features

- [**Background Image Selector**](https://github.com/KevinSilvester/wezterm-config/blob/master/utils/backdrops.lua)

  - Cycle images
  - Fuzzy search for image
  - Toggle background image

  > See: [key bindings](#background-images) for usage

- [**GPU Adapter Selector**](https://github.com/KevinSilvester/wezterm-config/blob/master/utils/gpu_adapter.lua)

  > :bulb: Only works if the [`front_end`](https://github.com/KevinSilvester/wezterm-config/blob/master/config/appearance.lua#L8) option is set to `WebGpu`.

  A small utility to select the best GPU + Adapter (graphics API) combo for your machine.

  GPU + Adapter combo is selected based on the following criteria:

  1.  <details>
      <summary>Best GPU available</summary>

      `Discrete` > `Integrated` > `Other` (for `wgpu`'s OpenGl implementation on Discrete GPU) > `Cpu`
      </details>

  2.  <details>
      <summary>Best graphics API available (based off my very scientific scroll a big log file in Neovim test 😁)</summary>

      > :bulb:<br>
      > The available graphics API choices change based on your OS.<br>
      > These options correspond to the APIs the `wgpu` crate (which powers WezTerm's gui in `WebGpu` mode)<br>
      > currently has support implemented for.<br>
      > See: <https://github.com/gfx-rs/wgpu#supported-platforms> for more info

      - Windows: `Dx12` > `Vulkan` > `OpenGl`
      - Linux: `Vulkan` > `OpenGl`
      - Mac: `Metal`

      </details>

---

### Getting Started

- ##### Requirements:

  - <details>
      <summary><b>WezTerm</b></summary>

    Minimum Version: `20240127-113634-bbcac864`<br>
    Recommended Version: [`Nightly`](https://github.com/wez/wezterm/releases/nightly)

    [Official Installation Page](https://wezfurlong.org/wezterm/installation.html)

    **Windows**

    - <details>
      <summary>Install Stable</summary>

      - Install with Scoop (non-portable)

        ```sh
        scoop bucket add extras
        scoop install wezterm
        ```

      - Install with Scoop (portable)

        ```sh
        scoop bucket add k https://github.com/KevinSilvester/scoop-bucket
        scoop install k/wezterm
        ```

      - Install with winget

        ```sh
        winget install wez.wezterm
        ```

      - Install with choco

        ```sh
        choco install wezterm -y
        ```
      </details>

    - <details>
      <summary>Install Nightly</summary>

      - Install with Scoop (non-portable)

        ```sh
        scoop bucket add versions
        scoop install wezterm-nightly
        ```

      - Install with Scoop (portable)

        ```sh
        scoop bucket add k https://github.com/KevinSilvester/scoop-bucket
        scoop install k/wezterm-nightly
        ```
      </details>

    > :bulb:<br>
    > Toast notifications don't work in non-portable installations.<br>
    > See issue <https://github.com/wez/wezterm/issues/5166> for more details
  
    ---

    **MacOS**

    - <details>
      <summary>Install Stable</summary>

      - Install with Homebrew

        ```sh
        brew install --cask wezterm
        ```

      - Install with MacPort

        ```sh
        sudo port selfupdate
        sudo port install wezterm
        ```
      </details>

    - <details>
      <summary>Install Nighlty</summary>

      - Install with Homebrew

        ```sh
        brew install --cask wezterm@nightly
        ```

      - Upgrade with Homebrew

        ```sh
        brew install --cask wezterm@nightly --no-quarantine --greedy-latest
        ```
      </details>

    ---

    **Linux**

    Refer to the Linux installation page.<br>
    <https://wezfurlong.org/wezterm/install/linux.html>

    </details>

  - <details>
    <summary>JetBrainsMono Nerd Font</summary>

    Install with Homebrew (Macos)

    ```sh
    brew install --cask font-jetbrains-mono-nerd-font
    ```

    Install with Scoop (Windows)

    ```sh
    scoop bucket add nerd-fonts
    scoop install JetBrainsMono-NF
    ```

    > More Info:
    >
    > - <https://www.nerdfonts.com/#home>
    > - <https://github.com/ryanoasis/nerd-fonts?#font-installation>
    </details/>

&nbsp;

- ##### Steps:

  1.  ```sh
      # On Windows and Unix systems
      git clone https://github.com/KevinSilvester/wezterm-config.git ~/.config/wezterm
      ```
  2.  And Done!!! 🎉🎉

&nbsp;

- ##### Things You Might Want to Change:

  - [./config/domains.lua](./config/domains.lua) for custom SSH domains (WSL distros are listed automatically)
  - The default shell: pick it in the Settings overlay (<kbd>LEADER</kbd>+<kbd>s</kbd>, section "Shell"),
    see [Default Shell](#default-shell)

---

### Default Shell

[./utils/shells.lua](./utils/shells.lua) finds the installed shells without starting any process
(it only checks whether files exist) and [./config/launch.lua](./config/launch.lua) turns them into
`launch_menu` entries (<kbd>F3</kbd>, right click on the `+` tab button):

| Shell | `default_shell` id | Looked up in |
| ----- | ------------------ | ------------ |
| GX Zsh | `gx-zsh` | the GX Shell install next to `wezterm.executable_dir` |
| PowerShell 7 | `pwsh` | `PATH` (Store app aliases included), `%ProgramFiles%\PowerShell\7` and `7-preview`, scoop |
| Windows PowerShell 5.1 | `powershell` | `%SystemRoot%\System32\WindowsPowerShell\v1.0` |
| Command Prompt | `cmd` | `%ComSpec%` |
| Git Bash | `git-bash` | the Git for Windows root of `git.exe` on `PATH`, Program Files, `%LOCALAPPDATA%\Programs\Git`, scoop |
| MSYS2 UCRT64 | `msys2-ucrt64` | `C:\msys64`, `C:\tools\msys64`, scoop, an MSYS2 `usr\bin` on `PATH` (never the GX private runtime) |
| Nushell | `nu` | `PATH`, `%ProgramFiles%\nu\bin`, scoop |
| WSL distros | `wsl:<Distro>` | `wezterm.default_wsl_domains()` via [./utils/wsl.lua](./utils/wsl.lua) |
| Zsh / Bash (Linux) | `zsh` / `bash` | `PATH` |
| Fish / Bash / Nushell / Zsh (MacOs) | `fish` / `bash` / `nu` / `zsh` | fixed list, not checked (Fish and Nushell in `/opt/homebrew/bin`) |

Only Store app-execution aliases under `WindowsApps` count without opening; any other file that
cannot be opened (a dead `PATH` entry, an empty drive) counts as missing.
[./utils/wsl.lua](./utils/wsl.lua) is shared by `config/domains.lua` and `config/launch.lua`: once
distros are found, `wsl.exe` runs once per GUI process; an empty or failed listing is retried by
config evaluations after 5 minutes.

The Settings overlay (<kbd>LEADER</kbd>+<kbd>s</kbd>; the menus' "Default Shell…" and the last entry of
the `+` right-click list open its Shell section directly) stores the choice as `default_shell` in
`gui-settings.json` next to `wezterm.lua`, or in `$XDG_CONFIG_HOME/wezterm` (default
`~/.config/wezterm`) for a `~/.wezterm.lua` config; [./utils/gui-settings.lua](./utils/gui-settings.lua)
resolves it the same way WezTerm does. Choosing GX Zsh removes the key. Without a valid choice the
default falls back to GX Zsh, then PowerShell 7, then Windows PowerShell 5.1 (Linux: GX Zsh, then
Zsh; MacOs: Fish), which is always the first shell in the launch menu, so on MacOs Fish now comes
before Bash. A WSL choice sets `default_domain`. Every
launch menu entry pins its own domain, and every shell entry carries `GX_SHELL_ID` (the `herdr` entry
does not), so PowerShell opened from a WSL tab is still the local PowerShell.

Inside the GX Shell install the event `gx-default-shell-changed` also runs
`bin\herdr.exe --gx-set-default-shell <absolute shell path>` so new herdr panes follow the choice,
unless herdr uses a custom config. herdr takes a single executable, and the toast says what that
means: a WSL choice gives herdr the default WSL distro, MSYS2 UCRT64 gives it an MSYS-environment
bash, and a system zsh on Linux points herdr at GX Zsh (the herdr server's zsh environment would
load the GX profile anyway).

---

### All Key Bindings

Linux and Windows share one scheme built on <kbd>Ctrl</kbd>+<kbd>Shift</kbd>, the Ubuntu terminal
convention. Bare <kbd>Alt</kbd> keys (readline/zsh <kbd>Alt</kbd>+<kbd>f</kbd>/<kbd>b</kbd>/<kbd>d</kbd>/<kbd>.</kbd>/<kbd>Backspace</kbd>)
always reach the shell, and <kbd>Ctrl</kbd>+<kbd>C</kbd> (interrupt), <kbd>Ctrl</kbd>+<kbd>V</kbd> (image paste in
agent CLIs), <kbd>Ctrl</kbd>+<kbd>B</kbd> (herdr prefix) and <kbd>Ctrl</kbd>+<kbd>_</kbd> (undo in readline, zsh,
emacs and nano; typed as <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>-</kbd>) are never bound.

- On Windows and Linux
  - <kbd>SUPER</kbd> ⇨ <kbd>Ctrl</kbd>+<kbd>Shift</kbd>
  - <kbd>SUPER_REV</kbd> ⇨ <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>
- On MacOs
  - <kbd>SUPER</kbd> ⇨ <kbd>Super</kbd>
  - <kbd>SUPER_REV</kbd> ⇨ <kbd>Super</kbd>+<kbd>Ctrl</kbd>
- On all platforms: <kbd>LEADER</kbd> ⇨ <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd> <sub>(1 second)</sub>

On MacOs the tables below apply with these differences: the page scroll keys are plain
<kbd>PageUp</kbd>/<kbd>PageDown</kbd>, the <kbd>SUPER</kbd>+<kbd>LeftArrow</kbd>/<kbd>RightArrow</kbd>/<kbd>Backspace</kbd>
line keys stay, and there is no <kbd>Ctrl</kbd>+<kbd>PageUp</kbd>/<kbd>PageDown</kbd>, no
<kbd>Ctrl</kbd>+<kbd>=</kbd>/<kbd>+</kbd>/<kbd>-</kbd>/<kbd>0</kbd> and no <kbd>LEADER</kbd>+<kbd>1</kbd>…<kbd>9</kbd>.
Three changes of GX Shell 0.2.0 apply to MacOs as well: <kbd>SUPER_REV</kbd>+<kbd>w</kbd> asks before
closing a tab, the window size keys moved from <kbd>SUPER</kbd>+<kbd>=</kbd>/<kbd>-</kbd> to
<kbd>LEADER</kbd>+<kbd>=</kbd>/<kbd>-</kbd>, and <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd>/<kbd>V</kbd> (screenshot,
image paste) are bound on Linux only. The launch menu order changed too, see [Default Shell](#default-shell).

> WezTerm reports <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>[</kbd> as `{` on Windows and X11, so on those
> platforms every <kbd>SUPER</kbd>/<kbd>SUPER_REV</kbd> binding on `[ ] \ 0 9` is also bound to its US-layout
> shifted character (`{ } | ) (`).

#### Miscellaneous/Useful

| Keys                              | Action                                      |
| --------------------------------- | ------------------------------------------- |
| <kbd>F1</kbd>                     | `ActivateCopyMode`                          |
| <kbd>F2</kbd>                     | `ActivateCommandPalette`                    |
| <kbd>F3</kbd>                     | `ShowLauncher`                              |
| <kbd>F4</kbd>                     | `ShowLauncher` <sub>(tabs only)</sub>       |
| <kbd>F5</kbd>                     | `ShowLauncher` <sub>(workspaces only)</sub> |
| <kbd>F8</kbd>                     | Send <kbd>Ctrl</kbd>+<kbd>R</kbd> (Atuin history) |
| <kbd>F11</kbd>                    | `ToggleFullScreen`                          |
| <kbd>F12</kbd>                    | `ShowDebugOverlay`                          |
| <kbd>SUPER</kbd>+<kbd>f</kbd>     | Search Text                                 |
| <kbd>SUPER_REV</kbd>+<kbd>u</kbd> | Open URL                                    |
| <kbd>LEADER</kbd>+<kbd>m</kbd>    | `ShowMainMenu`                              |
| <kbd>LEADER</kbd>+<kbd>s</kbd>    | `OpenSettings` <sub>(default shell, theme, font)</sub> |
| <kbd>LEADER</kbd>+<kbd>k</kbd>    | `ShowKeybinds`                              |

&nbsp;

#### Copy+Paste

| Keys                                          | Action               |
| --------------------------------------------- | -------------------- |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>c</kbd> | Copy to Clipboard    |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>v</kbd> | Paste from Clipboard |

Linux only: <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd> takes a Flameshot screenshot and
<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> pastes the path of the clipboard image saved by
`~/.local/bin/ai-image-paste`.

&nbsp;

#### Cursor Movements (MacOs only)

| Keys                                   | Action                                                     |
| -------------------------------------- | ---------------------------------------------------------- |
| <kbd>SUPER</kbd>+<kbd>LeftArrow</kbd>  | Move cursor to Line Start                                  |
| <kbd>SUPER</kbd>+<kbd>RightArrow</kbd> | Move cursor to Line End                                    |
| <kbd>SUPER</kbd>+<kbd>Backspace</kbd>  | Clear Line <sub>(does not work in PowerShell or cmd)</sub> |

&nbsp;

#### Tabs

##### Tabs: Spawn+Close

| Keys                              | Action                                            |
| --------------------------------- | ------------------------------------------------- |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>t</kbd> | `SpawnTab` <sub>(DefaultDomain, default shell)</sub> |
| <kbd>SUPER_REV</kbd>+<kbd>t</kbd> | `SpawnTab` <sub>(DefaultDomain)</sub>             |
| <kbd>SUPER_REV</kbd>+<kbd>w</kbd> | `CloseCurrentTab` <sub>(asks first)</sub>         |

##### Tabs: Navigation

| Keys                                                   | Action               |
| ------------------------------------------------------ | -------------------- |
| <kbd>SUPER</kbd>+<kbd>[</kbd> / <kbd>Ctrl</kbd>+<kbd>PageUp</kbd>   | Previous Tab |
| <kbd>SUPER</kbd>+<kbd>]</kbd> / <kbd>Ctrl</kbd>+<kbd>PageDown</kbd> | Next Tab     |
| <kbd>SUPER_REV</kbd>+<kbd>[</kbd>                      | Move Tab Left        |
| <kbd>SUPER_REV</kbd>+<kbd>]</kbd>                      | Move Tab Right       |
| <kbd>LEADER</kbd>+<kbd>1</kbd>…<kbd>9</kbd>             | Go to Tab 1…9        |

<sub>Windows and Linux only: <kbd>Ctrl</kbd>+<kbd>PageUp</kbd>/<kbd>PageDown</kbd> and <kbd>LEADER</kbd>+<kbd>1</kbd>…<kbd>9</kbd>.</sub>

##### Tabs: Toggle Tab-bar

| Keys                          | Action         |
| ----------------------------- | -------------- |
| <kbd>SUPER</kbd>+<kbd>9</kbd> | Toggle tab bar |

##### Tabs: Title

| Keys                              | Action             |
| --------------------------------- | ------------------ |
| <kbd>SUPER</kbd>+<kbd>0</kbd>     | Rename Current Tab |
| <kbd>SUPER_REV</kbd>+<kbd>0</kbd> | Undo Rename        |

&nbsp;

#### Windows

| Keys                                  | Action               |
| ------------------------------------- | -------------------- |
| <kbd>SUPER</kbd>+<kbd>n</kbd>         | `SpawnWindow`        |
| <kbd>LEADER</kbd>+<kbd>=</kbd>        | Increase Window Size |
| <kbd>LEADER</kbd>+<kbd>-</kbd>        | Decrease Window Size |
| <kbd>SUPER_REV</kbd>+<kbd>Enter</kbd> | Maximize Window      |

<sub>The window size keys sit on the leader layer because <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>-</kbd> is the shell's
undo key and <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>=</kbd> is <kbd>Ctrl</kbd>+<kbd>+</kbd>.</sub>

&nbsp;

#### Font Size

| Keys                                                         | Action             |
| ------------------------------------------------------------ | ------------------ |
| <kbd>Ctrl</kbd>+<kbd>=</kbd> / <kbd>Ctrl</kbd>+<kbd>+</kbd> | `IncreaseFontSize` |
| <kbd>Ctrl</kbd>+<kbd>-</kbd>                                 | `DecreaseFontSize` |
| <kbd>Ctrl</kbd>+<kbd>0</kbd>                                 | `ResetFontSize`    |
| <kbd>Ctrl</kbd>+Mouse Wheel                                  | Increase/Decrease  |

<sub><kbd>Ctrl</kbd>+<kbd>+</kbd> is <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>=</kbd> on the main keyboard or
<kbd>Ctrl</kbd> with the keypad <kbd>+</kbd>. The <kbd>Ctrl</kbd> keyboard keys are Windows and Linux only;
<kbd>Ctrl</kbd>+Mouse Wheel and <kbd>LEADER</kbd>+<kbd>f</kbd> work everywhere.</sub>

&nbsp;

#### Panes

##### Panes: Split Panes

| Keys                               | Action                                           |
| ---------------------------------- | ------------------------------------------------ |
| <kbd>SUPER</kbd>+<kbd>\\</kbd>     | `SplitVertical` <sub>(CurrentPaneDomain)</sub>   |
| <kbd>SUPER_REV</kbd>+<kbd>\\</kbd> | `SplitHorizontal` <sub>(CurrentPaneDomain)</sub> |

##### Panes: Zoom+Close Pane

| Keys                              | Action                                     |
| --------------------------------- | ------------------------------------------ |
| <kbd>SUPER</kbd>+<kbd>Enter</kbd> | `TogglePaneZoomState`                      |
| <kbd>SUPER</kbd>+<kbd>w</kbd>     | `CloseCurrentPane` <sub>(asks first)</sub> |

<sub>Closing a pane or tab does not ask while only an idle shell runs in it
(`skip_close_confirmation_for_processes_named`; on Windows the list also has `zsh.exe`, `bash.exe` and
the other `.exe` shell names, MSYS2's `env.exe` and GX Zsh's gitstatusd). herdr and other programs
still ask.</sub>

##### Panes: Navigation

| Keys                              | Action                  |
| --------------------------------- | ----------------------- |
| <kbd>SUPER_REV</kbd>+<kbd>k</kbd> | Move to Pane (Up)       |
| <kbd>SUPER_REV</kbd>+<kbd>j</kbd> | Move to Pane (Down)     |
| <kbd>SUPER_REV</kbd>+<kbd>h</kbd> | Move to Pane (Left)     |
| <kbd>SUPER_REV</kbd>+<kbd>l</kbd> | Move to Pane (Right)    |
| <kbd>SUPER_REV</kbd>+<kbd>p</kbd> | Swap with selected Pane |

##### Panes: Scroll Pane

| Keys                                                 | Action                               |
| ---------------------------------------------------- | ------------------------------------ |
| <kbd>SUPER</kbd>+<kbd>u</kbd>                        | Scroll Lines up <sub>5 lines</sub>   |
| <kbd>SUPER</kbd>+<kbd>d</kbd>                        | Scroll Lines down <sub>5 lines</sub> |
| <kbd>Shift</kbd>+<kbd>PageUp</kbd>                   | Scroll Page up                       |
| <kbd>Shift</kbd>+<kbd>PageDown</kbd>                 | Scroll Page down                     |

<sub>In alt-screen applications (herdr, vim, Claude Code) the page keys are passed through as
<kbd>Shift</kbd>+<kbd>PageUp</kbd>/<kbd>PageDown</kbd>. On Windows and Linux plain <kbd>PageUp</kbd>/<kbd>PageDown</kbd>
always go to the application; on MacOs plain <kbd>PageUp</kbd>/<kbd>PageDown</kbd> are the page scroll keys.</sub>

&nbsp;

#### Plugins

| Keys                              | Action                                                  |
| --------------------------------- | ------------------------------------------------------- |
| <kbd>SUPER</kbd>+<kbd>s</kbd>     | smart_workspace_switcher: switch workspace              |
| <kbd>SUPER_REV</kbd>+<kbd>S</kbd> | resurrect: save the workspace <sub>(loaded on first use)</sub> |
| <kbd>SUPER_REV</kbd>+<kbd>r</kbd> | resurrect: restore a saved state                        |

<sub>Plugins load only from WezTerm's data dir (pre-seeded by the installers); when one is missing its keys do nothing.</sub>

&nbsp;

#### Background Images

| Keys                           | Action                       |
| ------------------------------ | ---------------------------- |
| <kbd>LEADER</kbd>+<kbd>/</kbd> | Select Random Image          |
| <kbd>LEADER</kbd>+<kbd>.</kbd> | Cycle to next Image          |
| <kbd>LEADER</kbd>+<kbd>,</kbd> | Cycle to previous Image      |
| <kbd>LEADER</kbd>+<kbd>i</kbd> | Fuzzy select Image           |
| <kbd>LEADER</kbd>+<kbd>b</kbd> | Toggle background focus mode |
| <kbd>LEADER</kbd>+<kbd>w</kbd> | Wallpaper manager overlay    |

&nbsp;

#### Key Tables

> See: <https://wezfurlong.org/wezterm/config/key-tables.html>

| Keys                           | Action        |
| ------------------------------ | ------------- |
| <kbd>LEADER</kbd>+<kbd>f</kbd> | `resize_font` |
| <kbd>LEADER</kbd>+<kbd>p</kbd> | `resize_pane` |

##### Key Table: `resize_font`

| Keys           | Action                          |
| -------------- | ------------------------------- |
| <kbd>k</kbd>   | `IncreaseFontSize`              |
| <kbd>j</kbd>   | `DecreaseFontSize`              |
| <kbd>r</kbd>   | `ResetFontSize`                 |
| <kbd>q</kbd>   | `PopKeyTable` <sub>(exit)</sub> |
| <kbd>Esc</kbd> | `PopKeyTable` <sub>(exit)</sub> |

##### Key Table: `resize_pane`

| Keys           | Action                                         |
| -------------- | ---------------------------------------------- |
| <kbd>k</kbd>   | `AdjustPaneSize` <sub>(Direction: Up)</sub>    |
| <kbd>j</kbd>   | `AdjustPaneSize` <sub>(Direction: Down)</sub>  |
| <kbd>h</kbd>   | `AdjustPaneSize` <sub>(Direction: Left)</sub>  |
| <kbd>l</kbd>   | `AdjustPaneSize` <sub>(Direction: Right)</sub> |
| <kbd>q</kbd>   | `PopKeyTable` <sub>(exit)</sub>                |
| <kbd>Esc</kbd> | `PopKeyTable` <sub>(exit)</sub>                |

---

### References/Inspirations

- <https://github.com/rxi/lume>
- <https://github.com/catppuccin/wezterm>
- <https://github.com/wez/wezterm/discussions/628#discussioncomment-1874614>
- <https://github.com/wez/wezterm/discussions/628#discussioncomment-5942139>
