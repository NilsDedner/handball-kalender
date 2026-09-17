"""Mannschaften bei handball4all finden: Verein suchen -> Staffeln und Teamnamen zeigen.

    python -m tools.h4a Waiblingen                 # Verein suchen (Vorgabe: BWHV)
    python -m tools.h4a --club 148                 # Staffeln des Vereins auflisten
    python -m tools.h4a --club 148 --nur-maenner   # Jugend und Frauen weglassen

Das Portal kennt keinen Mannschaftsfilter: Ein Eintrag in teams.json besteht deshalb
aus der Verbands-ID (`org_id`), einer oder mehreren Staffel-IDs (`class_ids`) und dem
Teamnamen (`team_name`), genau so geschrieben wie in den Spielen.

**Zur neuen Saison ändern sich die Staffel-IDs**, der Teamname bleibt in der Regel.
Dieses Werkzeug zeigt die aktuellen IDs und den passenden teams.json-Eintrag.
"""
from __future__ import annotations

import argparse
import json
import sys

from src.h4a import H4aError, Handball4AllClient

# Verbände, die noch über handball4all laufen. 216 ist der Baden-Württembergische
# Handball-Verband (BWHV), unter dem auch die Bezirksstaffeln liegen.
BWHV = 216


def suche_verein(client: Handball4AllClient, begriff: str, org_id: int) -> int:
    treffer = client.vereinssuche(org_id=org_id, begriff=begriff)
    if not treffer:
        print(f"Kein Verein enthält „{begriff}“ im Verband {org_id}.")
        return 1
    print(f"{len(treffer)} Treffer für „{begriff}“:\n")
    for v in treffer:
        ort = " ".join(t for t in ((v.get("postal") or ""), (v.get("town") or "")) if t)
        print(f"  club_id {v['id']:>6}  {v.get('lname','')}   [{ort}]")
    print(f"\nStaffeln eines Vereins:  python -m tools.h4a --club <club_id> --org {org_id}")
    return 0


def zeige_staffeln(
    client: Handball4AllClient, club_id: int, org_id: int, *, nur_maenner: bool
) -> int:
    payload = client.verein_staffeln(org_id=org_id, club_id=club_id)
    klassen = (payload.get("content") or {}).get("classes") or []
    name = ((payload.get("head") or {}).get("headline2") or "").strip()
    if not klassen:
        print(f"Verein {club_id} hat im Verband {org_id} keine Staffeln.")
        return 1

    print(f"{name}\nVerein {club_id}, Verband {org_id}\n")
    gezeigt = 0
    for cl in klassen:
        # Die Wochenübersicht nennt je Staffel nur die Spiele dieser Woche – daraus
        # lesen wir, unter welchem Namen die eigene Mannschaft dort geführt wird.
        eigene = sorted(
            {
                t.strip()
                for g in (cl.get("games") or [])
                for t in ((g.get("gHomeTeam") or ""), (g.get("gGuestTeam") or ""))
                if t.strip()
            }
        )
        if nur_maenner and cl.get("gClassGender") != "m":
            continue
        if nur_maenner and (cl.get("gClassAGsDesc") or "") not in ("M", "F", ""):
            continue     # Jugend trägt A…F als Altersklasse
        gezeigt += 1
        print(f"  Staffel {cl['gClassID']:>7}  {cl.get('gClassSname','')}  {cl.get('gClassLname','')}")
        if eigene:
            print(f"      Mannschaften diese Woche: {', '.join(eigene)}")
        else:
            print("      (diese Woche kein Spiel – Teamname über die Staffel prüfen)")
    if not gezeigt:
        print("  (keine passende Staffel – ohne --nur-maenner nochmal versuchen)")
        return 1

    print(
        "\nEintrag für teams.json (Teamname exakt wie oben, mehrere Staffeln in einem\n"
        "Eintrag ergeben einen Feed – z.B. Liga und Pokal):\n"
    )
    print(
        json.dumps(
            {
                "label": "1. Herren",
                "source": "h4a",
                "org_id": org_id,
                "class_ids": ["<Staffel-ID>"],
                "team_name": "<Mannschaft>",
                "slug": "mein-team",
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Vereine und Staffeln im Ergebnisportal von handball4all finden"
    )
    p.add_argument("begriff", nargs="?", help="Teil eines Vereinsnamens")
    p.add_argument("--club", type=int, help="club_id: Staffeln dieses Vereins auflisten")
    p.add_argument(
        "--org", type=int, default=BWHV, help=f"Verbands-ID (Vorgabe {BWHV} = BWHV)"
    )
    p.add_argument(
        "--nur-maenner",
        action="store_true",
        help="nur Männer-Staffeln (ohne Jugend und Frauen)",
    )
    args = p.parse_args(argv)

    if not args.begriff and args.club is None:
        p.print_help()
        return 2

    client = Handball4AllClient()
    try:
        if args.club is not None:
            return zeige_staffeln(
                client, args.club, args.org, nur_maenner=args.nur_maenner
            )
        return suche_verein(client, args.begriff, args.org)
    except H4aError as exc:
        print(f"Portal meldet: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
