# The WoW Coach app: your coach in its own window

WoW Coach is a normal app on your computer. It has a chat with your coach, quick buttons
for common questions, and a small card that can stay on top of the game. It answers with your
own ChatGPT plan.

It also answers the questions you type in the game's [Coach panel](coach-panel.md), by
itself, while you play. When you close the window, the coach keeps running next to your clock
(in the "tray"), so it can keep answering.

## What you need

- A ChatGPT plan that allows it (Plus or Pro). Answers come out of your plan's usage, like
  using ChatGPT itself.
- WoW Forever with the CoachLink addon. The app can install or update it for you (the
  **Setup** page).
- [uv](https://docs.astral.sh/uv/getting-started/installation/): a small free tool that
  installs Python programs. Its page has a one-line install for Windows, macOS and Linux.

## Install it (once)

1. Open a terminal (on Windows: PowerShell) and paste this line:

   ```
   uv tool install "wow-coach[desktop] @ git+https://github.com/RayanBayat/wow-coach@v0.9.0"
   ```

   It downloads WoW Coach and the parts it needs (about 100 MB, once).
2. Start it:

   ```
   wow-coach app
   ```

   (`wow-coach-app` does the same without a terminal, and is what the app-menu shortcut
   runs.) If WoW Coach can't find your game, it asks you to choose the `_forever_` folder.

   If the terminal says `wow-coach: command not found`, run `uv tool update-shell`, close the
   terminal, open a new one and try again.
3. In the app, open **Setup**:
   - **Add to my app menu**, so next time you can start WoW Coach like any other app.
   - **Start when I log in** (optional): WoW Coach then waits quietly in the tray.
   - If CoachLink is missing or old, click **Install CoachLink** (or **Update CoachLink**),
     then restart WoW.
4. Open **ChatGPT** and click **Continue with ChatGPT**. OpenAI's own page opens in your
   browser; approve **wow-coach** there. WoW Coach never sees your password. Your sign-in is
   kept in your computer's password store (for example Windows Credential Manager, macOS
   Keychain, KDE Wallet or GNOME Keyring), never in a file.
5. In WoW, give the coach a key: **Options → Keybindings → CoachLink → Save for the coach
   (reloads the interface)**. Pick any free key. (After updating the addon, restart the game
   once, or the key won't show up.)

## Use it

- **Ask:** type in the box at the bottom and press Enter (Shift+Enter starts a new line), or
  click a quick button: **What next?**, **Check my gear**, **Spells to train**, **Plan my
  session**, **Why did I die?**, **Make gold**, **Explain a word**.
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
- **Sources and lookups:** while the coach works, the typing bubble says what it is doing
  ("Searched the Warcraft Wiki for ..."). Under each answer you see **Sources**: small link
  buttons with the page title (or the website) that open the page in your browser when you click
  them. Point at one to see the whole link. The links come from what the coach really searched
  and read, never from links the AI wrote. **What the coach looked up (3)** unfolds to a list of
  what it checked, including when it saved your notes. Point at an answer to see when it came.
  Both also show for older answers in the history.
- **Keep on top of the game:** opens a small card that stays above the game window and shows
  the newest answer. Drag it where you like; it remembers the spot. It never takes the
  keyboard away from the game.
- **Questions from the game:** ask in the game's Coach panel as before. WoW Coach answers
  within a few seconds, shows the answer, and can notify you. The answer is
  also in the Coach panel after your next `/reload`.
- **Closing the window** keeps the coach running in the tray. To stop it completely, use
  **Quit** in the tray icon's menu. Starting WoW Coach again just brings the window back:
  only one copy runs at a time.

## Overlay mode: the coach on top of your game

The overlay shows the coach as a see-through panel over the game, so you can ask a question
without leaving it. Press one key and it appears with the cursor already in the question
box. Type, press Enter, read the answer. Press **Esc** or the same key again and it goes away,
and your game gets the keyboard back.

- **The key:** **Ctrl+Shift+Space** at first. Change it in **Settings → Overlay**. There you
  can also choose how see-through the panel is (60 to 100 %; 92 % at first).
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
and, if not, the exact command for your computer with a **Copy command** button. To give the
command a key:

1. On KDE: open **System Settings → Keyboard → Shortcuts**.
2. Choose **Add New → Command or Script**.
3. Paste the command from the Setup card and pick your key (for example Ctrl+Shift+Space).

On other Linux desktops, look for "custom shortcuts" in the keyboard settings and use the same
command. On Windows, make a shortcut to the command and set its **Shortcut key** in the
shortcut's Properties.

## The other pages

- **Settings:** the **Coach tools** (let the coach look things up, search the web, update your
  notebook, and show what it looked up; all on at first), notifications, answering game questions by itself, when the
  coach tells you what changed after the game saves (**Coach on its own**: off, a free
  notification, or a notification plus advice), the **Overlay** key and how see-through it is,
  and what is shared with the AI. Changes save
  by themselves. More: [the coach window guide](coach-window.md#when-the-game-saves).
- **App size** (in Settings): make the whole app smaller or bigger (70 % to 130 %), for
  example to fit next to the game. Click **Restart now** to see the new size.
- **ChatGPT:** your sign-in, how many questions you asked in the last hour and day,
  **Manage usage** (your ChatGPT settings), the model, and **Sign out**.
- **Setup:** the checks above, any time, and the **Overlay hotkey** card. After changing the
  game folder, click **Restart WoW Coach**.
- **Privacy:** what stays on your computer and what is sent to ChatGPT. The full text:
  [privacy notice](privacy.md).

## If something doesn't work

- **"The desktop app needs the desktop extra":** you started an install without the app's
  parts. Run the install line from step 1 again.
- **The small card hides behind the game:** play in windowed or borderless mode. A game in
  exclusive full screen can cover other windows.
- **No tray icon** (some Linux desktops, such as plain GNOME): closing the window quits WoW
  Coach. Leave the window open, or minimize it, while you play.
- **macOS:** the app menu and "start with my computer" buttons are not available yet. Start
  WoW Coach from the terminal with `wow-coach app`.
- **You prefer the old browser window:** `wow-coach app --browser` still opens it
  ([guide](coach-window.md)).
- More help: [Troubleshooting](troubleshooting.md).
