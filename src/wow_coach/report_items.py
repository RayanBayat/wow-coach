"""Report sections about items: gear, bags, bank, mail and recipes.

Pure functions like the rest of the report: snapshot tables in, Markdown text out.
Each section returns ``""`` when its data is missing, so it simply disappears.

Items appear in many places (bags, bank, worn gear), but they all have the same shape;
see "Containers and items" in ``docs/design.md``.
"""

from typing import NamedTuple

from wow_coach.report_values import (
    Table,
    as_number,
    as_table,
    as_tables,
    as_text,
    as_texts,
    format_age,
    format_money,
    number_text,
)

QUALITY_NAMES = {0: "gray", 1: "white", 2: "green", 3: "blue", 4: "purple", 5: "orange"}
GRAY_QUALITY = 0
RECIPE_COLOR_HELP = "orange = sure skill-up, yellow = likely, green = rare, gray = never"


# ---------------------------------------------------------------------------
# One item
# ---------------------------------------------------------------------------


def _quality_name(item: Table) -> str | None:
    quality = as_number(item.get("quality"))
    if quality is None:
        return None
    return QUALITY_NAMES.get(int(quality), f"quality {int(quality)}")


def _item_kind(item: Table) -> str | None:
    """``Armor / Cloth``, or just ``Junk`` when both words are the same."""
    kind, sub_kind = as_text(item.get("type")), as_text(item.get("subType"))
    if kind and sub_kind and sub_kind != kind:
        return f"{kind} / {sub_kind}"
    return kind


def _item_details(item: Table, *, worn: bool) -> list[str]:
    """Item level, quality, slot, needed level and stats, as short phrases.

    ``worn`` is for gear lines: they always show the item level and leave out the
    slot word, because the line already starts with the slot.
    """
    details: list[str] = []
    slot = as_text(item.get("equipSlot"))
    item_level = as_number(item.get("itemLevel"))
    # Item level only matters for things you wear (cloth and food have one too).
    if item_level is not None and (slot or worn):
        details.append(f"item level {number_text(item_level)}")
    if quality := _quality_name(item):
        details.append(quality)
    if slot and not worn:
        details.append(slot)
    required = as_number(item.get("requiredLevel"))
    if required is not None and required > 1:
        details.append(f"needs level {number_text(required)}")
    details.extend(as_texts(item.get("stats")))
    return details


def _with_details(text: str, details: list[str]) -> str:
    return f"{text} ({', '.join(details)})" if details else text


# ---------------------------------------------------------------------------
# Gear
# ---------------------------------------------------------------------------


def _gear_line(item: Table) -> str:
    slot = as_text(item.get("slot")) or "?"
    name = as_text(item.get("name")) or "(unknown item)"
    details = _item_details(item, worn=True)
    durability, durability_max = (
        as_number(item.get("durability")),
        as_number(item.get("durabilityMax")),
    )
    if durability is not None and durability_max:
        details.append(f"durability {number_text(durability)}/{number_text(durability_max)}")
    return _with_details(f"- {slot}: {name}", details)


def gear_section(snapshot: Table) -> str:
    """The worn items, one line per slot."""
    gear = as_tables(snapshot.get("gear"))
    return "\n".join(["**Gear:**", *(_gear_line(item) for item in gear)]) if gear else ""


# ---------------------------------------------------------------------------
# Containers: bags, bank tabs
# ---------------------------------------------------------------------------


class _ItemGroup(NamedTuple):
    """All stacks of one item (same name and quality), added up."""

    item: Table  # the first stack, for the details
    total: int  # how many, all stacks together


def _group_items(containers: list[Table]) -> list[_ItemGroup]:
    """One group per item, in the order they first appear."""
    counts: dict[tuple[str, object], int] = {}
    firsts: dict[tuple[str, object], Table] = {}
    for container in containers:
        for item in as_tables(container.get("items")):
            key = (as_text(item.get("name")) or "?", item.get("quality"))
            firsts.setdefault(key, item)
            counts[key] = counts.get(key, 0) + int(as_number(item.get("count")) or 1)
    return [_ItemGroup(firsts[key], counts[key]) for key in firsts]


def _item_group_line(group: _ItemGroup) -> str:
    item = group.item
    name = as_text(item.get("name")) or "?"
    count = f" x{group.total}" if group.total > 1 else ""
    details = _item_details(item, worn=False)
    if kind := _item_kind(item):
        details.append(kind)
    sell_price = as_number(item.get("sellPrice"))
    if item.get("noValue") is True:
        details.append("vendors won't buy it")
    elif sell_price:
        details.append(f"sells for {format_money(int(sell_price))} each")
    if item.get("bound") is True:
        details.append("soulbound")
    return _with_details(f"- {name}{count}", details)


