"""Report sections about everything else on the character sheet.

Faction and guild, stats, buffs, the spellbook, action bars, reputations, currencies,
Forever's Legacy system, group and pet, and mounts. Pure functions like the rest of the
report: snapshot tables in, Markdown text out, ``""`` when the data is missing.
"""

from wow_coach.report_values import (
    Table,
    as_number,
    as_table,
    as_tables,
    as_text,
    as_texts,
    format_age,
    format_time_span,
    number_text,
)

ACTION_BAR_SLOTS = 12  # each action bar has 12 slots; slots 1-12 are the main bar


def _percent(value: float) -> str:
    """``4.3%``: one decimal at most."""
    return f"{round(value, 1):g}%"


def character_section(snapshot: Table, now: float) -> str:
    """Faction, guild, resting, play time and achievement points."""
    parts = []
    if faction := as_text(snapshot.get("faction")):
        parts.append(f"**Faction:** {faction}")
    guild = as_table(snapshot.get("guild"))
    if guild_name := as_text(guild.get("name")):
        rank = as_text(guild.get("rank"))
        parts.append(f"**Guild:** {guild_name}" + (f" (rank {rank})" if rank else ""))
    if snapshot.get("resting") is True:
        parts.append("**Resting:** yes (in an inn or a city, rested XP builds up)")
    played = as_table(snapshot.get("timePlayed"))
    total = as_number(played.get("total"))
    if total is not None:
        level = as_number(played.get("thisLevel")) or 0
        seen_at = as_number(played.get("seenAt"))
        when = f", as of {format_age(now - seen_at)}" if seen_at is not None else ""
        parts.append(
            f"**Time played:** {format_time_span(total)} "
            f"(this level {format_time_span(level)}{when})"
        )
    points = as_number(snapshot.get("achievementPoints"))
    if points is not None:
        parts.append(f"**Achievement points:** {number_text(points)}")
    return "\n".join(parts)


def _spell_damage_line(stats: Table) -> str:
    """One number when every school has the same bonus, else one per school."""
    schools = [
        (as_text(entry.get("school")) or "?", as_number(entry.get("value")))
        for entry in as_tables(stats.get("spellDamage"))
    ]
    values = {value for _, value in schools if value is not None}
    if not values:
        return ""
    if len(values) == 1:
        return f"Spell damage bonus: {number_text(values.pop())} (all schools)"
    shown = ", ".join(
        f"{school} {number_text(value)}" for school, value in schools if value is not None
    )
    return f"Spell damage bonus: {shown}"


def _bar(name: str, value: float | None, maximum: float | None) -> str:
    if value is None or not maximum:
        return ""
    return f"{name}: {number_text(value)}/{number_text(maximum)}"


def stats_section(snapshot: Table) -> str:
    """Health, mana and the numbers on the character window's stat list."""
    stats = as_table(snapshot.get("stats"))
    if not stats:
        return ""
    power_type = as_text(stats.get("powerType"))
    lines = [
        _bar("Health", as_number(stats.get("health")), as_number(stats.get("healthMax"))),
        _bar(
            power_type.capitalize() if power_type else "Power",
            as_number(stats.get("power")),
            as_number(stats.get("powerMax")),
        ),
    ]
    attributes = [
        f"{as_text(entry.get('name')) or '?'} {number_text(value)}"
        for entry in as_tables(stats.get("attributes"))
        if (value := as_number(entry.get("value"))) is not None
    ]
    lines.append(", ".join(attributes))
    if (armor := as_number(stats.get("armor"))) is not None:
        lines.append(f"Armor: {number_text(armor)}")
    resistances = [
        f"{as_text(entry.get('school')) or '?'} {number_text(value)}"
        for entry in as_tables(stats.get("resistances"))
        if (value := as_number(entry.get("value")))
    ]
    if resistances:
        lines.append("Resistances: " + ", ".join(resistances))
    lines.append(_spell_damage_line(stats))
    other = []
    for key, label in (
        ("spellCrit", "spell crit"),
        ("meleeCrit", "melee crit"),
        ("dodge", "dodge"),
    ):
        if (value := as_number(stats.get(key))) is not None:
            other.append(f"{label} {_percent(value)}")
    if (attack_power := as_number(stats.get("attackPower"))) is not None:
        other.append(f"attack power {number_text(attack_power)}")
    if (healing := as_number(stats.get("healing"))) is not None:
        other.append(f"healing bonus {number_text(healing)}")
    if other:
        lines.append(", ".join(other))
    regen = as_number(stats.get("manaRegen"))
    if regen is not None:
        # The game gives mana per second; players think in mana per 5 seconds.
        casting = as_number(stats.get("manaRegenCasting")) or 0
        per_5, casting_per_5 = round(regen * 5, 1), round(casting * 5, 1)
        lines.append(f"Mana regen per 5 s: {per_5:g} (while casting: {casting_per_5:g})")
    shown = [f"- {line}" for line in lines if line]
    return "\n".join(["**Stats:**", *shown]) if shown else ""


def auras_section(snapshot: Table) -> str:
    """Buffs and debuffs right now, with the time left."""
    lines = []
    for aura in as_tables(snapshot.get("auras")):
        details = [as_text(aura.get("kind")) or "aura"]
        if (stacks := as_number(aura.get("stacks"))) is not None:
            details.append(f"{number_text(stacks)} stacks")
        if (seconds := as_number(aura.get("seconds"))) is not None:
            details.append(f"{format_time_span(seconds)} left")
        lines.append(f"- {as_text(aura.get('name')) or '?'} ({', '.join(details)})")
    return "\n".join(["**Buffs and debuffs:**", *lines]) if lines else ""


