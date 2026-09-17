"""Datenquelle handball4all – für die Verbände, die handball.net nicht führt.

Warum es diese zweite Quelle gibt: handball.net bezieht seine Spieldaten seit dem
Relaunch ausschließlich aus Handball360. Verbände, die die Umstellung verschoben
haben, sind dort nur als leere Hülle angelegt – der Baden-Württembergische
Handball-Verband (BWHV, darin der frühere HVW) zum Beispiel hat dort 0 Mannschaften
und 0 Spiele, während die DHB-Ligen derselben Vereine (3. Liga, Jugendbundesliga)
normal erscheinen. Der Verband verweist stattdessen auf das Ergebnisportal von
handball4all (Stand 26.08.2026).

Genutzt wird die JSON-Schnittstelle, mit der dieses Portal selbst arbeitet:

    https://spo.handball4all.de/service/if_g_json.php?cmd=…

**Kein Login, kein Token.** Die Antwort ist stets eine Liste mit einem Objekt.
Gebraucht werden drei der erlaubten Kommandos:

| Kommando | Zweck |
|---|---|
| `cmd=ps&og=<Verband>&cl=<Staffel>&ca=1` | kompletter Spielplan einer Staffel |
| `cmd=pcu&og=<Verband>&c=<Verein>`       | Staffeln eines Vereins (für die Suche) |
| `cmd=cs&og=<Verband>&cs=<Name>`         | Vereinssuche |

Zwei Eigenheiten der Schnittstelle:

1. **`og` ist rechtepflichtig.** Der Verband (hier 216 = BWHV) antwortet, die
   Bezirks-IDs aus demselben Menü liefern HTTP 401. Die Staffeln der Bezirke stehen
   trotzdem unter dem Verband bereit, man muss sie nur dort abfragen.
2. **Die Spiele tragen keine Team-ID**, nur Namen – und zwar abgekürzte
   („H2Ku Herrenb. 2“). Die eigene Mannschaft wird deshalb über `team_name`
   erkannt, exakt so geschrieben wie in den Spielen („VfL Waiblingen 2“).
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime

import requests

from src.models import Match, TeamRef
from src.parser import tidy_caps

BASE = "https://spo.handball4all.de/service/if_g_json.php"
SITE = "https://www.handball4all.de/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "handballnet-kalender/1.0 (privates Kalender-Abo)"
)
POLITE_DELAY_S = 0.4
RETRIES = 3

# Portal-Adresse für den Link im Termin. Die Portalseiten heißen nach dem Verband;
# fehlt der Eintrag, verweist der Termin auf die Startseite statt auf eine 404.
PORTAL_SLUGS = {216: "baden-wuerttembergischer-hv"}
PORTAL_LIGA = "https://www.handball4all.de/home/portal/{slug}#/league?ogId={og}&lId={cl}"

# Bemerkungen, bei denen das Spiel nicht stattfindet. Die Schnittstelle hat kein
# Status-Feld – der Spielbetrieb schreibt es in `gComment`.
_ABGESETZT = ("abgesetzt", "ausgefallen", "annulliert", "abgebrochen", "nicht angetreten")

_DATUM_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})$")
_ZEIT_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


class H4aError(RuntimeError):
    pass


class Handball4AllClient:
    def __init__(self, *, delay: float = POLITE_DELAY_S):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "de-DE,de;q=0.9",
                "Referer": SITE,
            }
        )
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def get(self, params: dict) -> dict:
        """Ein Kommando abrufen. Die Antwort ist eine Liste mit genau einem Objekt."""
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        last_exc: Exception | None = None

        for versuch in range(1, RETRIES + 1):
            self._throttle()
            try:
                resp = self.session.get(BASE, params=clean, timeout=30)
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code == 401:
                    # Kein Übergangsfehler: diese og-ID gibt das Portal nicht heraus.
                    raise H4aError(
                        f"HTTP 401 für {clean}. Der Verband gibt diese Kennung nicht "
                        "heraus – die Staffeln der Bezirke stehen unter der "
                        "Verbands-ID (org_id) bereit."
                    )
                if resp.status_code >= 500:
                    last_exc = H4aError(f"HTTP {resp.status_code} für {clean}")
                else:
                    daten = resp.json()
                    payload = daten[0] if isinstance(daten, list) else daten
                    fehler = payload.get("error")
                    if fehler:
                        raise H4aError(
                            f"{fehler if isinstance(fehler, str) else '; '.join(fehler)}"
                        )
                    return payload
            if versuch < RETRIES:
                time.sleep(self.delay * 4 * versuch)

        raise H4aError(f"{clean} nach {RETRIES} Versuchen fehlgeschlagen: {last_exc}")

    # ------------------------------------------------------------------ Kommandos
    def staffel(self, *, org_id: int, class_id: int, period_id: int | None = None) -> dict:
        """Kompletter Spielplan einer Staffel.

        `ca=1` liefert die ganze Runde in `futureGames`; ohne den Schalter teilt das
        Portal in „aktuelle Woche“ und „Rest“ und lässt Gespieltes weg.
        Ohne `p` antwortet die Schnittstelle für die laufende Saison – damit
        stimmt die Staffel-ID zur Saison, ohne dass wir sie mitpflegen müssen.
        """
        return self.get({"cmd": "ps", "og": org_id, "cl": class_id, "ca": 1, "p": period_id})

    def verein_staffeln(self, *, org_id: int, club_id: int) -> dict:
        """Alle Staffeln, in denen ein Verein Mannschaften hat."""
        return self.get({"cmd": "pcu", "og": org_id, "c": club_id})

    def vereinssuche(self, *, org_id: int, begriff: str) -> list[dict]:
        payload = self.get({"cmd": "cs", "og": org_id, "cs": begriff})
        return (payload.get("searchResult") or {}).get("list") or []


# ------------------------------------------------------------------ Übersetzung
def parse_datum(datum: str, zeit: str) -> datetime | None:
    """„19.09.26“ + „15:30“ -> Ortszeit. Ohne Anwurfzeit: 00:00 (ganztägig)."""
    m = _DATUM_RE.match((datum or "").strip())
    if not m:
        return None
    tag, monat, jahr = (int(g) for g in m.groups())
    z = _ZEIT_RE.match((zeit or "").strip())
    stunde, minute = (int(g) for g in z.groups()) if z else (0, 0)
    return datetime(2000 + jahr, monat, tag, stunde, minute)


def _ergebnis(spiel: dict) -> str:
    """„28:24“ – oder leer, wenn noch nicht gespielt.

    Die Felder stehen vor dem Spiel als Leerzeichen in der Antwort. Ein 0:0 nach
    Spielende ist ein gemeldeter Ausfall, kein Ergebnis, und bleibt draußen.
    """
    heim, gast = (spiel.get("gHomeGoals") or "").strip(), (spiel.get("gGuestGoals") or "").strip()
    if not heim.isdigit() or not gast.isdigit():
        return ""
    if not int(heim) and not int(gast):
        return ""
    return f"{heim}:{gast}"


def _adresse(spiel: dict) -> str:
    strasse = (spiel.get("gGymnasiumStreet") or "").strip()
    plz = (spiel.get("gGymnasiumPostal") or "").strip()
    ort = (spiel.get("gGymnasiumTown") or "").strip()
    ortsteil = " ".join(t for t in (plz, ort) if t)
    return ", ".join(t for t in (strasse, ortsteil) if t)


def _bemerkung(spiel: dict) -> str:
    """Bemerkung und Rundenname der Quelle, beides oft nur ein Leerzeichen."""
    teile = [
        (spiel.get("gGroupsortTxt") or "").strip(),   # „1. Runde“ im Pokal
        (spiel.get("gComment") or "").strip(),        # „alt 8082“, „abgesetzt“
    ]
    return " · ".join(t for t in teile if t)


def to_match(spiel: dict, team: TeamRef, *, liga: str, link: str) -> Match | None:
    """Ein Spiel des Portals in ein `Match` übersetzen. None ohne lesbares Datum."""
    start = parse_datum(spiel.get("gDate"), spiel.get("gTime"))
    if start is None:
        return None

    heim = (spiel.get("gHomeTeam") or "").strip()
    gast = (spiel.get("gGuestTeam") or "").strip()
    bemerkung = _bemerkung(spiel)
    ergebnis = _ergebnis(spiel)
    abgesetzt = any(w in bemerkung.lower() for w in _ABGESETZT)

    return Match(
        team=team,
        id=int(spiel["gID"]),
        start=start,
        all_day=(start.hour == 0 and start.minute == 0),
        home=tidy_caps(heim),
        away=tidy_caps(gast),
        is_home=(heim == team.team_name),
        league=liga,
        status="Abgesetzt" if abgesetzt else ("Beendet" if ergebnis else "Angesetzt"),
        finished=bool(ergebnis),
        result=ergebnis,
        venue=tidy_caps((spiel.get("gGymnasiumName") or "").strip()),
        address=tidy_caps(_adresse(spiel)),
        referees=[r.strip() for r in (spiel.get("gReferee") or "").split(",") if r.strip()],
        dedupe_key=(start, heim, gast),
        note=bemerkung,
        link=link,
    )


def _liganame(staffel: dict) -> str:
    """Sprechender Name der Staffel, z.B. „Männer-Landesliga Staffel 2 (M-LL-2-BW)“."""
    lang = (staffel.get("gClassLname") or "").strip()
    kurz = (staffel.get("gClassSname") or "").strip()
    if lang and kurz and kurz not in lang:
        return f"{lang} ({kurz})"
    return lang or kurz


def _portal_link(org_id: int, class_id: int) -> str:
    slug = PORTAL_SLUGS.get(org_id)
    if not slug:
        return SITE
    return PORTAL_LIGA.format(slug=slug, og=org_id, cl=class_id)


def collect_team_matches(
    client: Handball4AllClient, team: TeamRef, season_start: str, season_end: str
) -> list[Match]:
    """Die Spiele einer konfigurierten h4a-Mannschaft holen.

    Ein Request je Staffel: das Portal kennt keinen Mannschaftsfilter, also holen wir
    die Staffel und behalten die Spiele mit `team_name` auf einer der beiden Seiten.
    """
    matches: list[Match] = []

    for class_id in team.class_ids:
        payload = client.staffel(org_id=team.org_id, class_id=class_id)
        staffeln = [
            s
            for key in ("actualGames", "futureGames")
            for s in [(payload.get("content") or {}).get(key)]
            if isinstance(s, dict)
        ]
        liga = _liganame(staffeln[0]) if staffeln else ""
        link = _portal_link(team.org_id, class_id)

        alle = [g for s in staffeln for g in (s.get("games") or [])]
        eigene = [
            g
            for g in alle
            if team.team_name in ((g.get("gHomeTeam") or ""), (g.get("gGuestTeam") or ""))
        ]
        if not eigene:
            namen = sorted({(g.get("gHomeTeam") or "").strip() for g in alle})
            print(
                f"    [warn] Staffel {class_id} ({liga or '?'}) enthält „{team.team_name}“ "
                f"nicht. Gemeldete Heimmannschaften: {', '.join(namen) or 'keine'}",
                file=sys.stderr,
            )
            continue

        im_fenster = [
            m
            for m in (to_match(g, team, liga=liga, link=link) for g in eigene)
            if m is not None and season_start <= m.start.strftime("%Y-%m-%d") <= season_end
        ]
        draussen = len(eigene) - len(im_fenster)
        hinweis = f", {draussen} außerhalb des Saisonfensters" if draussen else ""
        print(f"    {len(im_fenster)} Spiele | {liga}{hinweis}")
        matches.extend(im_fenster)

    return matches