def _container_summary(containers: list[Table]) -> str:
    """``Backpack 16 slots (3 free), Small Brown Pouch 6 slots (0 free)``."""
    parts = []
    for container in containers:
        bag = as_number(container.get("bag"))
        name = as_text(container.get("name")) or (
            f"bag {number_text(bag)}" if bag is not None else "bag"
        )
        if container.get("account") is True:
            name += " [account bank]"
        slots = number_text(as_number(container.get("slots")) or 0)
        free = number_text(as_number(container.get("free")) or 0)
        parts.append(f"{name} {slots} slots ({free} free)")
    return ", ".join(parts)


def _junk_value(containers: list[Table]) -> int:
    """What all gray items together sell for at a vendor, in copper."""
    total = 0
    for container in containers:
        for item in as_tables(container.get("items")):
            if as_number(item.get("quality")) == GRAY_QUALITY and item.get("noValue") is not True:
                price = as_number(item.get("sellPrice")) or 0
                total += int(price * (as_number(item.get("count")) or 1))
    return total


def bags_section(snapshot: Table) -> str:
    """Free slots, the bags themselves, the junk value and every item."""
    bags = as_table(snapshot.get("bags"))
    free, total = as_number(bags.get("free")), as_number(bags.get("total"))
    if free is None or total is None:
        return ""
    lines = [f"**Bags:** {number_text(free)}/{number_text(total)} slots free"]
    containers = as_tables(bags.get("containers"))
    if containers:
        lines.append(f"Bags: {_container_summary(containers)}")
        if junk := _junk_value(containers):
            lines.append(f"Gray (junk) items sell for {format_money(junk)} in total")
        lines.extend(_item_group_line(group) for group in _group_items(containers))
    return "\n".join(lines)


def bank_section(snapshot: Table, now: float) -> str:
    """The bank as the addon last saw it (it can only read it while the bank is open)."""
    bank = as_table(snapshot.get("bank"))
    if not bank:
        if "containers" not in as_table(snapshot.get("bags")):
            return ""  # saved by an addon older than 0.6.0, which never read the bank
        return "**Bank:** not seen yet (open the bank once and the addon remembers it)"
    containers = as_tables(bank.get("containers"))
    seen_at = as_number(bank.get("seenAt"))
    seen = f"seen {format_age(now - seen_at)}" if seen_at is not None else "seen at an unknown time"
    lines = [f"**Bank** ({seen}): {_container_summary(containers) or 'no bank tabs'}"]
    items = [_item_group_line(group) for group in _group_items(containers)]
    lines.extend(items or ["- (empty)"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------


def _letter_line(letter: Table) -> str:
    subject = as_text(letter.get("subject")) or "(no subject)"
    parts = [f"from {as_text(letter.get('sender')) or '?'}"]
    if money := as_number(letter.get("money")):
        parts.append(f"{format_money(int(money))} attached")
    if cod := as_number(letter.get("cod")):
        parts.append(f"cash on delivery {format_money(int(cod))}")
    items = []
    for item in as_tables(letter.get("items")):
        count = as_number(item.get("count")) or 1
        name = as_text(item.get("name")) or "?"
        items.append(f"{name} x{number_text(count)}" if count > 1 else name)
    if items:
        parts.append("items: " + ", ".join(items))
    days_left = as_number(letter.get("daysLeft"))
    if days_left is not None:
        parts.append(f"{number_text(days_left)} days left")
    return f"- {subject} ({', '.join(parts)})"


def mail_section(snapshot: Table, now: float) -> str:
    """The mailbox as the addon last saw it."""
    mail = as_table(snapshot.get("mail"))
    if not mail:
        return ""
    letters = as_tables(mail.get("letters"))
    seen_at = as_number(mail.get("seenAt"))
    seen = f"seen {format_age(now - seen_at)}" if seen_at is not None else "seen at an unknown time"
    count = "1 letter" if len(letters) == 1 else f"{len(letters)} letters"
    return "\n".join([f"**Mail** ({seen}): {count}", *(_letter_line(letter) for letter in letters)])


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------


def _profession_recipes(profession: Table, now: float) -> list[str]:
    name = as_text(profession.get("profession")) or "?"
    rank, max_rank = as_number(profession.get("rank")), as_number(profession.get("maxRank"))
    if rank is not None and max_rank is not None:
        name += f" {number_text(rank)}/{number_text(max_rank)}"
    recipes = as_tables(profession.get("recipes"))
    seen_at = as_number(profession.get("seenAt"))
    seen = f"seen {format_age(now - seen_at)}" if seen_at is not None else "seen at an unknown time"
    lines = [f"- {name}, {len(recipes)} recipes ({seen}):"]
    for recipe in recipes:
        color = as_text(recipe.get("color"))
        recipe_name = as_text(recipe.get("name")) or "?"
        lines.append(f"  - {recipe_name} ({color})" if color else f"  - {recipe_name}")
    return lines


def recipes_section(snapshot: Table, now: float) -> str:
    """Every learned recipe per profession, with its skill-up color."""
    professions = as_tables(snapshot.get("recipes"))
    if not professions:
        return ""
    lines = [f"**Recipes** ({RECIPE_COLOR_HELP}):"]
    for profession in professions:
        lines.extend(_profession_recipes(profession, now))
    return "\n".join(lines)
