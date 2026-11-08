"""The "Gear hints" section: bag items the character can't use, and possible upgrades.

Pure functions like the rest of the report: snapshot tables in, Markdown text out.
The section only gives hints. The coach (the AI) makes the final call, so every line
says "possible", and it never guesses: if the snapshot lacks the facts needed for a
check (proficiency lines, item levels), that check is skipped.
"""

from wow_coach.report_values import Table, as_number, as_table, as_tables, as_text, number_text

GRAY_QUALITY = 0
ARMOR_CATEGORY = "Armor Proficiencies"
WEAPON_CATEGORY = "Weapon Skills"

# Item subtype (the game's English word) -> the name of the skill or proficiency that
# lets you use it. Anything not listed here (Miscellaneous, Librams, Idols...) is never flagged.
ARMOR_SKILL = {
    "Cloth": "Cloth",
    "Leather": "Leather",
    "Mail": "Mail",
    "Plate": "Plate Mail",
    "Shields": "Shield",
}
WEAPON_SKILL = {
    "One-Handed Swords": "Swords",
    "Two-Handed Swords": "Two-Handed Swords",
    "One-Handed Axes": "Axes",
    "Two-Handed Axes": "Two-Handed Axes",
    "One-Handed Maces": "Maces",
    "Two-Handed Maces": "Two-Handed Maces",
    "Daggers": "Daggers",
    "Staves": "Staves",
    "Polearms": "Polearms",
    "Fist Weapons": "Fist Weapons",
    "Bows": "Bows",
    "Guns": "Guns",
    "Crossbows": "Crossbows",
    "Thrown": "Thrown",
    "Wands": "Wands",
}

# The item's ``equipSlot`` (the game's INVTYPE_* text) -> the worn slots it could go in.
# The worn names are the ones the addon saves (``GEAR_SLOTS`` in CoachLink.lua).
# I could not check these English texts in Blizzard's UI source (its global strings
# file is not published there), so they come from the game's usual wording; the raw
# ``INVTYPE_*`` names are listed too because the addon saves those when it has no text.
# One-Hand, Two-Hand and Main Hand are all compared with the main hand. Shirts, tabards,
# relics, ammo and bags are left out on purpose: no "upgrade" makes sense for them.
SLOTS_FOR_EQUIP: dict[str, list[str]] = {
    "Head": ["Head"],
    "Neck": ["Neck"],
    "Shoulder": ["Shoulders"],
    "Chest": ["Chest"],
    "Robe": ["Chest"],
    "Waist": ["Waist"],
    "Legs": ["Legs"],
    "Feet": ["Feet"],
    "Wrist": ["Wrists"],
    "Hands": ["Hands"],
    "Finger": ["Ring 1", "Ring 2"],
    "Trinket": ["Trinket 1", "Trinket 2"],
    "Back": ["Back"],
    "Main Hand": ["Main hand"],
    "One-Hand": ["Main hand"],
    "Two-Hand": ["Main hand"],
    "Off Hand": ["Off hand"],
    "Held In Off-hand": ["Off hand"],
    "Shield": ["Off hand"],
    "Ranged": ["Ranged (wand)"],
    "Thrown": ["Ranged (wand)"],
    "INVTYPE_HEAD": ["Head"],
    "INVTYPE_NECK": ["Neck"],
    "INVTYPE_SHOULDER": ["Shoulders"],
    "INVTYPE_CHEST": ["Chest"],
    "INVTYPE_ROBE": ["Chest"],
    "INVTYPE_WAIST": ["Waist"],
    "INVTYPE_LEGS": ["Legs"],
    "INVTYPE_FEET": ["Feet"],
    "INVTYPE_WRIST": ["Wrists"],
    "INVTYPE_HAND": ["Hands"],
    "INVTYPE_FINGER": ["Ring 1", "Ring 2"],
    "INVTYPE_TRINKET": ["Trinket 1", "Trinket 2"],
    "INVTYPE_CLOAK": ["Back"],
    "INVTYPE_WEAPON": ["Main hand"],
    "INVTYPE_2HWEAPON": ["Main hand"],
    "INVTYPE_WEAPONMAINHAND": ["Main hand"],
    "INVTYPE_WEAPONOFFHAND": ["Off hand"],
    "INVTYPE_HOLDABLE": ["Off hand"],
    "INVTYPE_SHIELD": ["Off hand"],
    "INVTYPE_RANGED": ["Ranged (wand)"],
    "INVTYPE_RANGEDRIGHT": ["Ranged (wand)"],
    "INVTYPE_THROWN": ["Ranged (wand)"],
}


def _skills(snapshot: Table, category: str) -> set[str] | None:
    """Skill names under one Skills-tab header, or None if the snapshot has none.

    None means "we can't tell" (an older save, or a game in another language), and
    the caller then skips the check instead of calling everything unusable.
    """
    names = {
        name
        for entry in as_tables(snapshot.get("professions"))
        if as_text(entry.get("category")) == category and (name := as_text(entry.get("name")))
    }
    return names or None


