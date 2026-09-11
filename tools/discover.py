"""Mannschaften finden: Verein suchen -> Teams mit Staffeln und IDs auflisten.

    python -m tools.discover Villigst          # Vereine suchen
    python -m tools.discover --club 4868       # Mannschaften des Vereins auflisten

Die API ignoriert Suchparameter auf /teams/clubs, deshalb holen wir das
Vereinsverzeichnis einmal komplett (45 Requests) und legen es in .cache/clubs.json ab.
Mannschaften kommen aus den Spielen des Vereins – dort stehen team_id und Staffel.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from src.client import ApiError, HandballNetClient
from src.config import env

CACHE = Path(".cache/clubs.json")


def clubs_geladen(client: HandballNetClient, *, refresh: bool = False) -> list[dict]:
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    print("→ Vereinsverzeichnis laden (einmalig, ~45 Requests) …", file=sys.stderr)
    clubs = client.clubs()
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(clubs, ensure_ascii=False), encoding="utf-8")
    print(f"→ {len(clubs)} Vereine, gecacht in {CACHE}", file=sys.stderr)
    return clubs


def suche_vereine(client: HandballNetClient, begriff: str, *, refresh: bool) -> None:
    clubs = clubs_geladen(client, refresh=refresh)
    nadel = begriff.lower()
    treffer = [c for c in clubs if nadel in (c.get("name") or "").lower()]

    if not treffer:
        print(f"Kein Verein enthält „{begriff}“.")
        return
    print(f"{len(treffer)} Treffer für „{begriff}“:\n")
    for c in sorted(treffer, key=lambda x: x["name"]):
        verband = (c.get("federation") or {}).get("name", "")
        print(f"  club_id {c['id']:>6}  {c['name']}   [{verband}]")
    print("\nMannschaften eines Vereins:  python -m tools.discover --club <club_id>")


def _club_kennungen(client: HandballNetClient, club_id: int) -> set[str]:
    """Alle Schreibweisen der Vereins-ID sammeln.

    handball.net hat die Vereins-IDs von Zahlen auf Zeichenketten umgestellt
    (4868 -> "1t9yc3c"). Der Filter `?club_id=` nimmt weiter die Zahl, in den
    Daten steht aber die neue Kennung – ohne beides findet man keine Mannschaft.
    """
    kennungen = {str(club_id)}
    try:
        verein = client.get(f"teams/clubs/{club_id}")
        daten = verein.get("data") or verein
        if daten.get("id") is not None:
            kennungen.add(str(daten["id"]))
    except ApiError:
        pass
    return kennungen


def zeige_mannschaften(client: HandballNetClient, club_id: int, *, von: str, bis: str) -> None:
    spiele = client.matches(club_id=club_id, date_from=von, date_to=bis)
    if not spiele:
        print(f"Verein {club_id} hat im Fenster {von} … {bis} keine Spiele.")
        return
    kennungen = _club_kennungen(client, club_id)

    # (team_id, name) -> {(phase_id, staffelname): anzahl}
    teams: dict[tuple[int, str], dict[tuple[int, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for s in spiele:
        phase = s.get("phase") or {}
        for seite in ("local", "visitor"):
            t = s.get(seite) or {}
            if str((t.get("club") or {}).get("id")) in kennungen and t.get("id"):
                key = (int(phase.get("id", 0)), (phase.get("name") or "").strip())
                teams[(int(t["id"]), (t.get("name") or "").strip())][key] += 1

    print(f"Verein {club_id}: {len(teams)} Mannschaft(en), Fenster {von} … {bis}\n")
    for (team_id, name), staffeln in sorted(teams.items(), key=lambda x: x[0][1]):
        print(f"  {name}   (team_id {team_id})")
        mehrere = len(staffeln) > 1
        for (phase_id, staffel), anzahl in sorted(staffeln.items(), key=lambda x: -x[1]):
            print(f"      Staffel {phase_id:>6}  {staffel}  ({anzahl} Spiele)")
        for (phase_id, staffel), _ in sorted(staffeln.items(), key=lambda x: -x[1]):
            phase_arg = f" --phase {phase_id}" if mehrere else ""
            print(
                f'      → python -m tools.teams add --team {team_id}{phase_arg} '
                f'--label "{staffel or name}"'
            )
        if mehrere:
            alle = " ".join(f"--phase {pid}" for pid, _ in staffeln)
            print(
                "      ↑ mehrere Staffeln unter einer team_id. Das können zwei echte\n"
                "        Mannschaften sein (dann je Staffel ein Eintrag) – oder Liga plus\n"
                "        Freundschaftsspiele derselben Mannschaft; dann alles in einen:\n"
                f'        python -m tools.teams add --team {team_id} {alle} --label "…"'
            )
        print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vereine und Mannschaften auf handball.net finden")
    p.add_argument("begriff", nargs="?", help="Teil eines Vereinsnamens")
    p.add_argument("--club", type=int, help="club_id: Mannschaften dieses Vereins auflisten")
    p.add_argument("--refresh", action="store_true", help="Vereins-Cache neu laden")
    p.add_argument("--from", dest="von", default=env("SEASON_START", "2026-08-01"))
    p.add_argument("--to", dest="bis", default=env("SEASON_END", "2027-06-30"))
    args = p.parse_args(argv)

    if not args.begriff and args.club is None:
        p.print_help()
        return 2

    client = HandballNetClient()
    if args.club is not None:
        zeige_mannschaften(client, args.club, von=args.von, bis=args.bis)
    else:
        suche_vereine(client, args.begriff, refresh=args.refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
