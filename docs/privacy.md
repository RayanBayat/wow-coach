# Privacy notice

This notice explains what data wow-coach handles, where it goes, and what you can do about it.
wow-coach is free, open-source software that runs on your own computer. Its author runs no
server and receives none of your data.

Last updated: 2026-11-08.

## The short version

- The CoachLink addon writes your character's data to a file on your computer. Nothing else.
- The `wow-coach` program reads that file on your computer.
- When **you choose** to get answers from wow-coach's own coach (`wow-coach ask`, the coach
  window), it sends that data, your question, the last few messages of the conversation and
  the coach's notes (your player notes and the character's journal) to **OpenAI**, through your own **Sign in with ChatGPT**,
  using your ChatGPT plan.
- When you use another AI app (Claude Code, an MCP app, or you paste the text into a chat),
  that app's company receives what it reads. That is between you and that company.
- No tracking, no analytics, no ads. wow-coach never sends data to its author.

## What data, and where it goes

| Data | Where it is kept | Who receives it, and when |
|---|---|---|
| Your character's snapshot: name, realm, level, zone, quests, gear, bags, bank, mail, spells, stats, reputations, history (deaths, items, quests) | The game's SavedVariables file on your computer | OpenAI, when wow-coach's own coach answers (only after you signed in). Any other AI app you connect |
| Questions you type in the Coach panel or the coach window | The game's SavedVariables file, and a conversation file in wow-coach's data folder | OpenAI, as above |
| The coach's answers | `Interface/AddOns/CoachLink_Advice/Advice.lua`, and the conversation file | Nobody else |
| Your chats with your Claude coach (`claude --agent wow-coach`): what you typed and the coach's text replies, copied from Claude Code's own session files in `~/.claude/projects` (never its tool calls, thinking or other sessions), plus answers other apps write into the game's answer file | The same conversation file in wow-coach's data folder. The Claude Code files are only read, never changed | OpenAI, as part of the recent conversation that goes with each question to wow-coach's own coach (the newest messages that fit, about 6 000 characters). Other players' names in them are replaced with "a player" like everywhere else. Turn off "Use my Claude coach chats" in Settings to stop importing them and to keep them out of what is sent |
| Your player notes and character journals (the coach writes them; they can hold personal notes, for example how you like to be coached or notes about your computer) | wow-coach's data folder | OpenAI, with each question to wow-coach's own coach (the whole journal and player notes, up to about 16 000 and 6 000 characters; longer notes keep their most useful sections), unless you turn off "send the coach's notes" in Settings. Sections about your computer (a heading with "computer", "PC" or "machine", such as "## This computer") are never sent. The AI app you use, when it reads them |
| Other players' names (your group, mail senders, players who attacked you) | The game's SavedVariables file | Hidden from wow-coach's own coach (replaced with "a player") unless you turn on "share other players' names". Other AI apps can read them in the status report |
| Your ChatGPT sign-in: a renewal token, the id OpenAI gave this copy of wow-coach, and your ChatGPT account id (not your email) | Your computer's password store (for example KDE Wallet, GNOME Keyring, macOS Keychain, Windows Credential Manager), never a file. The short-lived access token is only kept in memory | OpenAI only, when wow-coach asks for an answer |
| Your email address | Not stored by wow-coach (it is shown once after sign-in) | Nobody |
| A usage log (time, model, number of tokens; no text) | wow-coach's data folder | Nobody |
| Your "when to speak up" rules in your own words, and short summaries of game events (for example "Died in Brill") | wow-coach's data folder (settings) | OpenAI's smallest model on your plan, only if you turn on "use a small AI to decide" |
| Names of other players the coach has seen (to keep hiding them), and the ids of questions already answered | wow-coach's data folder (`hidden-names-v2.json`, `answered-questions.json`), kept until you delete them. `import-state.json` only remembers how far your Claude Code session files were read | Nobody |
| Words you look up on the Warcraft Wiki | Nowhere | The Warcraft Wiki (warcraft.wiki.gg), when the coach looks something up |

wow-coach's data folder is `~/.local/share/wow-coach` on Linux (or `$XDG_DATA_HOME/wow-coach`),
`~/Library/Application Support/wow-coach` on macOS, and `%LOCALAPPDATA%\wow-coach` on
Windows.

## Why

The only purpose is to coach you in World of Warcraft: Forever: answering your questions and
suggesting what to do next. The data is never used for anything else, never sold, and never
used to train anything by wow-coach.

## OpenAI

When you sign in with ChatGPT, OpenAI handles your requests under its own terms and privacy
policy (https://openai.com/policies). The requests count as your ChatGPT use, and you can see
and manage that usage at https://chatgpt.com/settings/usage. wow-coach asks OpenAI not to store
the requests (`store: false`).

## Your choices

- **Don't use wow-coach's own coach.** Without `wow-coach signin`, nothing is sent to OpenAI.
- **Sign out:** run `wow-coach signout`, or click **Sign out** in the coach window. You can
  also disconnect wow-coach in your ChatGPT settings.
- **Delete everything:** delete wow-coach's data folder, the `CoachLink_Advice` folder in the
  game's `Interface/AddOns`, and the CoachLink SavedVariables file
  (`WTF/Account/<account>/SavedVariables/CoachLink.lua`).
- **Other players' names:** keep "share other players' names" off (the default).
- **Your Claude coach chats:** turn off "Use my Claude coach chats" (Settings, Privacy) so they
  are not imported, not shown, and never sent to ChatGPT. Chats already imported stay in the
  conversation file until you delete it (`conversations/<character>.jsonl` in the data folder).
- **The coach's notes:** turn off "send the coach's notes" to keep your player notes and
  journals on your computer (answers fit you less well).

## Children

wow-coach is a helper for a game rated T (Teen). It does not knowingly handle data of
children under 13 and is not meant for them.

## Questions and changes

- Questions about this notice go to the project's issue page:
  https://github.com/RayanBayat/wow-coach/issues
- Security problems: see [SECURITY.md](../SECURITY.md).
- Changes to this notice are listed in the [changelog](../CHANGELOG.md).
