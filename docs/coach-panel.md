# The Coach panel: your coach inside the game

The Coach panel is a small window inside World of Warcraft: Forever. It shows your coach's
next steps and answers, and has a box where you can ask the coach a question. It comes with
the CoachLink addon from version 0.8.0.

**How it works, in plain words:**
- A WoW addon can't use the internet, so the coach itself runs on your PC: the Claude Code
  agent, or any AI app connected to `wow-coach`.
- When you ask a question, the game saves it. Your coach on the PC reads it and writes the
  answer into a small file that the game reads.
- You see the answer in the panel after your next `/reload`. Your coach on the PC also shows
  it right away.

## What you need

- CoachLink 0.8.0 or newer.
- A coach on your PC that can use wow-coach's tools: the
  [Claude Code agent](claude-code-agent.md) (the easiest), or another
  [AI app connected to wow-coach](connect-an-ai-app.md).
- About 5 minutes.

## Set it up (once)

1. Close World of Warcraft through the game menu: press Esc, then click **Exit Game**.
2. Run this line in a terminal. It updates the addon and creates the folder where your coach
   writes its answers (`Interface/AddOns/CoachLink_Advice`):

   ```
   uvx --from git+https://github.com/RayanBayat/wow-coach@v0.10.0 wow-coach setup
   ```

   **You should see:** "Setup finished", and a line that says it created `CoachLink_Advice`.
3. Start the game again. The game only notices new addon files after a full restart, not a
   `/reload`.

## Open the panel

Any of these:
- Type `/coach panel` in the chat box.
- Click the addon button on the minimap, then **CoachLink**.
- Bind a key: Options, then Keybindings, then the **CoachLink** section.

The panel remembers where you put it and how big it is. **A-** and **A+** change the text
size. Esc closes it.

## Ask a question

1. Type your question in the box at the bottom of the panel, for example "What should I do
   next?" or "Where do I turn in Fields of Grief?".
2. Click **Ask (saves and reloads)**, or press Enter. The screen reloads for a few seconds:
   that is how the game saves your question.
3. Your coach on the PC answers. In Claude Code with live mode on, the answer shows there
   within a few seconds, so you can read it right away. Otherwise ask your coach: "answer my
   question from the game".
4. To see the answer in the game, click **Show answer (reloads)** in the panel, or type
   `/reload`. The panel shows it, with who wrote it and when.

Until the answer arrives, the panel says "Waiting for your coach" with your question and the
Show answer button. If you click it too early, nothing is lost: the question keeps waiting.

**Why the reloads?** A WoW addon can't use the internet or talk to other programs. The only
moment it can hand anything to your PC is when the game saves, which happens at a `/reload`
(and at logout). New answers from your PC are read the same way. That is how Blizzard keeps
addons safe, so wow-coach works inside it instead of around it.

Your coach can also send you next steps without a question, for example after it makes a
plan with you. After a reload, one chat line tells you when there is new advice.

## Good to know

- **In combat** the panel hides, and you can't ask. It comes back when the fight ends. That
  is on purpose: Blizzard doesn't want addons to help in fights, and the coach is for
  everything outside them.
- **AI can be wrong.** The panel says which AI wrote each answer. If something sounds off,
  ask again or check the wiki link your coach gives.
- **Privacy:**
  - Your questions are saved in the game's addon file on your PC.
  - They go to the AI app you use, like anything you type there.
  - The panel never sends anything to other players.

## If something doesn't work

| What you see | What to do |
|---|---|
| "please restart the game once to finish updating CoachLink" | Exit the game through the menu and start it again |
| The panel says there is no advice yet | Ask a question, or ask your coach on the PC to send you next steps. Then `/reload` |
| Your coach says it wrote an answer, but the panel shows nothing new | Type `/reload`. If it is still missing, check that `wow-coach setup` created `CoachLink_Advice`, and restart the game once |
| The panel says "you can ask after the fight" | Wait until you are out of combat |

More help: [troubleshooting](troubleshooting.md).
