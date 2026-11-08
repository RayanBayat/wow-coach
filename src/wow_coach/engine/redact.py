"""Hide other players' names before anything goes to the AI.

Privacy rule (docs/plans/coach-panel.md, section 3): unless the player allows it, the names
of group members, mail senders and players who attacked the character are replaced with
"a player". The character's own name is never touched.

Names are matched as whole words (letters, digits and "_" all count as part of a word), so
"Ann" does not change "Annex" or "Ann2". A name is always hidden as seen ("Gorbo") and in
ALL CAPS ("GORBO"). Names of 4 or more letters are also hidden in any other case ("gorbo"),
unless the lower-case word is an ordinary word (``commonwords.py``): a group-mate called
"Will" is hidden as "Will" or "WILL", but "What will I get?" stays readable.
"""

import re

from wow_coach.engine.commonwords import COMMON_WORDS
from wow_coach.report_values import Table, as_table, as_tables, as_text
from wow_coach.savedvars import Character

REPLACEMENT = "a player"
MIN_NAME_LENGTH = 2  # one letter would match far too much
IGNORE_CASE_FROM = 4  # names this long are matched in any case
# A player name is one word of letters ("Thrall"); "Auction House" has a space, so it stays.
_PLAYER_LIKE = re.compile(r"[^\W\d_]+")


def looks_like_player_name(sender: str) -> bool:
    """True for one word of letters, with an optional realm: "Thrall" or "Crossy-Stormrage".

    NPC senders usually have spaces ("Auction House"), so they are not hidden.
    """
    return _PLAYER_LIKE.fullmatch(sender.split("-", 1)[0]) is not None


def own_names(character: Character) -> set[str]:
    """The names that must never be hidden: this character's."""
    names = {character.key.split("-", 1)[0]}
    name = as_text(character.snapshot.get("name"))
    if name:
        names.add(name)
    return names


def _group_names(snapshot: Table) -> set[str]:
    members = as_tables(as_table(snapshot.get("group")).get("members"))
    return {name for member in members if (name := as_text(member.get("name")))}


def _mail_names(snapshot: Table) -> set[str]:
    letters = as_tables(as_table(snapshot.get("mail")).get("letters"))
    senders = (as_text(letter.get("sender")) for letter in letters)
    return {sender for sender in senders if sender and looks_like_player_name(sender)}


def _attacker_names(history: list[Table]) -> tuple[set[str], set[str]]:
    """(players, monsters) among all attackers in the history.

    The addon writes ``isPlayer = true`` for a player and leaves the key out for a monster
    (Lua's ``false or nil`` is nil), so only ``True`` means a player.
    """
    players: set[str] = set()
    monsters: set[str] = set()
    for event in history:
        for attacker in as_tables(event.get("attackers")):
            name = as_text(attacker.get("name"))
            if name:
                (players if attacker.get("isPlayer") is True else monsters).add(name)
    return players, monsters - players


def _killer_is_player(name: str, players: set[str], monsters: set[str]) -> bool:
    """Same idea as triggers/events.py, but also catching a killer with no attacker data."""
    if name in players:
        return True
    return name not in monsters and looks_like_player_name(name)


def _event_names(history: list[Table]) -> set[str]:
    """Names in history events: players who attacked or killed, and who sent an item."""
    players, monsters = _attacker_names(history)
    names = set(players)
    for event in history:
        killer = as_text(as_table(event.get("killer")).get("name"))
        if killer and _killer_is_player(killer, players, monsters):
            names.add(killer)
        sender = as_text(event.get("from"))
        if sender and looks_like_player_name(sender):
            names.add(sender)
    return names


def other_player_names(character: Character, *, own: frozenset[str] = frozenset()) -> set[str]:
    """Every other player's name found in the character's save.

    ``own`` holds the names of the player's other characters (alts), which are never hidden.
    """
    found = _group_names(character.snapshot) | _mail_names(character.snapshot)
    found |= _event_names(as_tables(character.history))
    # "Name-Realm" forms: hide the bare name too, because the report may print either.
    found |= {name.split("-", 1)[0] for name in found}
    return without_own_names(found, character, own=own)


def without_own_names(
    names: set[str], character: Character, *, own: frozenset[str] = frozenset()
) -> set[str]:
    """``names`` without the player's own characters and without names too short to match."""
    mine = {name.lower() for name in own_names(character) | own}
    return {n for n in names if len(n) >= MIN_NAME_LENGTH and n.lower().split("-")[0] not in mine}


def _any_case(name: str) -> bool:
    """True when "gorbo" and "Gorbo" may both be hidden: long enough, and not a common word."""
    bare = name.split("-", 1)[0].lower()
    return len(bare) >= IGNORE_CASE_FROM and bare not in COMMON_WORDS


def redact_names(text: str, names: set[str]) -> str:
    """Replace each name in ``names`` (whole words only) with "a player"."""
    if not names:
        return text
    # Longest first, so "Annabel" is handled before "Ann".
    ordered = sorted(names, key=len, reverse=True)
    parts = []
    any_case = [re.escape(n) for n in ordered if _any_case(n)]
    if any_case:
        parts.append(f"(?i:{'|'.join(any_case)})")
    # Every name, exactly as seen and in ALL CAPS ("GORBO"), even when it is a common word.
    parts.extend(re.escape(n) for n in ordered)
    parts.extend(re.escape(n.upper()) for n in ordered if n.upper() != n)
    return re.sub(rf"(?<!\w)(?:{'|'.join(parts)})(?!\w)", REPLACEMENT, text)
