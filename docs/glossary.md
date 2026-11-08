# Glossary

**Addon**: a small add-on for the game, made of a folder of text files. The game loads it at
startup. CoachLink is an addon.

**AI agent**: an AI app that can also run commands and read files on your computer (Claude Code,
Codex, Gemini CLI, Cursor...).

**Agent Skill**: a folder with a `SKILL.md` instructions file that an AI agent loads when it is
relevant. See https://agentskills.io.

**Environment variable**: a named value you hand to a program, such as `WOW_COACH_WOW_DIR`.

**Folder path**: the address of a folder, such as `C:\Program Files (x86)\World of Warcraft`.

**JSON / TOML**: two ways of writing settings as text. AI apps use them for config files.

**MCP (Model Context Protocol)**: the standard way for AI apps to use small helper programs on
your computer. wow-coach is one such helper.

**SavedVariables**: files the game writes in the `WTF` folder when you log out or `/reload`.
CoachLink keeps your character there.

**Terminal**: a window where you type a line of text and press Enter to run it. Windows:
PowerShell. macOS: Terminal. Linux: Terminal or Konsole (the name depends on your desktop).

**PowerShell**: the terminal that comes with Windows. Open it from the Start menu by typing
`PowerShell`.

**PATH**: the list of folders your computer looks in when you type a program's name. If a
program is "not found" right after installing, its folder may not be on the PATH yet.
`uv tool update-shell` fixes that.

**Tray**: the small icons near your clock. WoW Coach keeps running there when you close its
window. Right-click or click its icon for the menu (**Open WoW Coach**, **Quit**). Some Linux
desktops have no tray.

**Overlay**: a see-through WoW Coach panel on top of your game, so you can ask the coach
without leaving the game. It is only a window; it never touches the game.

**Hotkey**: a key (or a key combination such as Ctrl+Shift+Space) that works from any program,
even while the game is in front. WoW Coach uses one to show or hide the overlay.

**Password store (keychain)**: the safe place your computer keeps passwords and sign-ins (for
example Windows Credential Manager, macOS Keychain, KDE Wallet, GNOME Keyring). WoW Coach keeps
your ChatGPT sign-in there, not in a file.

**Wine / Proton prefix**: on Linux, the folder where Wine or Proton keeps a fake Windows
`C:` drive (called `drive_c`). The game lives inside it.

**uv**: a free tool that downloads and runs Python programs. Here it installs and runs wow-coach.

**`_forever_`**: the folder inside World of Warcraft that holds WoW Forever.
