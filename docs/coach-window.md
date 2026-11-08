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

## When the coach speaks up by itself

At first the coach only answers when you ask. In **Settings**, under **When should the coach
speak up?**, you can choose what happens for each kind of event the game reports:

| Event | Example |
|---|---|
| You died, or died again soon after coming back | "Died in Brill. Attacked by 2 enemies..." |
| You levelled up | "Reached level 12." |
| A quest is ready to turn in | "Ready to turn in: Fields of Grief." |
| Your bags are nearly full | "2 free slots left." |
| A new zone | "Now in Silverpine Forest." |
| Unspent talent points, a gear upgrade in your bags, gear that needs repair | |
| A timer, every N minutes | |

For each one you choose **Off**, **Notify me** (just a notification, no AI) or **Ask the
coach** (the coach looks at it and gives advice, using your plan).

- **The game only reports events when it saves:** at `/coach`, `/reload`, logout, or the
  Coach panel's Ask.
- **The coach stays quiet in dungeons and raids**, unless you turn that off, and in the quiet
  hours you set.
- **The cooldown:** after an answer it didn't ask for, the coach waits at least the cooldown
  minutes before the next one. In between, you only get notifications.
- **Optional "use a small AI to decide":** a small, cheap model on your plan reads the events
  and your own words, for example "only wake the coach if I die twice in 10 minutes", and
  decides whether it is worth asking the bigger model.
- **Why it did or didn't speak:** the window shows each decision and its reason.

## Limits that protect your plan

- In **Settings** you set the most questions per hour and per day (20 and 100 at first).
- When a limit is reached, or your plan's own limit is, the coach stops and says when it can
  answer again.
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
| A limit message | Wait until the time it says, or raise the limits in Settings |
| No notifications on Linux | Install `libnotify` (the `notify-send` program) |
| The window says no saved game data | In the game, type `/coach` once |
| "Press Enter in the wow-coach terminal for a new link" | The window's session ended (for example a new tab). Press Enter in the terminal and open the new link |
| "wow-coach was closed" | Start `wow-coach app` again |

More help: [troubleshooting](troubleshooting.md).
