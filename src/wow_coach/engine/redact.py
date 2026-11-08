"""Hide other players' names before anything goes to the AI.

Privacy rule (docs/plans/coach-panel.md, section 3): unless the player allows it, the names
of group members, mail senders and players who attacked the character are replaced with
"a player". The character's own name is never touched.

Names are matched as whole words (letters, digits and "_" all count as part of a word), so
"Ann" does not change "Annex" or "Ann2". Names of 4 or more letters match in any case, so
"gorbo" and "GORBO" are hidden too. Shorter names must match exactly: "Will" is hidden but the
common word "will" survives.
"""

import re

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


def _killer_name(event: Table, attackers: list[Table]) -> str | None:
    """The killing blow's name, unless an attacker of that name is known to be a monster."""
    name = as_text(as_table(event.get("killer")).get("name"))
    if not name:
        return None
    monsters = {as_text(a.get("name")) for a in attackers if a.get("isPlayer") is False}
    return None if name in monsters else name


def _event_names(history: list[Table]) -> set[str]:
    """Names in history events: players who attacked or killed, and who sent an item."""
    names: set[str] = set()
    for event in history:
        attackers = as_tables(event.get("attackers"))
        for attacker in attackers:
            name = as_text(attacker.get("name"))
            if attacker.get("isPlayer") is True and name:
                names.add(name)
        killer = _killer_name(event, attackers)
        if killer:
            names.add(killer)
        sender = as_text(event.get("from"))
        if sender and looks_like_player_name(sender):
            names.add(sender)
    return names


def other_player_names(character: Character) -> set[str]:
    """Every other player's name found in the character's save."""
    found = _group_names(character.snapshot) | _mail_names(character.snapshot)
    found |= _event_names(as_tables(character.history))
    # "Name-Realm" forms: hide the bare name too, because the report may print either.
    found |= {name.split("-", 1)[0] for name in found}
    return without_own_names(found, character)


def without_own_names(names: set[str], character: Character) -> set[str]:
    """``names`` without this character's own name and without names too short to match."""
    own = {name.lower() for name in own_names(character)}
    return {n for n in names if len(n) >= MIN_NAME_LENGTH and n.lower() not in own}


def redact_names(text: str, names: set[str]) -> str:
    """Replace each name in ``names`` (whole words only) with "a player"."""
    if not names:
        return text
    # Longest first, so "Annabel" is handled before "Ann".
    ordered = sorted(names, key=len, reverse=True)
    long_names = [re.escape(n) for n in ordered if len(n) >= IGNORE_CASE_FROM]
    short_names = [re.escape(n) for n in ordered if len(n) < IGNORE_CASE_FROM]
    parts = []
    if long_names:
        parts.append(f"(?i:{'|'.join(long_names)})")
    parts.extend(short_names)
    return re.sub(rf"(?<!\w)(?:{'|'.join(parts)})(?!\w)", REPLACEMENT, text)