def _cant_use_reason(item: Table, armor: set[str] | None, weapons: set[str] | None) -> str | None:
    """Why this character can't use the item, or None."""
    sub_kind = as_text(item.get("subType")) or ""
    kind = as_text(item.get("type"))
    if kind == "Armor" and armor is not None and sub_kind in ARMOR_SKILL:
        skill = ARMOR_SKILL[sub_kind]
        if skill not in armor:
            return f"armor type {skill}, but this character has no {skill} armor proficiency"
    if kind == "Weapon" and weapons is not None and sub_kind in WEAPON_SKILL:
        skill = WEAPON_SKILL[sub_kind]
        if skill not in weapons:
            return (
                f"weapon type {sub_kind}, but this character has no {skill} weapon skill yet; "
                "a weapon master teaches some weapon skills, so check before selling it"
            )
    return None


def _item_level(item: Table) -> int | float | None:
    return as_number(item.get("itemLevel"))


def _is_gray(item: Table) -> bool:
    return as_number(item.get("quality")) == GRAY_QUALITY


def _weakest_worn(candidates: list[Table]) -> Table:
    """The worn item a new ring or trinket would replace: gray first, then lowest level.

    An item with no item level counts as strong, so we never claim an upgrade over it.
    """
    return min(
        candidates,
        key=lambda worn: (not _is_gray(worn), _item_level(worn) or float("inf")),
    )


def _worn_text(worn: Table) -> str:
    details = []
    if (level := _item_level(worn)) is not None:
        details.append(f"item level {number_text(level)}")
    if _is_gray(worn):
        details.append("gray")
    name = as_text(worn.get("name")) or "?"
    return f"{name} ({', '.join(details)})" if details else name


def _is_better(item: Table, worn: Table) -> bool:
    """The simple rule: a higher item level, or a real item replacing a gray one.

    Needs the numbers on both sides; with a missing item level we say nothing.
    """
    new_level, worn_level = _item_level(item), _item_level(worn)
    if new_level is not None and worn_level is not None and new_level > worn_level:
        return True
    return _is_gray(worn) and as_number(item.get("quality")) not in (None, GRAY_QUALITY)


def _upgrade_target(item: Table, worn_items: list[Table]) -> str | None:
    """The "for ..." part of an upgrade hint, or None when it is not an upgrade."""
    slots = SLOTS_FOR_EQUIP.get(as_text(item.get("equipSlot")) or "")
    if not slots:
        return None
    worn_here = [worn for worn in worn_items if as_text(worn.get("slot")) in slots]
    filled = {as_text(worn.get("slot")) for worn in worn_here}
    for slot in slots:
        if slot not in filled:
            return f"the empty {slot} slot"
    worn = _weakest_worn(worn_here)
    if not _is_better(item, worn):
        return None
    return f"{as_text(worn.get('slot'))}: {_worn_text(worn)}"


def _bag_item_text(item: Table, character_level: int | float | None) -> str:
    details = []
    if (level := _item_level(item)) is not None:
        details.append(f"item level {number_text(level)}")
    required = as_number(item.get("requiredLevel"))
    if required is not None and character_level is not None and required > character_level:
        details.append(f"needs level {number_text(required)}")
    name = as_text(item.get("name")) or "?"
    return f"{name} ({', '.join(details)})" if details else name


def _bag_items(snapshot: Table) -> list[Table]:
    """Every bag item once (several stacks of one name count as one)."""
    seen: set[str] = set()
    items = []
    for container in as_tables(as_table(snapshot.get("bags")).get("containers")):
        for item in as_tables(container.get("items")):
            name = as_text(item.get("name")) or "?"
            if name not in seen:
                seen.add(name)
                items.append(item)
    return items


def gear_hints_section(snapshot: Table) -> str:
    """Bag items the character can't use, then possible upgrades. Empty if neither."""
    armor, weapons = _skills(snapshot, ARMOR_CATEGORY), _skills(snapshot, WEAPON_CATEGORY)
    worn_items = as_tables(snapshot.get("gear"))
    character_level = as_number(snapshot.get("level"))
    cant_use, upgrades = [], []
    for item in _bag_items(snapshot):
        name = as_text(item.get("name")) or "?"
        if reason := _cant_use_reason(item, armor, weapons):
            cant_use.append(f"- Can't use: {name} ({reason})")
        elif target := _upgrade_target(item, worn_items):
            upgrades.append(
                f"- Possible upgrade: {_bag_item_text(item, character_level)} for {target}"
            )
    if not cant_use and not upgrades:
        return ""
    return "\n".join(["**Gear hints** (hints only; the coach decides):", *cant_use, *upgrades])
