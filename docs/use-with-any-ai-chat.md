# Way 1: use it with any AI chat

This works with every AI chat website or app: ChatGPT, Claude, Gemini, Microsoft Copilot and
others. You copy your character as text and paste it into the chat. Nothing to install besides
the [addon](install-the-addon.md).

## Step 1: Copy your character

1. In the game, type `/coach copy` and press Enter. (`/coach export` does the same.)
2. A window opens with your character as text. The text is already selected.
3. Press **Ctrl+C** (Windows, Linux) or **Cmd+C** (Mac) to copy it.
4. Press **Esc** to close the window.

**You should see:** a window with your whole character: name, level, zone, quests, stats,
everything in your bags, gear, spells, action bars, reputations and more. It is only your
data, with no instructions for the AI, so you decide what to ask.

**To include your bank, mail and recipes:** the game only shows these while their window is
open. Open your bank, a mailbox and each profession window once (and type `/played` for your
play time); the addon remembers what it saw and includes it from then on.

**If it didn't work:** if `/coach copy` says nothing, the addon isn't loaded (see
[the install guide, step 6](install-the-addon.md)). If the text isn't selected, click inside
the window, press Ctrl+A, then copy.

## Step 2: Paste it into the AI chat

1. Open your AI chat in a browser or app.
2. Write what you want, for example: "Here is my World of Warcraft Forever character. What
   should I do next?"
3. Paste with **Ctrl+V** (or **Cmd+V**) and send.

**You should see:** an answer that mentions your own character, quests and level.

Each time you want fresh advice, run `/coach copy` again and paste the new text. The AI cannot
see your game by itself.

## Step 3 (recommended): Give the chat the coach instructions once

The coach instructions are a file that tells the AI how to teach you (short steps, explain
terms, check your quests and gear). Without them, an AI still answers, but less well.

1. Open https://github.com/RayanBayat/wow-coach/blob/main/src/wow_coach/assets/skills/wow-coach/SKILL.md
2. Click the **Copy raw file** button (two squares) at the top right of the file view.
3. Paste it into your chatbot's instructions feature, below.

Remove the block between the two `---` lines at the very top if the chatbot complains; it is
only for AI agents.

### ChatGPT

ChatGPT has **Projects**: a project can have its own instructions that apply to every chat in
it. Look for Projects in the left sidebar, create one (for example "WoW coach"), and use its
**instructions** field (the button may say something like **Add instructions**; ChatGPT often
renames things). Open new chats inside that project.
Official help: https://help.openai.com/en/articles/10169521-using-projects-in-chatgpt
(we could not open this page while writing, so the labels above are not verified).
You can also use **Custom instructions** in your settings under personalization; those apply
to all your chats, so a project is better.

### Claude (claude.ai)

Claude has **Projects**.

1. Click **Projects** in the left side panel.
2. Click **New Project** in the upper right and give it a name.
3. In the project, click **Set project instructions**, paste the coach instructions, and click
   **Save instructions**.
4. Start your chats inside the project.

Projects are available on all plans, including free (up to five on free).
Source: https://support.claude.com/en/articles/9519177-how-can-i-create-and-manage-projects

### Google Gemini

Gemini has **Gems**: saved custom versions of Gemini with instructions.

1. Go to https://gemini.google.com and open the sidebar.
2. Click **Gems**, then **New Gem**.
3. Give it a name, paste the coach instructions into the instructions field, and click **Save**.

Google's help page says Gems are being converted to skills starting in November 2026, so the
steps may change. Source: https://support.google.com/gemini/answer/15146780

### Microsoft Copilot

We could not verify an equivalent for the consumer Copilot app. For Microsoft 365 Copilot
(work and school accounts), Microsoft documents **Custom instructions** under Copilot settings,
Personalization, and per-notebook instructions in Copilot Notebooks (**Add Copilot
instructions**):
- https://support.microsoft.com/en-US/microsoft-365-copilot/customize-how-microsoft-365-copilot-responds-to-you
- https://support.microsoft.com/en-US/Microsoft-365-Copilot/provide-custom-instructions-for-your-microsoft-365-copilot-notebook

If your Copilot has no such feature, paste the instructions as the first message of each chat,
then paste your character sheet.

### Any other chatbot

Look for words like "custom instructions", "system prompt", "project" or "persona". If there
is none, paste the instructions as the first message of every new chat.

## Where the AI keeps its notes

A plain chat has no memory between conversations. At the end of a session the coach may
give you a "Notes to paste next time" block. Save it in a text file and paste it at the start
of your next chat. To avoid this, use [Way 2](connect-an-ai-app.md).

## If it doesn't work

See [Troubleshooting](troubleshooting.md).
