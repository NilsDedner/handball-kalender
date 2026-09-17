"""Konfiguration: Saisonfenster & Darstellung aus .env, Mannschaften aus teams.json.

teams.json hält zwei Listen:

* `teams`  – die Mannschaften. Jede bekommt automatisch einen **eigenen Feed**
             (`docs/<slug>.ics`), damit man einzeln abonnieren kann.
* `feeds`  – zusätzliche Sammel-Feeds über mehrere Mannschaften, z.B. „alle" oder
             „alle außer der Ersten". Fehlt die Liste, entsteht ein Feed „alle".
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from src.models import FeedSpec, TeamRef

load_dotenv()

TEAMS_FILE = Path(os.environ.get("TEAMS_FILE", "teams.json"))

SETUP_HINWEIS = (
    "Mannschaften findest du mit:\n"
    "  python -m tools.discover <Vereinsname>\n"
    "und fügst sie hinzu mit:\n"
    '  python -m tools.teams add --team <id> [--phase <id>] --label "1. Herren"'
)


@dataclass
class Config:
    teams: list[TeamRef] = field(default_factory=list)
    feeds: list[FeedSpec] = field(default_factory=list)
    season_start: str = "2026-08-01"   # inkl.
    season_end: str = "2027-06-30"     # inkl.
    timezone: str = "Europe/Berlin"
    calendar_name: str = "Handball"
    match_duration_min: int = 120

    @classmethod
    def from_env(cls) -> "Config":
        teams, feeds = load_setup()
        return cls(
            teams=teams,
            feeds=feeds,
            season_start=env("SEASON_START", "2026-08-01"),
            season_end=env("SEASON_END", "2027-06-30"),
            timezone=env("TIMEZONE", "Europe/Berlin"),
            calendar_name=env("CALENDAR_NAME", "Handball"),
            match_duration_min=int(env("MATCH_DURATION_MIN", "120")),
        )


def env(name: str, default: str) -> str:
    """Umgebungsvariable lesen; leere Werte gelten als nicht gesetzt."""
    return (os.environ.get(name, "") or "").strip() or default


def load_setup(path: Path | None = None) -> tuple[list[TeamRef], list[FeedSpec]]:
    """teams.json lesen. Fehlt die Datei, ist das ein Setup-Hinweis, kein Crash-Log."""
    p = path or TEAMS_FILE
    if not p.exists():
        raise SystemExit(f"{p} fehlt. {SETUP_HINWEIS}")

    daten = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(daten, list):          # Kurzform: nur eine Mannschaftsliste
        daten = {"teams": daten}

    teams = [TeamRef.from_dict(t) for t in (daten.get("teams") or [])]
    if not teams:
        raise SystemExit(f"In {p} ist keine Mannschaft eingetragen.\n{SETUP_HINWEIS}")
    _slugs_eindeutig(teams)

    feeds = [FeedSpec.from_dict(f) for f in (daten.get("feeds") or [])]
    if not feeds and len(teams) > 1:
        # Bei einer einzigen Mannschaft wäre „alle“ eine Kopie ihres Feeds unter
        # zweitem Namen – zwei Abo-URLs für denselben Spielplan.
        feeds = [FeedSpec(label="Alle Mannschaften", slug="alle")]
    _feeds_pruefen(feeds, teams, p)

    return teams, feeds


def save_setup(
    teams: list[TeamRef], feeds: list[FeedSpec] | None = None, path: Path | None = None
) -> Path:
    """teams.json schreiben (stabile Reihenfolge, damit Diffs lesbar bleiben)."""
    p = path or TEAMS_FILE
    inhalt: dict = {"teams": [t.as_dict() for t in teams]}
    if feeds:
        inhalt["feeds"] = [f.as_dict() for f in feeds]
    p.write_text(json.dumps(inhalt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def _slugs_eindeutig(teams: list[TeamRef]) -> None:
    """Gleiche Labels würden denselben Dateinamen ergeben – durchnummerieren."""
    vergeben: dict[str, int] = {}
    for t in teams:
        basis = t.feed_slug
        if basis in vergeben:
            vergeben[basis] += 1
            t.slug = f"{basis}-{vergeben[basis]}"
        else:
            vergeben[basis] = 1


def _feeds_pruefen(feeds: list[FeedSpec], teams: list[TeamRef], p: Path) -> None:
    """Tippfehler in `feeds.teams` früh melden statt still einen leeren Feed zu bauen."""
    bekannt = {t.feed_slug for t in teams}
    for f in feeds:
        unbekannt = [s for s in f.teams if s not in bekannt]
        if unbekannt:
            raise SystemExit(
                f"Feed '{f.label}' in {p} nennt unbekannte Mannschaften: "
                f"{', '.join(unbekannt)}.\nVerfügbar: {', '.join(sorted(bekannt))}"
            )
