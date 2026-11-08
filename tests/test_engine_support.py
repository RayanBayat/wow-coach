"""Shared setup for the engine tests: a tiny game folder with a save and a data folder."""

from dataclasses import dataclass, field
from pathlib import Path

from wow_coach.app_settings import AppSettings

KEY = "Testchar-Testrealm"
SAVED_AT = 1793900000
NOW = SAVED_AT + 300

SAVE = """\
HeroBridgeDB = {
["formatVersion"] = 1,
["characters"] = {
["Testchar-Testrealm"] = {
["snapshot"] = {
["savedAt"] = 1793900000,
["name"] = "Testchar",
["realm"] = "Testrealm",
["race"] = "Undead",
["class"] = "Mage",
["level"] = 7,
["zone"] = "Tirisfal Glades",
["quests"] = {
{ ["questID"] = 3902, ["title"] = "The Damned", ["level"] = 5, ["complete"] = false },
},
["group"] = { ["kind"] = "party", ["members"] = {
{ ["name"] = "Bobby", ["level"] = 7, ["class"] = "Priest" },
} },
["mail"] = { ["seenAt"] = 1793899000, ["letters"] = {
{ ["sender"] = "Gorbo", ["subject"] = "Gorbo says hi", ["money"] = 0, ["items"] = {} },
{ ["sender"] = "Auction House", ["subject"] = "Auction won", ["money"] = 0, ["items"] = {} },
} },
},
["history"] = {
{ ["time"] = 1793899500, ["kind"] = "death", ["text"] = "Died to Zandor in Brill",
  ["attackers"] = { { ["name"] = "Zandor", ["level"] = 9, ["isPlayer"] = true },
                    { ["name"] = "Wolf", ["level"] = 3 } } },
{ ["time"] = 1793899800, ["kind"] = "item", ["text"] = "Got Linen Cloth from Mirela",
  ["from"] = "Mirela" },
},
["questions"] = {
{ ["id"] = "1793899900-1", ["text"] = "Where do I train?", ["askedAt"] = 1793899900 },
{ ["id"] = "1793899950-2", ["text"] = "What about Bobby?", ["askedAt"] = 1793899950 },
},
},
},
}
"""

GOOD_REPLY = (
    '{"title": "Next steps", "steps": ["Go to Brill", "Train spells"], '
    '"text": "You are level 7.", "warnings": ["Watch your health"]}'
)


@dataclass(frozen=True)
class World:
    """A fake game folder and data folder, both inside ``tmp_path``."""

    wow_dir: Path
    environ: dict[str, str]
    settings: AppSettings = field(default_factory=AppSettings)

    @property
    def advice_file(self) -> Path:
        return self.wow_dir / "Interface" / "AddOns" / "HeroBridge_Advice" / "Advice.lua"


def make_world(tmp_path: Path, *, save: str = SAVE) -> World:
    wow_dir = tmp_path / "wow"
    saved = wow_dir / "WTF" / "Account" / "ACCOUNT1" / "SavedVariables"
    saved.mkdir(parents=True)
    (saved / "HeroBridge.lua").write_text(save, encoding="utf-8")
    addons = wow_dir / "Interface" / "AddOns" / "HeroBridge"
    addons.mkdir(parents=True)
    (addons / "HeroBridge.toc").write_text("## Interface: 11507\n", encoding="utf-8")
    data = tmp_path / "data"
    environ = {"WOW_COACH_DATA_DIR": str(data / "wow-coach")}
    return World(wow_dir=wow_dir, environ=environ)
