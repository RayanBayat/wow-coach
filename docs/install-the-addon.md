# Install the CoachLink addon

CoachLink is a small add-on for World of Warcraft: Forever. It saves your character so an AI
can read it. You do this once.

An **addon** is a folder of files that the game loads when it starts. Installing one means
putting its folder in the right place.

You need: WoW Forever installed through the Battle.net app, and about 10 minutes.

## Step 1: Download the addon

1. Open https://github.com/RayanBayat/wow-coach/releases/latest
2. Under **Assets**, click `CoachLink-0.4.0.zip` (the number may be newer).

**You should see:** a file called `CoachLink-0.4.0.zip` in your Downloads folder.

**If it didn't work:** if your browser says the file is unsafe, check that you came from the
link above. The zip holds only text files.

## Step 2: Find the game folder

WoW Forever lives in a folder called `_forever_`, inside the World of Warcraft folder. Find it
with the Battle.net app:

1. Open the Battle.net app and pick **World of Warcraft: Forever** on the left.
2. Click the settings (gear) button next to the Play button.
3. Choose something like **Show in Explorer** (Windows) or **Show in Finder** (Mac).

The exact wording may differ between Battle.net versions. We could not check it for this
guide.

**You should see:** a folder window with `_forever_` inside, or you may already be inside it.
Open `_forever_`.

**Common places** if you want to look yourself:

| System | Usual path |
|---|---|
| Windows | `C:\Program Files (x86)\World of Warcraft\_forever_` |
| macOS | `/Applications/World of Warcraft/_forever_` |
| Linux with Wine or Lutris | `~/Games/battlenet/drive_c/Program Files (x86)/World of Warcraft/_forever_` (or under `~/.wine/drive_c/`) |

**If it didn't work:** on Linux, the Battle.net app runs inside Wine. Open your file manager
and look under the path above. Hidden folders (names starting with a dot) must be shown;
in most file managers the shortcut is Ctrl+H.

## Step 3: Open or create the AddOns folder

1. Inside `_forever_`, open the folder `Interface`, then the folder `AddOns`.
2. If `Interface` or `AddOns` doesn't exist, create it: right-click, New Folder, and name it
   exactly `Interface` (then `AddOns` inside it). Capital letters matter on macOS and Linux.

**You should see:** an `AddOns` folder, probably empty.

## Step 4: Unzip CoachLink into AddOns

1. Open your Downloads folder and unzip `CoachLink-0.4.0.zip`.
   - Windows: right-click the zip, **Extract All...**.
   - macOS: double-click the zip.
   - Linux: right-click, Extract, or run `unzip` in a terminal.
2. You get a folder named `CoachLink`. Move or copy that whole folder into `AddOns`.

**You should see:** this exact path exists:

```
_forever_\Interface\AddOns\CoachLink\CoachLink.toc
```

**If it didn't work:** the most common mistake is one folder too many, such as
`AddOns\CoachLink\CoachLink\CoachLink.toc`. Move the inner folder up one level so `CoachLink.toc`
sits directly inside the first `CoachLink` folder.

## Step 5: Restart the game fully

A new addon is only noticed when the game starts fresh. Typing `/reload` is not enough.

1. If the game is running, log out and quit it from the game menu.
2. Start it again from the Battle.net app.

## Step 6: Check that it is on

1. On the character selection screen, click the **AddOns** button (bottom left).
2. Find **CoachLink** in the list and make sure its box is ticked.
3. If there is a box such as **Load out of date AddOns**, tick it only if CoachLink is shown as
   out of date and unticked. (The label may read slightly differently.)
4. Log in with your character.

**You should see:** nothing special on screen, or a short blue "CoachLink:" line in the chat.

**If it didn't work:** if CoachLink isn't in the list at all, the folder is in the wrong place:
repeat the check at the end of Step 4. Also confirm you restarted the whole game.

## Step 7: Test it

1. In the chat box, type `/coach help` and press Enter.

**You should see:** a short help text from CoachLink listing its commands.

2. Type `/coach` and press Enter. The screen reloads for a few seconds. That's normal: it is how
   the addon saves your character.

Now continue with [Use it with any AI chat](use-with-any-ai-chat.md).

## Updating later

Download the new zip, delete the old `CoachLink` folder in `AddOns`, unzip the new one in its
place and restart the game fully.

## Uninstalling

Close the game and delete the `CoachLink` folder from `AddOns`.
