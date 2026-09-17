"""Orchestrierung: je konfigurierter Mannschaft die Spiele holen -> aufs Saisonfenster
filtern -> deduplizieren -> je Mannschaft und je Sammel-Feed eine .ics nach docs/
schreiben, dazu eine Übersichtsseite.

Aufruf:  python -m src.main
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from src.client import ApiError, HandballNetClient
from src.config import Config
from src.dashboard import render_dashboard
from src.h4a import H4aError, Handball4AllClient, collect_team_matches as collect_h4a_matches
from src.ics import build_calendar, to_ics_bytes
from src.models import Match, TeamRef
from src.parser import dedupe, to_match

DOCS = Path("docs")
PROBLEME = Path("probleme.txt")   # vom Workflow ausgewertet


def collect_team_matches(
    client: HandballNetClient, team: TeamRef, cfg: Config
) -> list[Match]:
    """Ein Request je Mannschaft; die Staffel-Auswahl filtern wir lokal."""
    rohe = client.matches(
        team_id=team.team_id,
        date_from=cfg.season_start,
        date_to=cfg.season_end,
    )
    passend = [s for s in rohe if team.passt(s)]
    if len(passend) != len(rohe):
        # Die Staffeln benennen, nicht nur zählen: wandert eine Mannschaft in eine
        # neue Staffel, steht hier direkt die ID, die in teams.json gehört.
        fremd = sorted(
            {
                (s["phase"]["id"], (s["phase"].get("name") or "").strip())
                for s in rohe
                if not team.passt(s) and s.get("phase")
            }
        )
        benannt = ", ".join(f"{name} ({pid})" for pid, name in fremd)
        print(
            f"    {len(rohe) - len(passend)} Spiele durch Staffel-Filter aussortiert: {benannt}"
        )

    matches = [m for m in (to_match(s, team) for s in passend) if m is not None]
    verworfen = len(passend) - len(matches)
    if verworfen:
        print(f"    [warn] {verworfen} Spiele ohne lesbares Datum übersprungen", file=sys.stderr)

    ligen = sorted({m.league for m in matches if m.league})
    print(f"    {len(matches)} Spiele | {', '.join(ligen) or 'keine Staffel erkannt'}")
    if len(ligen) > 1 and not (team.phase_ids or team.competition_ids):
        # Genau hierfür gibt es den Staffel-Filter: handball.net führt unter einer
        # team_id mitunter zwei echte Mannschaften (z.B. Oberliga + Bezirksliga).
        print(
            f"    [hinweis] {team.display} taucht in {len(ligen)} Staffeln auf. Sind das zwei "
            "Mannschaften, phase_ids setzen (tools.discover zeigt die IDs).",
            file=sys.stderr,
        )
    return dedupe(matches)


def schreibe_feed(
    matches: list[Match],
    *,
    slug: str,
    name: str,
    cfg: Config,
    gebaut_am: datetime,
) -> tuple[str, str, int]:
    cal = build_calendar(
        matches,
        calendar_name=name,
        timezone=cfg.timezone,
        duration_min=cfg.match_duration_min,
        gebaut_am=gebaut_am,
    )
    (DOCS / f"{slug}.ics").write_bytes(to_ics_bytes(cal))
    return slug, name, len(matches)


def main() -> int:
    cfg = Config.from_env()
    # Beide Clients werden erst beim ersten Zugriff gebaut: wer nur eine Quelle
    # konfiguriert hat, baut auch nur zu dieser eine Verbindung auf.
    clients: dict[str, object] = {}

    def client_fuer(team: TeamRef):
        art = "h4a" if team.ist_h4a else "handballnet"
        if art not in clients:
            clients[art] = Handball4AllClient() if team.ist_h4a else HandballNetClient()
        return clients[art]

    print(f"→ Fenster {cfg.season_start} … {cfg.season_end} | {len(cfg.teams)} Mannschaft(en)")
    je_team: dict[str, list[Match]] = {}
    for team in cfg.teams:
        zusatz = f" [{team.filter_beschreibung}]" if team.filter_beschreibung else ""
        kennung = f"„{team.team_name}“" if team.ist_h4a else f"team_id {team.team_id}"
        print(f"→ {team.display} ({kennung}){zusatz}")
        try:
            if team.ist_h4a:
                je_team[team.feed_slug] = dedupe(
                    collect_h4a_matches(
                        client_fuer(team), team, cfg.season_start, cfg.season_end
                    )
                )
            else:
                je_team[team.feed_slug] = collect_team_matches(client_fuer(team), team, cfg)
        except (ApiError, H4aError) as exc:
            print(f"    [fehler] {exc}", file=sys.stderr)

    if not any(je_team.values()):
        print("Keine Spiele gefunden – nichts geschrieben.", file=sys.stderr)
        return 1

    DOCS.mkdir(exist_ok=True)
    feeds: list[tuple[str, str, int]] = []
    probleme: list[str] = []
    # Ein Zeitstempel für alle Feeds eines Laufs.
    gebaut_am = datetime.now(dt_timezone.utc)

    # Ein Feed je Mannschaft – so kann man einzeln abonnieren und abbestellen.
    for team in cfg.teams:
        matches = je_team.get(team.feed_slug, [])
        if not matches:
            # Eine konfigurierte Mannschaft ohne Spiele ist fast immer ein Fehler in
            # teams.json, kein leerer Spielplan: handball.net vergibt neue team_ids,
            # wenn ein Verein seine Mannschaften neu registriert. Die alte .ics bleibt
            # liegen und wäre sonst wochenlang unbemerkt veraltet.
            kennung = f"„{team.team_name}“" if team.ist_h4a else f"team_id {team.team_id}"
            nachsehen = (
                "python -m tools.h4a <Vereinsname>"
                if team.ist_h4a
                else "python -m tools.discover --club <club_id>"
            )
            probleme.append(
                f"{team.display} ({kennung}"
                + (f", {team.filter_beschreibung}" if team.filter_beschreibung else "")
                + ") liefert keine Spiele – Staffel/Name prüfen: "
                + nachsehen
            )
            continue
        feeds.append(
            schreibe_feed(
                matches,
                slug=team.feed_slug,
                name=f"{cfg.calendar_name}: {team.display}",
                cfg=cfg,
                gebaut_am=gebaut_am,
            )
        )

    # Zusätzlich die konfigurierten Sammel-Feeds.
    for spec in cfg.feeds:
        gesammelt: list[Match] = []
        for team in cfg.teams:
            if spec.gilt_fuer(team):
                gesammelt.extend(je_team.get(team.feed_slug, []))
        # Über Mannschaften hinweg nochmal deduplizieren: ein Derby der eigenen
        # Erster gegen die Zweite ist ein Spiel, kein zweiter Termin.
        gesammelt = dedupe(gesammelt)
        if not gesammelt:
            print(f"    [warn] Feed „{spec.label}“ bleibt leer", file=sys.stderr)
            continue
        feeds.append(
            schreibe_feed(
                gesammelt,
                slug=spec.slug,
                name=f"{cfg.calendar_name}: {spec.label}",
                cfg=cfg,
                gebaut_am=gebaut_am,
            )
        )

    ohne_zeit = sum(1 for ms in je_team.values() for m in ms if m.all_day)
    if ohne_zeit:
        print(f"→ {ohne_zeit} Spiel(e) ohne Anwurfzeit als ganztägiger Termin")

    render_dashboard(
        je_team,
        cfg=cfg,
        feeds=feeds,
        out=DOCS / "index.html",
        gebaut_am=gebaut_am.astimezone(),
    )
    print(f"→ {len(feeds)} Feeds geschrieben:")
    for slug, name, anzahl in feeds:
        print(f"   docs/{slug}.ics   {anzahl:>3} Spiele   {name}")
    print(f"✓ {DOCS / 'index.html'}")

    # Die guten Feeds sind geschrieben und werden veröffentlicht – der Lauf meldet das
    # Problem trotzdem, damit es auffällt. Die Datei wertet der Workflow nach dem
    # Deploy aus und färbt den Lauf rot.
    if probleme:
        print("\n[PROBLEM] " + "\n[PROBLEM] ".join(probleme), file=sys.stderr)
        PROBLEME.write_text("\n".join(probleme) + "\n", encoding="utf-8")
    elif PROBLEME.exists():
        PROBLEME.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
