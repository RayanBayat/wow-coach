# The coach window: answers while you play, with your ChatGPT plan

> **New:** the [WoW Coach app](desktop-app.md) does everything this page does, in its own
> window, with quick buttons and a card that stays on top of the game. This browser window
> still works: start it with `wow-coach app --browser`.

The coach window is a small page that wow-coach opens in your web browser. It is your own
coach, answering with your ChatGPT plan. It shows the coach's answers the moment they are
ready, so you don't need to `/reload` the game to read them. It can also pop up a
notification.

It runs only on your computer. Only you can open it, and it never talks to other players.

## What you need

- A ChatGPT plan that allows it (Plus or Pro). Answers come out of your plan's usage, like
  using ChatGPT itself.
- The CoachLink addon 0.8.0 or newer, and the [Coach panel](coach-panel.md) set up.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), the same one-line install as
  in the other guides.

## Start it

1. Sign in with ChatGPT, once. This opens OpenAI's own page in your browser. Approve
   **wow-coach** there; wow-coach never sees your password.

   ```
   uvx --from git+https://github.com/RayanBayat/wow-coach@v0.9.0 wow-coach signin
   ```

   **You should see:** "Signed in as <your email>" and "You're using your ChatGPT plan."
   Your sign-in is kept in your computer's password store (for example KDE Wallet, GNOME
   Keyring, macOS Keychain or Windows Credential Manager), never in a file.
2. Open the coach window:

   ```
   uvx --from git+https://github.com/RayanBayat/wow-coach@v0.9.0 wow-coach app
   ```

   Your browser opens the window. Keep the terminal open while you play; press Ctrl+C there
   to close the window. If the browser shows an error or doesn't open, paste the link the
   terminal printed into it. Need a new link (for example in another browser)? Press Enter in
   the terminal.

## Use it

- **Ask in the window:** type a question and click **Ask**, or click **What next?**. The
  answer shows at once, with numbered steps. It is also put in the game's Coach panel for your
  next `/reload`.
- **Ask in the game:** type your question in the Coach panel and click **Ask**. The window
  answers it by itself within a few seconds, and shows it or notifies you.
  You can keep playing.
- **Notifications:** turn them on or off in **Settings**. If your computer can't show
  them, the window says so.
- **ChatGPT:** shows that you are signed in, how many questions you asked in the last hour and
  day, a **Manage usage** link to your ChatGPT settings, and **Sign out**.

## When the game saves

The game only hands your character to wow-coach when it **saves**: when you type `/coach` or
`/reload`, log out, press the "Save for the coach" key, or ask in the game. So the coach can
never be "live", but right after each save it can tell you what changed since the save before.

In **Settings**, under **Coach on its own**, **When the game saves** has three choices:

- **Off:** nothing happens. The coach only answers when you ask.
- **Tell me what's worth knowing** (the default): one desktop notification that lists what is
  worth knowing, in one short text. It is worked out by wow-coach itself from what changed
  between the two saves, so it is free and uses nothing from your plan. When nothing
  happened, you get nothing.
- **Tell me and update my next steps:** the same notification, and after every save that
  changed something (you moved, levelled, looted, finished or picked up a quest...) the coach
  gets "Status updated: what should I do next?". Its answer shows in the chat and on the small
  keep-on-top card, so your next steps are always fresh. It uses one call of your plan per
  save; a `/reload` with nothing new costs nothing, and a save made by asking in the game
  only answers your question.

What counts as worth knowing:

| Thing | Example |
|---|---|
| You died, or died again soon after coming back | "Died in Brill. Attacked by 2 enemies..." |
| You levelled up | "Reached level 12." |
| A quest is ready to turn in | "Ready to turn in: Fields of Grief." |
| Your bags are nearly full | "Bags are nearly full: 2 free slots left." |
| A new zone | "Now in Silverpine Forest." |
| Unspent talent points, a gear upgrade in your bags, gear that needs repair | |

One more switch, **Stay quiet in dungeons and raids** (on at first): while you are in an
instance, nothing is told or asked.

There is no timer, no quiet hours and no waiting time between answers. One save gives at
most one notification and at most one unasked answer, and a save where nothing changed gives
nothing, so repeated `/reload`s cost nothing.

Settings files from older versions still work: if any event was set to "Ask the coach" you
get the advice choice, otherwise if any was on "Notify me" you get the notify choice, and
when everything was off you get the new default. The old timer, quiet hours, waiting time
and small-AI settings are dropped.

## Your plan's limits

- wow-coach sets no limits of its own. Only your ChatGPT plan's limits apply.
- When your plan's limit is reached, the coach stops and says when it can answer again.
- One game save never costs more than one answer it didn't ask for.

## Privacy

- **What goes to OpenAI:** your character's data (the same report the other coaches get), the
  question, the last few messages of the conversation, and the coach's notes (your player notes
  and the character's journal; turn them off in Settings with "send the coach's notes"). It goes through your own sign-in and
  counts as your ChatGPT use.
- **Other players' names** (your group, mail senders, players who attacked you) are replaced
  with "a player" first, unless you turn that off in Settings.
- **Nothing else leaves your computer.** wow-coach has no server and no tracking. The window
  only works on this computer.
- **To stop:** run `wow-coach signout`, or disconnect wow-coach in your ChatGPT settings.

## If something doesn't work

| What you see | What to do |
|---|---|
| "You're not signed in to ChatGPT yet" | Run `wow-coach signin` |
| "Your password keychain could not be used. It may be locked" | Unlock your password store (for example KDE Wallet) and try again |
| "You signed in, but did not allow wow-coach to use your ChatGPT plan" | Sign in again and accept the plan permission |
| A limit message | Wait until the time it says (it is your ChatGPT plan's own limit) |
| No notifications on Linux | Install `libnotify` (the `notify-send` program) |
| The window says no saved game data | In the game, type `/coach` once |
| "Press Enter in the wow-coach terminal for a new link" | The window's session ended (for example a new tab). Press Enter in the terminal and open the new link |
| "wow-coach was closed" | Start `wow-coach app` again |

More help: [troubleshooting](troubleshooting.md).
