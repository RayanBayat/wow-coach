# Publishing CoachLink on CurseForge

This page is for the maintainer. It explains how the CoachLink addon gets onto CurseForge, so
players can install and update it with one click in the CurseForge app. Only the addon goes
there: the WoW Coach app and the `wow-coach` command are not addons, so players get those from
this repository (see the [WoW Coach app guide](desktop-app.md)).

Once it is set up, every release uploads itself: pushing a version tag builds
`CoachLink-<version>.zip` for the GitHub release, and the same release job uploads that zip to
CurseForge ([`.github/workflows/release.yml`](../.github/workflows/release.yml)). Until it is
set up, that step is skipped.

## One-time setup

1. **Create the project.** Sign in at [authors.curseforge.com](https://authors.curseforge.com)
   and create a new project for World of Warcraft, type addon, named **CoachLink**. Use the
   page text in [`addon/CURSEFORGE.md`](../addon/CURSEFORGE.md) for the description, MIT as the
   license, and `https://github.com/RayanBayat/wow-coach` as the source.
2. **Note the project ID.** It is shown on the project's overview page.
3. **Make an API token.** On authors.curseforge.com, open your settings, then **API Tokens**,
   and generate one. Treat it like a password.
4. **Find the game version ID for WoW Forever.** CurseForge files are tagged with game version
   IDs. This line lists all of them (put your token in place of `YOUR_TOKEN`); look for the
   WoW Forever version that matches the game's current build:

   ```
   curl -s -H "X-Api-Token: YOUR_TOKEN" https://wow.curseforge.com/api/game/versions
   ```

   We have not checked how CurseForge names the Forever versions in this list, so read the
   names carefully. The addon's `CoachLink.toc` says `## Interface: 16001`.
5. **Tell GitHub.** In the repository on GitHub, open **Settings → Secrets and variables →
   Actions**:
   - under **Secrets**, add `CF_API_TOKEN` with the token;
   - under **Variables**, add `CURSEFORGE_PROJECT_ID` with the project ID, and
     `CURSEFORGE_GAME_VERSIONS` with the game version ID (several IDs are separated by commas).

## Every release after that

Nothing extra: push the version tag as usual (see [AGENTS.md](../AGENTS.md)). The release job
uploads the zip to CurseForge with the version's notes from `CHANGELOG.md`, as a "release".

A release that came out before the setup (for example 0.10.0) can be uploaded by hand on the
project's **Files** page with the zip from the GitHub release.

## If an upload fails

The release job's log shows CurseForge's answer. Common causes: an expired or wrong token
(make a new one and update the secret), or a game version ID that no longer exists after a
game update (look it up again with the line above and update the variable).