def spells_section(snapshot: Table) -> str:
    """The spellbook by tab, with ranks; passives on their own line.

    Snapshots from before addon 0.6.0 only have the ``spells`` name list.
    """
    book = as_tables(snapshot.get("spellBook"))
    if not book:
        names = as_texts(snapshot.get("spells"))
        return f"**Spells:** {', '.join(names)}" if names else ""
    by_tab: dict[str, list[str]] = {}
    passives = []
    for spell in book:
        name = as_text(spell.get("name")) or "?"
        rank = as_text(spell.get("rank"))
        text = f"{name} ({rank})" if rank else name
        if spell.get("passive") is True:
            passives.append(text)
        else:
            by_tab.setdefault(as_text(spell.get("tab")) or "Other", []).append(text)
    lines = [f"- {tab}: {', '.join(spells)}" for tab, spells in by_tab.items()]
    if passives:
        lines.append(f"- Passive: {', '.join(passives)}")
    return "\n".join(["**Spells:**", *lines])


def action_bars_section(snapshot: Table) -> str:
    """What sits on each action bar: ``Main bar: 1 Frostbolt, 2 Fireball``."""
    bars: dict[int, list[str]] = {}
    for action in as_tables(snapshot.get("actionBars")):
        slot = as_number(action.get("slot"))
        if slot is None:
            continue
        bar, key = divmod(int(slot) - 1, ACTION_BAR_SLOTS)
        bars.setdefault(bar, []).append(f"{key + 1} {as_text(action.get('name')) or '?'}")
    lines = []
    for bar, actions in bars.items():
        first = bar * ACTION_BAR_SLOTS + 1
        label = "Main bar" if bar == 0 else f"Slots {first}-{first + ACTION_BAR_SLOTS - 1}"
        lines.append(f"- {label}: {', '.join(actions)}")
    return "\n".join(["**Action bars:**", *lines]) if lines else ""


def reputation_section(snapshot: Table) -> str:
    """Standing with every faction the reputation window shows."""
    lines = []
    for faction in as_tables(snapshot.get("reputations")):
        name = as_text(faction.get("name")) or "?"
        if faction.get("collapsed") is True:
            lines.append(f"- {name}: collapsed in the reputation window, so not read")
            continue
        text = f"- {name}: {as_text(faction.get('standing')) or '?'}"
        value, maximum = as_number(faction.get("value")), as_number(faction.get("max"))
        if value is not None and maximum:
            text += f" {number_text(value)}/{number_text(maximum)}"
        if faction.get("atWar") is True:
            text += " (at war)"
        lines.append(text)
    return "\n".join(["**Reputation:**", *lines]) if lines else ""


def currencies_section(snapshot: Table) -> str:
    """Everything on the Currency tab."""
    parts = []
    for currency in as_tables(snapshot.get("currencies")):
        quantity = as_number(currency.get("quantity")) or 0
        parts.append(f"{as_text(currency.get('name')) or '?'} {number_text(quantity)}")
    return f"**Currencies:** {', '.join(parts)}" if parts else ""


def legacy_section(snapshot: Table) -> str:
    """Forever's Legacy system: reward track, points, perks and class challenges."""
    legacy = as_table(snapshot.get("legacy"))
    if not legacy:
        return ""
    lines = []
    summary = []
    if (renown := as_number(legacy.get("renown"))) is not None:
        summary.append(f"reward track level {number_text(renown)}")
    if (points := as_number(legacy.get("points"))) is not None:
        summary.append(f"{number_text(points)} Legacy points to spend")
    if summary:
        lines.append("- " + ", ".join(summary))
    perks = []
    for perk in as_tables(legacy.get("perks")):
        rank, max_rank = as_number(perk.get("rank")), as_number(perk.get("maxRank"))
        ranks = f"{number_text(rank)}/{number_text(max_rank)}" if rank and max_rank else "?"
        perks.append(
            f"{as_text(perk.get('name')) or '?'} ({as_text(perk.get('tree')) or '?'}, {ranks})"
        )
    if perks:
        lines.append("- Perks: " + ", ".join(perks))
    for challenge in as_tables(legacy.get("challenges")):
        box = "[x]" if challenge.get("done") is True else "[ ]"
        description = as_text(challenge.get("description"))
        name = as_text(challenge.get("name")) or "?"
        lines.append(f"- {box} {name}" + (f": {description}" if description else ""))
    return "\n".join(["**Legacy:**", *lines]) if lines else ""


def group_section(snapshot: Table) -> str:
    """The party or raid, and the pet."""
    lines = []
    group = as_table(snapshot.get("group"))
    if group:
        members = []
        for member in as_tables(group.get("members")):
            level = as_number(member.get("level"))
            level_text = number_text(level) if level is not None else "?"
            members.append(
                f"{as_text(member.get('name')) or '?'} "
                f"(level {level_text} {as_text(member.get('class')) or ''})".replace(" )", ")")
            )
        lines.append(f"**Group:** {as_text(group.get('kind')) or 'group'}: {', '.join(members)}")
    pet = as_table(snapshot.get("pet"))
    if pet:
        level = as_number(pet.get("level"))
        family = as_text(pet.get("family"))
        text = f"**Pet:** {as_text(pet.get('name')) or '?'}"
        if level is not None:
            text += f", level {number_text(level)}"
        lines.append(text + (f" {family}" if family else ""))
    return "\n".join(lines)


def mounts_section(snapshot: Table) -> str:
    """The mounts the character owns."""
    mounts = as_texts(snapshot.get("mounts"))
    return f"**Mounts:** {', '.join(mounts)}" if mounts else ""
