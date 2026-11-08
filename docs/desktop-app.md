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
- **Game data: 12 min old:** the top of the page shows how fresh the coach's view of your
  character is. The game only hands your character to other programs when it saves: when you
  log out, type `/reload`, or press your **Save for the coach** key.
- **Refresh game data:** click it, then press your **Save for the coach** key in WoW. The game
  reloads for a few seconds, and the app updates by itself. If you type a question while it
  waits, the question is sent as soon as the fresh data arrives. (The key does nothing during a
  fight, so a reload never catches you mid-combat. Press it again when the fight is over.)

  Why can't the app do this alone? Programs that press keys in your game break Blizzard's
  rules, so WoW Coach never does it. One key press from you is all it needs.
- **Keep on top of the game:** opens a small card that stays above the game window and shows
  the newest answer. Drag it where you like; it remembers the spot. It never takes the
  keyboard away from the game.
- **Questions from the game:** ask in the game's Coach panel as before. WoW Coach answers
  within a few seconds, shows the answer, and can notify you. The answer is
  also in the Coach panel after your next `/reload`.
- **Closing the window** keeps the coach running in the tray. To stop it completely, use
  **Quit** in the tray icon's menu. Starting WoW Coach again just brings the window back:
  only one copy runs at a time.

## The other pages

- **Settings:** notifications, answering game questions by itself, when the
  coach should speak up on its own (when you die, level up, need repairs...), quiet hours,
  and limits. Changes save by themselves. A limit of **0 means no calls at all**, not "no
  limit". More about speaking up: [the coach window guide](coach-window.md#when-the-coach-speaks-up-by-itself).
- **ChatGPT:** your sign-in, how many questions you asked in the last hour and day,
  **Manage usage** (your ChatGPT settings), the model, and **Sign out**.
- **Setup:** the checks above, any time. After changing the game folder, click **Restart WoW
  Coach**.
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
