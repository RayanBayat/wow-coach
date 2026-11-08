# wow-coach

wow-coach is a coach for World of Warcraft: Forever. It reads your real character (level,
quests, talents, gear, every item in your bags, bank and mail, spells, stats and more) and
helps you decide what to do next. A small addon called CoachLink saves your character as text,
and a program on your computer reads it.

You do not need to know how to code.

## Start here: the WoW Coach app (Windows and Linux; macOS works with fewer extras)

The easiest way is the WoW Coach app. It is a normal window on your computer with a chat, quick
buttons ("What next?", "Check my gear"...) and a small card that can stay on top of your game.
It answers with your own ChatGPT plan (Plus or Pro). It also installs the addon for you.

You need:

- A ChatGPT Plus or Pro plan.
- WoW Forever, installed with the Battle.net app.
- About 10 minutes. There is nothing else to buy.

Then follow the step-by-step guide for your system. Every step says what you should see:

- [Install and use the app on Windows](docs/desktop-app.md#windows)
- [Install and use the app on Linux](docs/desktop-app.md#linux)
- [macOS](docs/desktop-app.md#macos)

The guide starts from zero: it even shows how to open the window where you type the install
line (a "terminal") and how to install the one free helper tool (uv) the app needs.

## Other ways to use wow-coach

The app is the recommended path. These are alternatives, for people who already use another AI
app. Start with any one of them and add the others later.

| | Way 1: the WoW Coach app (recommended) | Way 2: paste | Way 3: connect an AI app | Way 4: skill and live mode | Way 5: the Claude Code agent |
|---|---|---|---|---|---|
| For | People with a ChatGPT plan (Plus or Pro) | Anyone, with any AI chat | People who use an AI app that supports MCP | People who use an AI agent such as Claude Code | People who use Claude Code |
| Effort | Install uv, then one install line; the app sets up the rest and signs you in with ChatGPT | Lowest: install the addon only | Medium: also install uv and edit one settings file | Medium: also copy one folder; live mode needs Claude Code | One setup command, then one start command |
| What you get | Your own coach app: chat and quick buttons, a card that stays on top of the game, answers your questions from the game by itself, notifies you, and tells you what changed after each save (a level-up, a death, full bags...), with advice if you want | You type `/coach copy`, paste the text into the chat | The AI reads your character itself and remembers each character | The AI answers on its own each time you type `/coach` | A coach that sets everything up, lets you pick which character to continue, takes your goal and plans how to reach it |
| Guide | [The WoW Coach app](docs/desktop-app.md) | [Use with any AI chat](docs/use-with-any-ai-chat.md) | [Connect an AI app](docs/connect-an-ai-app.md) | [Skill and live mode](docs/coach-skill-and-live-mode.md) | [The Claude Code agent](docs/claude-code-agent.md) |

## Quick start (Way 2: paste into any AI chat)

Shortcut: if you have [uv](https://docs.astral.sh/uv/getting-started/installation/), this line
does steps 1 to 3 for you:
`uvx --from git+https://github.com/RayanBayat/wow-coach@v0.9.0 wow-coach setup`

1. Download `CoachLink-0.9.0.zip` from the
   [Releases page](https://github.com/RayanBayat/wow-coach/releases/latest).
2. Unzip it into the game's `Interface\AddOns` folder, so this file exists:
   `World of Warcraft\_forever_\Interface\AddOns\CoachLink\CoachLink.toc`.
   [Step-by-step help for Windows, macOS and Linux](docs/install-the-addon.md).
3. Quit the game completely and start it again. (A new addon is only noticed after a full
   restart.)
4. Log in and type `/coach copy` in the chat box. A window opens with your character as text,
   already selected.
5. Press Ctrl+C (Cmd+C on a Mac) to copy it, then Esc to close the window.
6. Open your AI chat, paste, and ask: "What should I do next?"
7. Optional but better: save the [coach instructions](docs/use-with-any-ai-chat.md) in your
   chatbot once, so it knows how to teach you.

In game, `/coach` saves your character (the screen reloads for a few seconds) and `/coach help`
lists the commands.

## Way 5: the Claude Code agent (the easiest alternative if you use Claude Code)

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (the
   [Connect an AI app](docs/connect-an-ai-app.md) guide, step 1, shows how).
2. In a terminal, run this one line. It finds your game, installs the addon, creates your
   player notes file and installs the coach into Claude Code:

   ```
   uvx --from git+https://github.com/RayanBayat/wow-coach@v0.9.0 wow-coach setup --claude-code
   ```

3. Restart the game completely if the setup told you to, then start your coach:

   ```
   claude --agent wow-coach
   ```

Tell it your goal ("level 20 by Sunday", "100 gold for the mount") and it makes a plan.
[More in the guide](docs/claude-code-agent.md).

## Game lookups

With Way 3, the AI can also look up game facts quickly instead of searching the web: where an
NPC stands, what a vendor sells, who gives a quest and what it rewards. It reads the
[Warcraft Wiki](https://warcraft.wiki.gg) (text under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)), tells you which parts are
Forever-only, and gives you the page link. You can try it yourself:

```
wow-coach wiki "Abigail Shiel" --page "Abigail Shiel"
```

To find a quest by the number the status shows after its name, for example `(quest 365)`:

```
wow-coach wiki --quest 365
```

## Guides

- [Install the addon](docs/install-the-addon.md)
- [Use with any AI chat](docs/use-with-any-ai-chat.md)
- [Connect an AI app](docs/connect-an-ai-app.md)
- [Skill and live mode](docs/coach-skill-and-live-mode.md)
- [The WoW Coach app](docs/desktop-app.md) and the older [browser window](docs/coach-window.md)
- [The Claude Code agent](docs/claude-code-agent.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Glossary](docs/glossary.md)
- [How it works](docs/design.md)

## What the coach remembers

Each character has its own journal (choices, goals and plans, progress, open advice), and you
have player notes shared by all characters (how you like to be coached). The addon also keeps
a progress log per character. The tools the AI uses:

- `list_characters`: your characters, most recently played first, with each one's goal.
- `character_status`, `recent_history`, `progress_summary`: where a character is, what it did, and how it progressed lately.
- `read_coach_notes`, `save_coach_notes`, `save_player_notes`: read both kinds of notes, save one character's journal, save the player notes.
- `search_wiki`, `read_wiki_page`, `find_quest`: game facts from the Warcraft Wiki. `find_quest` finds a quest's page from its quest ID (shown in the status).
- `questions_from_game`, `send_advice_to_game`: read the questions you asked in the game's
  [Coach panel](docs/coach-panel.md), and show the coach's answers and next steps there.

In a terminal, `wow-coach characters` and `wow-coach progress` show the same lists.

## Privacy and safety

- The addon never uploads anything. It only writes a file on your computer.
- The helper program reads that file and never sends your character anywhere. The one thing it
  does on the internet is look up game facts: when the AI uses a lookup tool, the search words
  (for example "Abigail Shiel") are sent to the [Warcraft Wiki](https://warcraft.wiki.gg). Your
  character data is not part of that.
- The AI you choose receives what you paste or what it reads, and sends it to its provider, like
  anything else you type there. Your character sheet contains your character name, realm,
  guild, level, zone, quests, items, gear, spells, gold and the rest of what the game shows you.
  It also contains other players' character names when they are in your group, sent you
  mail (with the mail's subject) or attacked you just before you died. It does not contain your account name, password or email.
- The addon only uses the normal addon interface. It does not read game memory, inject code or
  automate play. Addons that use the normal interface are allowed under Blizzard's rules.
- With the WoW Coach app or the coach window (Way 1), wow-coach's own coach sends your character's data, your
  questions, the recent conversation and the coach's notes (you can turn the notes off) to OpenAI through your own Sign in with ChatGPT, using your ChatGPT plan. Other
  players' names are replaced with "a player" first, unless you allow them. Details:
  [privacy notice](docs/privacy.md).
- The coach never needs you to close the game for it.

## FAQ

**Does this play the game for me?** No. It only reads your character and gives advice.

**Is it free?** wow-coach is free. Your AI chat may have its own limits or prices.

**Which AI is best?** Any that can follow instructions. Try the one you already use.

**Why do I have to type `/coach`?** Addons cannot send data out of the game. They can only save
a file, and the game writes it when you type `/coach`, log out or reload.

**Will it work after a game patch?** Usually. If a part stops working, the character report
says which part, and the rest still works. Please [report it](https://github.com/RayanBayat/wow-coach/issues).

**What does "MCP" mean?** The standard way for AI apps to use helper programs on your computer.
See the [glossary](docs/glossary.md).

## Credits

- Game facts were checked against Blizzard's own interface code, mirrored at
  [Gethe/wow-ui-source](https://github.com/Gethe/wow-ui-source) (branch `forever`).
- [Questie](https://github.com/Questie/Questie) is a separate, optional addon that marks quests
  on your map. wow-coach does not include or depend on it.
- World of Warcraft is a trademark of Blizzard Entertainment. This project is not affiliated
  with Blizzard.

## For contributors

See [AGENTS.md](AGENTS.md) and the [changelog](CHANGELOG.md).

## License

[MIT](LICENSE), copyright 2026 Rayan Bayat.
