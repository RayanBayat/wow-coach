# HeroBridge

HeroBridge saves your WoW Forever character to a file on your computer, so an AI coach can see
exactly where you are and help you decide what to do next. It also adds a small Coach panel in
the game where you can ask questions and read the answers.

HeroBridge works on its own, with any AI chat:

- **`/coach copy`** opens a window with your whole character as text (level, quests, talents,
  gear, bags, spells, professions, reputations and more). Copy it, paste it into any AI chat,
  and ask "What should I do next?".
- **`/coach`** (or the **Save for the coach** key, set in Options → Keybindings → HeroBridge)
  saves your character for coaching tools on your computer. It reloads the interface for a few
  seconds, and does nothing during a fight.
- **The Coach panel** (`/coach panel`, a key, or the addon compartment) shows the answers your
  coach left for you and lets you ask a new question.

For more, HeroBridge is the gateway for free tools on your computer
(https://github.com/RayanBayat/wow-coach):

- **The WoW Coach app** (Windows and Linux): a coach window that answers with your own ChatGPT
  plan, looks things up on the Warcraft Wiki and the web with sources, and can show its answer
  on top of the game.
- **Your own AI agent:** an MCP server and a `wow-coach` command, so tools like Claude Code,
  Codex or Cursor can read your character and answer in the Coach panel.

## Privacy and rules

- HeroBridge never uses the internet. It only writes a file on your computer, through the
  normal addon interface.
- It does not read game memory, inject anything or play for you.
- Some details the game hides from addons (for example during fights) are saved as "(hidden by
  the game)".

## Commands

- `/coach`: save your character (reloads the interface).
- `/coach copy` (or `/coach export`): show your character as text to copy. No reload.
- `/coach panel`: open the Coach panel.
- `/coach ask <question>`: ask your coach (saves and reloads).
- `/coach help`: show this list in the game.

Free and open source (MIT): https://github.com/RayanBayat/wow-coach
