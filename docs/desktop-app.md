# The WoW Coach app: install it and use it

WoW Coach is a normal app on your computer. It has a chat with your coach, quick buttons for
common questions, and a small card that can stay on top of the game. It answers with your own
ChatGPT plan, and it also answers the questions you type in the game's
[Coach panel](coach-panel.md), by itself, while you play.

This guide starts from zero. You do not need to have used a terminal before.

**Jump to:** [Windows](#windows) | [Linux](#linux) | [macOS](#macos) |
[After the install](#first-start) | [Daily use](#daily-use) |
[Update](#update-to-a-new-version) | [Uninstall](#uninstall)

## What you need

- A ChatGPT plan that allows it (**Plus** or **Pro**). Answers come out of your plan's usage,
  like using ChatGPT itself.
- World of Warcraft: Forever, installed with the Battle.net app.
- About 10 minutes.
- Nothing else to buy. wow-coach and the tools below are free.

## Two words you will see

- **Terminal**: a window where you type a line of text and press Enter to run it. On Windows
  it is called **PowerShell**. You only need it for the install and the update.
- **uv**: a small free tool that downloads and installs Python programs. WoW Coach is a Python
  program, so you install uv first, then ask uv to install WoW Coach.

When this guide shows a line in a grey box, copy the whole line, paste it into the terminal
and press Enter. To paste, try Ctrl+V, or Ctrl+Shift+V (many Linux terminals need this one),
or right-click in the window.

## Windows

### 1. Open PowerShell

1. Click the Start button (or press the Windows key).
2. Type `PowerShell`.
3. Click **Windows PowerShell**.

**You should see:** a window (blue or black) with a line of text ending in `>` and a blinking
cursor. That is where you type.

### 2. Install uv

Paste this line and press Enter. It is the official uv install line for Windows from
[uv's install page](https://docs.astral.sh/uv/getting-started/installation/):

```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

The part `-ExecutionPolicy ByPass` lets this one run work even if Windows normally blocks
scripts. It changes nothing else on your computer. (uv's page notes that changing the
execution policy allows running a script from the internet, so only use this line from uv's
own page.)

**You should see:** a few lines of text while uv downloads, and then the prompt comes back.

Now **close the PowerShell window and open a new one** (step 1 again). Programs only notice a
newly installed tool in a window opened afterwards.

Check it:

```
uv --version
```

**You should see:** `uv` and a version number, for example `uv 0.12.24`.

**If it didn't work:** see [Troubleshooting](troubleshooting.md#the-app-wont-install-or-start).

### 3. Install WoW Coach

Paste this line and press Enter:

```
uv tool install "wow-coach[desktop] @ git+https://github.com/RayanBayat/wow-coach@v0.9.0"
```

It downloads WoW Coach and the parts it needs (about 100 MB, once). This can take a few
minutes.

**You should see:** a list of installed parts and, at the end, `Installed 3 executables:
wow-coach, wow-coach-app, wow-coach-mcp`. We checked the install line with the Linux
version; the Windows output is the same kind of text.

If you also see a warning that a folder "is not on your PATH", run this line, then close
PowerShell and open a new one:

```
uv tool update-shell
```

### 4. Start it

```
wow-coach app
```

**You should see:** the WoW Coach window opens. On Windows, keep this PowerShell window open
while you use the app: closing it closes WoW Coach. (After the next section you can start WoW
Coach from the Start menu instead, and you can close PowerShell.)

If PowerShell says `wow-coach` is not recognized, see
[Troubleshooting](troubleshooting.md#wow-coach-command-not-found).

Now continue with [First start](#first-start).

## Linux

These steps use the standard terminal of your desktop (on KDE it is called **Konsole**, on
GNOME simply **Terminal**; the names vary).

### 1. Open a terminal

1. Open your application menu and search for `Terminal` (or `Konsole`).
2. Click it.

**You should see:** a window with a line of text ending in `$` and a blinking cursor.

### 2. Install uv

Paste this line and press Enter. It is the official uv install line for Linux from
[uv's install page](https://docs.astral.sh/uv/getting-started/installation/):

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If your computer says `curl` is not found, the same page gives this line, which uses `wget`
instead:

```
wget -qO- https://astral.sh/uv/install.sh | sh
```

**You should see:** a few lines of text while uv downloads, and then the prompt comes back.

Now **close the terminal and open a new one**. Programs only notice a newly installed tool in
a window opened afterwards.

Check it:

```
uv --version
```

**You should see:** `uv` and a version number, for example `uv 0.12.24`.

### 3. Install WoW Coach

```
uv tool install "wow-coach[desktop] @ git+https://github.com/RayanBayat/wow-coach@v0.9.0"
```

It downloads WoW Coach and the parts it needs (about 100 MB, once).

**You should see:** a list of installed parts and, at the end, `Installed 3 executables:
wow-coach, wow-coach-app, wow-coach-mcp`.

If you also see a warning that a folder "is not on your PATH", run this line, then close the
terminal and open a new one:

```
uv tool update-shell
```

### 4. Start it

```
wow-coach app
```

**You should see:** the WoW Coach window opens. The terminal stays busy while the app runs;
that is normal. (After the next section you can start WoW Coach from your app menu instead.)

If the terminal says `wow-coach: command not found`, see
[Troubleshooting](troubleshooting.md#wow-coach-command-not-found).

Your game runs under Wine (through Battle.net, Lutris or Proton)? That is fine: WoW Coach only
needs to find the game's `_forever_` folder, and
[Install the addon](install-the-addon.md#step-2-find-the-game-folder) lists the usual paths.

Now continue with [First start](#first-start).

## macOS

macOS works, with fewer extras. We have not tested these steps on a Mac. What is different:

- Open **Terminal** (it is in Applications, in the Utilities folder) and use the same uv line
  as on Linux (the `curl` line above).
- The install line (step 3) and the start line (`wow-coach app`) are the same.
- The Setup page has no "App menu" or "Start with my computer" buttons yet. Start WoW Coach
  from the terminal each time.
- There is no global overlay key yet. Use the **Overlay** button or the tray icon's menu (see
  [Overlay mode](#overlay-mode-the-coach-on-top-of-your-game)).

## First start

The first time, WoW Coach looks for your game by itself.

### If it cannot find the game

**You should see:** a small window titled "I can't find your game yet", with the buttons
**Choose the game folder…**, **Try again** and **Quit**.

1. Click **Choose the game folder…**.
2. Pick the folder called `_forever_`. It is inside your World of Warcraft folder. Usual
   places: `C:\Program Files (x86)\World of Warcraft\_forever_` (Windows) and
   `~/Games/battlenet/drive_c/Program Files (x86)/World of Warcraft/_forever_` (Linux with
   Wine or Lutris). More help: [Install the addon, step 2](install-the-addon.md#step-2-find-the-game-folder).
3. If your game is on a disk that is not connected yet, connect it and click **Try again**.

The folder must contain a `WTF` folder (the game creates it the first time you start the game).
If it does not, WoW Coach tells you.

**You should see:** the main WoW Coach window. On the left is a list of pages: **Coach**,
**Notebook**, **Settings**, **ChatGPT**, **Setup** and **Privacy**.

### Setup: get the game and the app ready

Click **Setup**. It is a checklist; each item is a card with a status icon and, when there is
something to do, a button.

1. **Game folder**: shows the folder in use. Click **Change…** to pick another one. After
   changing it, click **Restart WoW Coach**.
2. **CoachLink addon**: if it is missing or old, click **Install CoachLink** (or **Update
   CoachLink**). WoW Coach downloads the addon that matches the app and puts it in your game.
   **You should see:** "CoachLink 0.9.0 is installed and up to date." (after the
   work finishes, the card says to restart WoW).
3. **Answers folder**: if it says the folder does not exist, click **Create it**. (Installing
   CoachLink creates it too.) This is the folder where the coach puts its answers for the game.
4. **"Save for the coach" key**: this card only explains what to do in the game. See the next
   section.
5. **App menu** (not on macOS): click **Add to my app menu**. On Windows this puts "WoW Coach"
   in the Start menu. On Linux it puts it in your application menu. Next time you can start the
   app like any other app.
6. **Start with my computer** (not on macOS, optional): click **Start when I log in**. WoW Coach
   then starts quietly in the tray when you log in. Click **Stop starting** to undo it.
7. **Overlay hotkey**: shows whether the overlay key works (see
   [Overlay mode](#overlay-mode-the-coach-on-top-of-your-game)).

If the App menu or Start with my computer card shows a command and says "WoW Coach was started
from a temporary place, so a shortcut would stop working later", you started the app a
different way than this guide (for example with `uvx`). Install it once with the command the
card shows. The command in the card has no version number in it; the install line in this
guide does.

### Restart WoW once

A new addon (and a new key) is only noticed when the game starts fresh.

1. If WoW is running, quit it completely from the game menu (Esc, then **Exit Game**).
2. Start it again from the Battle.net app.
3. On the character screen, click **AddOns** (bottom left) and check that **CoachLink** is
   ticked.

### Give the coach a key to save your character

The game only hands your character to other programs when it saves. A key does that for you.

1. In WoW: **Options → Keybindings → CoachLink → Save for the coach (reloads the interface)**.
2. Pick any free key.

**You should see:** the key next to that line. If the line is missing, you have not restarted
WoW completely yet (a `/reload` is not enough).

## Sign in with ChatGPT

1. In WoW Coach, click **ChatGPT**.
2. Click **Continue with ChatGPT**.
3. Your browser opens OpenAI's own sign-in page. Sign in and approve **wow-coach** there.
   WoW Coach never sees your password. If you want to read first what is sent, click **What is
   sent?** (or open **Privacy**; the full text is the [privacy notice](privacy.md)).

**You should see:** in WoW Coach, "Finish signing in in your browser..." while you wait, then
"You're signed in. The coach now answers with your ChatGPT plan." and a small message titled
"You're using your ChatGPT plan". Click **Got it**. You will not see that message again.

Your sign-in is kept in your computer's password store (for example Windows Credential
Manager, macOS Keychain, KDE Wallet or GNOME Keyring), never in a file. WoW Coach has no
charges of its own. You can sign out any time on the ChatGPT page with **Sign out**.

If the browser did not open, use **Open the sign-in page again** or **Copy link** on the same
page. More: [Troubleshooting](troubleshooting.md#sign-in-problems).

## Daily use

Start the game, log in, and start WoW Coach (from the Start menu or app menu, or with
`wow-coach app`). If you chose **Start when I log in**, it is already running in the tray.

- **Ask:** click **Coach**, type in the box at the bottom and press Enter (Shift+Enter starts a
  new line), or click a quick button: **What next?**, **Check my gear**, **Spells to train**,
  **Plan my session**, **Why did I die?**, **Make gold**, **Explain a word**.
  **You should see:** a typing bubble, then the coach's answer.
- **Your whole history:** the chat shows everything you and your coaches said about this
  character: what you asked in the app and in the game, the answers, and your chats with your
  Claude coach (`claude --agent wow-coach`), which WoW Coach reads from Claude Code's own
  session files every minute. Each message says where it came from ("from the game", "from your
  Claude coach", "from another app"). Long replies fold behind **Show more**. WoW Coach's own
  coach reads the recent messages too, so it knows what you already talked about. Don't want
  that? Turn off **Use my Claude coach chats** in Settings.
- **Game data: 12 min old:** the top of the page shows how fresh the coach's view of your
  character is. The game only hands your character to other programs when it saves: when you
  log out, type `/reload`, or press your **Save for the coach** key.
- **The app updates by itself.** There is no refresh button: WoW Coach notices every time the
  game saves, shows a short "Got your latest game data" note in the chat and updates "Game data:
  ... old". To make the game save, press your **Save for the coach** key in WoW, type `/coach`,
  or type `/reload`. The game reloads for a few seconds. (The key does nothing during a fight,
  so a reload never catches you mid-combat. Press it again when the fight is over.) A question
  you type is always asked right away, with the data from the last save.

  Why can't the app make the game save alone? Programs that press keys in your game break
  Blizzard's rules, so WoW Coach never does it. One key press from you is all it needs.
- **After a save:** in **Settings**, under **Coach on its own**, **When the game saves** has
  three choices: **Off**, **Tell me what's worth knowing** and **Tell me and update my next
  steps**. With the last one, after each save the chat shows a slim line, **Game saved: next
  steps updated**, and the coach updates your next steps. More:
  [the coach window guide](coach-window.md#when-the-game-saves).
- **Sources and lookups:** while the coach works, the typing bubble says what it is doing
  ("Searched the Warcraft Wiki for ..."). Under each answer you see **Sources**: small link
  buttons with the page title (or the website) that open the page in your browser when you click
  them. Point at one to see the whole link. The links come from what the coach really searched
  and read, never from links the AI wrote. **What the coach looked up (3)** unfolds to a list of
  what it checked, including when it saved your notes. Point at an answer to see when it came.
  Both also show for older answers in the history.
- **Keep on top of the game:** the button **Keep on top of the game** (at the top of the Coach
  page) opens a small card that stays above the game window and shows the newest answer. Drag
  it where you like; it remembers the spot. It never takes the keyboard away from the game.
  While it is open the button says **Hide the small card**. It only stays above the game when
  the game runs in a window or borderless window (see
  [Troubleshooting](troubleshooting.md#the-small-card-hides-behind-the-game)).
- **Questions from the game:** ask in the game's Coach panel as before. WoW Coach answers
  within a few seconds, shows the answer, and can notify you. The answer is
  also in the Coach panel after your next `/reload`.
- **Notebook:** click **Notebook** to see what the coach remembers about you and your
  character (its notes). Click **Reload** to read the files again right now. The **At a glance**
  card at the top sums up the important parts. On a wide window the same card also sits beside
  the chat on the Coach page.
- **App size:** in **Settings**, the **App size** card makes the whole app smaller or bigger
  (70 % to 130 %), for example to fit next to the game. Click **Restart now** to see the new
  size.
- **Closing the window** keeps the coach running in the tray (the small icons near your clock).
  The first time, a message tells you so. To stop it completely, use **Quit** in the tray
  icon's menu. Starting WoW Coach again just brings the window back: only one copy runs at a
  time.

## Overlay mode: the coach on top of your game

The overlay shows the coach as a see-through panel over the game, so you can ask a question
without leaving it. Press one key and it appears with the cursor already in the question
box. Type, press Enter, read the answer. Press **Esc** or the same key again and it goes away,
and your game gets the keyboard back.

- **The key:** **Ctrl+Shift+Space** at first. Change it in **Settings → Overlay**: click the
  box next to **Show or hide the overlay**, then press the keys you want. There you can also
  choose how see-through the panel is (**How solid it is**: 60 to 100 %; 92 % at first).
- **Other ways in:** the **Overlay** button at the top of the Coach page, and **Show or hide
  the overlay** in the tray icon's menu.
- **Move and resize it:** drag the bar at the top to move it; drag its edges or corners to
  resize it. It remembers its size and place. The first time it opens on the right part of
  the screen. **Open the full app** (in the bar) closes the overlay and opens the big window.
- **It is just a window.** The overlay is a normal window of WoW Coach that stays on top of
  other windows. It never touches the game: it sends no keys to the game, reads nothing from
  it and does not ask it to do anything. For the game to look right under it, run WoW as a
  window or borderless window (not true full screen).
- **It never grabs the keyboard by itself.** It takes the keyboard only when you ask for it
  (the key, the tray menu or the button). A new answer does not pop it up; the notification
  and the **Keep on top of the game** card are for that.

### How the key works on your system

| System | What happens |
|---|---|
| **Linux** | WoW Coach asks your desktop for the key through the *global shortcuts portal* (the polite way programs ask the desktop to tell them about a key). The first time, KDE shows its own question; say yes. The desktop needs to know the app, so add WoW Coach to your app menu first (**Setup → App menu**). |
| **Windows** | WoW Coach asks Windows for the key. If another program already uses it, pick a different one in Settings. |
| **macOS** | There is no global key yet. Use the tray menu or the Overlay button, or the command below. |

### If the key does not work: set it by hand

The command **`wow-coach-app --toggle-overlay`** always works, on every system. It tells the
running WoW Coach to show or hide the overlay (and starts WoW Coach first if it is not
running). The **Setup** page has an **Overlay hotkey** card that shows whether the key works
and, if not, the exact command for your computer with a **Copy command** button, and a
**Try again** button that asks your desktop for the key again. Then give the command a key:

**KDE (Linux):**

1. Open **System Settings → Keyboard → Shortcuts**.
2. Choose **Add New → Command or Script**.
3. Paste the command from the Setup card and pick your key (for example Ctrl+Shift+Space).

**Other Linux desktops:** open the keyboard settings, look for "custom shortcuts", add one and
paste the same command as its command.

**Windows:** first try another key in **Settings → Overlay**. Or make a shortcut to the command
(right-click the desktop, **New → Shortcut**, paste the command from the Setup card), then
open the shortcut's **Properties** and click in its **Shortcut key** box to pick a key.

**macOS:** there is no tested way. The Setup card suggests the Shortcuts app with a "Run Shell
Script" action running the command; we have not tested that.

## The other pages

- **Settings:** the **Coach tools** (let the coach look things up, search the web, update your
  notebook, and show what it looked up; all on at first), notifications, answering game questions by itself, when the
  coach tells you what changed after the game saves (**Coach on its own**: off, a free
  notification, or a notification plus advice), the **Overlay** key and how see-through it is,
  **App size**, and what is shared with the AI. Changes save by themselves. More:
  [the coach window guide](coach-window.md#when-the-game-saves).
- **ChatGPT:** your sign-in, how many questions you asked in the last hour and day,
  **Manage usage** (your ChatGPT settings), the model, and **Sign out**.
- **Setup:** the checks above, any time, and the **Overlay hotkey** card. After changing the
  game folder, click **Restart WoW Coach**.
- **Privacy:** what stays on your computer and what is sent to ChatGPT. The full text:
  [privacy notice](privacy.md).

## Update to a new version

New versions are announced on the
[Releases page](https://github.com/RayanBayat/wow-coach/releases/latest). The install line has
a version in it (the `@v0.9.0` at the end), and `uv tool upgrade` keeps to the constraints you
installed with (this is what [uv's documentation](https://docs.astral.sh/uv/concepts/tools/)
says), so it does not move you to a newer tag. To update, install again with the new version:

1. Quit WoW Coach: **Quit** in the tray icon's menu.
2. Run the install line again, with the new version number in place of `v0.9.0`, and `--force`
   after `install`:

   ```
   uv tool install --force "wow-coach[desktop] @ git+https://github.com/RayanBayat/wow-coach@v0.9.0"
   ```

3. Start WoW Coach again. Click **Setup**. If the **CoachLink addon** card says an update is
   ready, click **Update CoachLink**.
4. Restart WoW completely.

**You should see:** the CoachLink card says "CoachLink (new version) is installed and up to
date." Your shortcuts, settings, notes and sign-in stay as they were.

We could not test an update from one tag to the next (the next tag does not exist yet).
The commands above follow uv's documentation.

## Uninstall

Do the steps you need, in this order.

1. In WoW Coach, click **Setup**, and click **Remove** on the **App menu** card and **Stop
   starting** on the **Start with my computer** card (if you added them). Uninstalling does
   not remove these shortcuts by itself.
2. Click **ChatGPT**, then **Sign out**. This removes the sign-in from your computer's
   password store. To be sure OpenAI forgets it too, open ChatGPT, go to Settings and remove
   wow-coach from your connected apps (this is what the app itself tells you).
3. Quit WoW Coach (**Quit** in the tray icon's menu).
4. Remove the program:

   ```
   uv tool uninstall wow-coach
   ```

   **You should see:** `Uninstalled 3 executables: wow-coach, wow-coach-app, wow-coach-mcp`.
5. Optional: delete what is left behind.

| What | Windows | Linux | macOS |
|---|---|---|---|
| WoW Coach's own files (your notes, chat history, settings) | `%LOCALAPPDATA%\wow-coach` | `~/.local/share/wow-coach` (or under `$XDG_DATA_HOME` if you set it) | `~/Library/Application Support/wow-coach` |
| The addon, in the game folder | `_forever_\Interface\AddOns\CoachLink` and `CoachLink_Advice` | the same, inside your Wine prefix | the same |

To remove the addon, close the game and delete the `CoachLink` and `CoachLink_Advice` folders
(see [Install the addon](install-the-addon.md#uninstalling)). The game also keeps a saved
character file called `CoachLink.lua` in its `SavedVariables` folder; deleting it is optional.

## If something doesn't work

See [Troubleshooting](troubleshooting.md#the-wow-coach-app). Common ones:

- `wow-coach` is "not found" or "not recognized".
- "The desktop app needs the desktop extra".
- The app cannot find the game folder.
- CoachLink is not loaded in the game, or the "Save for the coach" key is missing.
- There is no tray icon (some Linux desktops).
- The overlay key does nothing, or the small card hides behind the game.

You prefer the old browser window? `wow-coach app --browser` still opens it
([guide](coach-window.md)).
