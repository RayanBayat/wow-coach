# Troubleshooting

Find your problem, try the fixes in order. Using the WoW Coach app? Start with
[the app section](#the-wow-coach-app).

# The WoW Coach app

These are the problems people hit with the [WoW Coach app](desktop-app.md). Try the fixes in
order.

## The app won't install or start

1. **Windows, uv install line:** use the exact line from the guide (it contains
   `-ExecutionPolicy ByPass`). A plain PowerShell window may refuse to run downloaded scripts;
   that option allows just this one run. If your computer belongs to a work or school and
   still blocks it, ask whoever manages it. We could not test that case.
2. **Linux, `curl` not found:** use the `wget` line from the guide instead.
3. **No internet or a blocked download:** the install downloads about 100 MB from GitHub and
   from Python's package site. Check your connection and run the install line again.
4. Make sure you pasted the whole install line, including the quotes and the `@v...` at the end.

## `wow-coach` command not found

The terminal says `wow-coach: command not found` (Linux, macOS) or `wow-coach is not
recognized` (Windows).

1. Close the terminal completely and open a new one. A window only sees a newly installed tool
   after it is reopened.
2. Run this line, close the terminal again and open a new one:

   ```
   uv tool update-shell
   ```

   It adds the folder where uv puts its programs to your PATH (the list of folders your
   computer looks in for programs).
3. Run `uv --version`. If that fails too, install uv again (see the guide, step 2 of your
   system).

## "The desktop app needs the desktop extra"

The message reads: "The desktop app needs the desktop extra: uv tool install ... Opening the
browser window instead." It means the app's window parts (Qt) are not installed. You probably
installed wow-coach without `[desktop]`. Run the install line from the guide again, with
`--force` after `install`:

```
uv tool install --force "wow-coach[desktop] @ git+https://github.com/RayanBayat/wow-coach@v0.9.0"
```

The program `wow-coach-app` prints a similar message ("WoW Coach needs its desktop extra").
The command printed inside those messages has no version number; use the line above.

## The app says it can't find the game folder

You see "I can't find your game yet" (or, when the app starts at login, a tray message "WoW
Coach can't find your game yet. Click to choose it.").

1. Click **Choose the game folder…** and pick the folder called `_forever_`.
   [Where it usually is](install-the-addon.md#step-2-find-the-game-folder).
2. If it says the folder "does not look like the game folder (it has no WTF folder)", you
   picked the wrong folder, or you have never started the game. Start the game once, then try
   again.
3. If the game is on a disk that is not connected yet, connect it and click **Try again**.

## CoachLink is not loaded in the game

`/coach` does nothing, or the Setup page says CoachLink is missing.

1. In WoW Coach, open **Setup**. Click **Install CoachLink** (or **Update CoachLink**).
2. Quit the game completely and start it again. `/reload` is not enough for a new addon.
3. On the character screen, click **AddOns** (bottom left). Tick **CoachLink**. If it is marked
   out of date, tick the box that loads out-of-date addons (the exact wording may vary).
4. Still nothing? Check that this file exists:
   `_forever_\Interface\AddOns\CoachLink\CoachLink.toc`. More:
   [`/coach` does nothing](#coach-does-nothing-or-unknown-command).

## The "Save for the coach" key is not in the key list

The game only notices a new key after a full restart. Quit the game completely and start it
again, then open **Options → Keybindings → CoachLink**. A `/reload` is not enough.

## "Game data" stays old

The game only hands over your character when it saves. Press your **Save for the coach** key,
or type `/coach` or `/reload`. The key does nothing during a fight ("Can't save during a
fight"); press it again afterwards.

## No tray icon (some Linux desktops)

Some desktops, such as plain GNOME, show no tray icons. Then closing the WoW Coach window
quits the app. Leave the window open, or minimize it, while you play.

## The overlay key does nothing

1. Open **Setup** and read the **Overlay hotkey** card. It tells you if the key works.
2. **Linux:** add WoW Coach to your app menu first (**Setup → App menu**), then click **Try
   again** on the Overlay hotkey card. The first time, your desktop (KDE) asks you to allow the
   key; say yes.
3. **Windows:** another program may use that key. Pick another in **Settings → Overlay**.
4. **Any system, by hand:** give the command `wow-coach-app --toggle-overlay` a key in your
   system's keyboard settings. The Setup card shows the exact command with a **Copy command**
   button. Steps: [Overlay mode](desktop-app.md#if-the-key-does-not-work-set-it-by-hand).
5. **macOS:** there is no global key yet. Use the **Overlay** button or the tray menu.

## The small card hides behind the game

The **Keep on top of the game** card and the overlay are normal windows. A game in true full
screen (exclusive full screen) can cover them. Set the game to windowed or borderless window
mode in its graphics options.

## Sign-in problems

1. **The browser did not open:** on the **ChatGPT** page click **Open the sign-in page again**,
   or **Copy link** and paste it into your browser. The sign-in expires within 5 minutes; if
   it does, click **Hide this** and start again.
2. **"Your password keychain could not be used. It may be locked: unlock it and try again."**
   The app keeps your sign-in in your computer's password store (Windows Credential Manager,
   macOS Keychain, KDE Wallet or GNOME Keyring). Unlock it (on Linux, your wallet or keyring
   asks for your password; log in again if needed) and try again.
3. **Answers stop with a usage message:** the coach uses your ChatGPT plan's usage. **Manage
   usage** on the ChatGPT page opens your ChatGPT settings.
4. **Sign out says OpenAI did not confirm it:** you are signed out of wow-coach on this
   computer. To be sure, open ChatGPT, go to Settings and remove wow-coach from your connected
   apps.

## The shortcut is refused: "started from a temporary place"

Adding WoW Coach to the app menu or to log-in makes a shortcut that remembers where the program
is. If you started the app with `uvx`, that place is temporary, so the Setup page refuses
and shows an install command. Install WoW Coach once with the guide's install line, start it
again, and add the shortcut.

# The addon and the other ways

## `/coach` does nothing, or "unknown command"

The addon isn't loaded.

1. Check the file exists: `_forever_\Interface\AddOns\CoachLink\CoachLink.toc`
   (see [Install the addon](install-the-addon.md)).
2. Quit the game fully and start it again. `/reload` does not load new addons.
3. On the character screen, click **AddOns** and tick CoachLink. If it is marked out of date,
   tick **Load out of date AddOns** (the wording may vary).

## `/coach copy` shows an empty window or no window

1. Type `/coach` first, wait for the reload, then `/coach copy`.
2. Type `/coach help` to see which commands your version has. If `copy` isn't listed, update the
   addon to the latest release.

## I pasted my character but the AI says it can't see anything

The AI app cannot see your game. Paste the text from `/coach copy` into the message itself.

## `wow-coach check` says the game folder wasn't found

1. Easiest: run `uvx --from git+https://github.com/RayanBayat/wow-coach@v0.9.0 wow-coach setup`.
   It asks for the folder, checks it and remembers it. If it says a saved folder does not
   exist any more (you moved the game), run it again.
2. Or find the `_forever_` folder (see [Install the addon](install-the-addon.md), step 2)
   and set `WOW_COACH_WOW_DIR` to that folder. In an app config it goes in the `env` section
   (see [Connect an AI app](connect-an-ai-app.md)). In a terminal: on Windows PowerShell
   `$env:WOW_COACH_WOW_DIR = "D:\Games\World of Warcraft\_forever_"`, on macOS and Linux
   `export WOW_COACH_WOW_DIR="/path/to/_forever_"`.

## `wow-coach check` says no CoachLink.lua was found

The addon has not saved yet. Start the game, log in, type `/coach`, wait for the reload, run the
check again. The file is only written on `/coach`, `/reload` or a clean logout. Killing the game
loses the save.

## The AI shows old data

The character is only as fresh as your last `/coach`, `/reload` or logout. Type `/coach` and ask
again.

## "uvx: command not found" (or "not recognized")

1. Close the terminal or the AI app completely and open it again. Programs only see newly
   installed tools after a restart.
2. Run `uv --version`. If that fails, install uv again ([step 1](connect-an-ai-app.md)).
3. In the app config use the full path of `uvx`: `where uvx` on Windows, `which uvx` on macOS
   and Linux.

## The AI app doesn't show wow-coach tools

1. Check the config file is valid JSON/TOML: a missing comma or quote breaks it. Paste it into
   a JSON checker if unsure.
2. Quit the app completely (not just the window) and start it again.
3. Run the `check` command from [Connect an AI app](connect-an-ai-app.md) to confirm the helper
   itself works.
4. Check the app's logs. Claude Desktop writes MCP logs to `%APPDATA%\Claude\logs` (Windows),
   `~/Library/Logs/Claude` (macOS) or `~/.config/Claude/logs` (Linux).

## The first start is very slow

The first run downloads the helper. Later runs are fast.

## "Addon read errors" in the character report

One part of your character could not be read, for example after a game patch. The rest still
works. Please report it at https://github.com/RayanBayat/wow-coach/issues with the error text.

## The addon shows as "out of date"

The interface number in `CoachLink.toc` is for the game build it was made for. Tick **Load out of
date AddOns** on the character screen, and check for a new release.

## Still stuck

Open an issue at https://github.com/RayanBayat/wow-coach/issues. Include your system (Windows,
macOS or Linux), which way you use, and the output of the `check` command. Do not include
passwords or private information.
