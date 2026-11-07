# wow-coach

wow-coach lets an AI of your choice see your World of Warcraft: Forever character, so it can
coach you with your real level, quests, talents, gear and spells. A small addon called
CoachLink saves your character as text. You give that text to the AI by pasting it, or by
connecting an AI app that can read it.

It works with ChatGPT, Claude, Gemini, Copilot and any other AI. You do not need to know how
to code.

## What you need

- WoW Forever installed with the Battle.net app (Windows, macOS, or Linux with Wine).
- An AI chat or app you already use.
- About 10 minutes.

## Pick your way

| | Way 1: paste | Way 2: connect an AI app | Way 3: skill and live mode |
|---|---|---|---|
| For | Anyone, with any AI chat | People who use an AI app that supports MCP | People who use an AI agent such as Claude Code |
| Effort | Lowest: install the addon only | Medium: also install uv and edit one settings file | Medium: also copy one folder; live mode needs Claude Code |
| What you get | You type `/coach copy`, paste the text into the chat | The AI reads your character itself and keeps a notebook | The AI answers on its own each time you type `/coach` |
| Guide | [Use with any AI chat](docs/use-with-any-ai-chat.md) | [Connect an AI app](docs/connect-an-ai-app.md) | [Skill and live mode](docs/coach-skill-and-live-mode.md) |

You can start with Way 1 and add the others later.

## Quick start (Way 1)

1. Download `CoachLink-0.2.0.zip` from the
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

## Guides

- [Install the addon](docs/install-the-addon.md)
- [Use with any AI chat](docs/use-with-any-ai-chat.md)
- [Connect an AI app](docs/connect-an-ai-app.md)
- [Skill and live mode](docs/coach-skill-and-live-mode.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Glossary](docs/glossary.md)
- [How it works](docs/design.md)

## Privacy and safety

- The addon and the helper program upload nothing. They only write and read files on your
  computer.
- The AI you choose receives what you paste or what it reads, and sends it to its provider, like
  anything else you type there. Your character sheet contains your character name, realm,
  level, zone, quests, gear, spells and gold. It does not contain your account name, password or
  email.
- The addon only uses the normal addon interface. It does not read game memory, inject code or
  automate play. Addons that use the normal interface are allowed under Blizzard's rules.
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
