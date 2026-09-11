# handballnet-kalender · Mannschafts-Spielpläne als Kalender-Abo

Baut aus den Spielplänen von **handball.net** Kalender-Abos (ICS) für **frei wählbare
Mannschaften** – je Mannschaft einen Feed, dazu beliebige Zusammenstellungen. Mit Halle
und Adresse im Termin, Gegner und Staffel im Titel, Ergebnis nach dem Spiel. Ein
GitHub-Actions-Job baut die Feeds regelmäßig neu und veröffentlicht sie über GitHub Pages.

## Warum überhaupt

handball.net kann seit dem Relaunch **keinen Mannschafts-Spielplan mehr abonnieren**.
Die Kalender-Funktion der Seite kennt nur zwei Fälle: eine **ganze Liga** oder ein
**einzelnes Spiel**. Auf der Team- und der Spielplan-Seite gibt es keinen Kalender-Knopf,
und die alte Ankündigung des Kalender-Exports ist heute eine 404-Seite.

Auf dem Backend liegt zwar ein nirgends verlinkter Team-Feed
(`json/equipo_google_calendar.php?id_equipo=…`), der ist als Abo aber unbrauchbar:

- **Die UIDs wechseln bei jedem Abruf** → jede Aktualisierung legt neue Termine an,
  statt bestehende zu ändern.
- **Die Zeiten liegen 1–2 Stunden daneben**: Ortszeit wird als UTC ausgegeben
  (`DTSTART:20260912T170000Z` für einen Anwurf um 17:00).
- `LOCATION` ist leer, `DESCRIPTION` enthält `Pendiente`, `X-WR-TIMEZONE` ist
  `Europe/Madrid`.

Dieses Tool nutzt stattdessen die JSON-API der Seite und schreibt den ICS selbst –
mit stabilen UIDs, korrekter Zeitzone und der Halle im Termin.

## Datenquelle

`https://www.handball.net/api/new/…` – die API, mit der die Website selbst arbeitet
(Proxy auf das iSquad-Backend). **Kein Login, kein Token.** Genutzt werden:

| Endpunkt | Zweck |
|---|---|
| `GET /matches?team_id=…&date_from=…&date_to=…` | Spiele einer Mannschaft |
| `GET /matches?club_id=…` | alle Mannschaften eines Vereins (für die Discovery) |
| `GET /teams/clubs` | Vereinsverzeichnis (~4400 Einträge, paginiert) |

`per_page` ist auf 100 begrenzt, der Client paginiert selbst. robots.txt erlaubt
`User-agent: *`; gesperrt sind dort nur KI-Trainings-Crawler. Der Client tritt mit
eigenem User-Agent auf, pausiert zwischen Requests und läuft alle sechs Stunden.

## Lokal einrichten

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Saisonfenster, Kalendername, Zeitzone
```

## Mannschaften wählen

Mannschaften stehen in **`teams.json`** und lassen sich jederzeit hinzufügen oder
entfernen – von Hand oder über `tools.teams`.

```bash
# 1) Verein suchen (lädt das Vereinsverzeichnis einmalig nach .cache/)
python -m tools.discover Villigst

# 2) Mannschaften des Vereins mit team_id und Staffel-IDs auflisten
python -m tools.discover --club 4868

# 3) hinzufügen / anzeigen / entfernen
python -m tools.teams add --team 86629 --phase 12647 --label "1. Herren"
python -m tools.teams list
python -m tools.teams remove 2            # Nummer aus `list`
```

`add` prüft die Angabe vor dem Speichern gegen die API und zeigt, wie viele Spiele in
welchen Staffeln gefunden wurden.

### Warum es die Staffel-ID braucht

handball.net führt unter **einer** `team_id` mitunter **zwei tatsächliche Mannschaften**
eines Vereins. Beispiel HVE Villigst-Ergste, Stand August 2026: `team_id 86629` hatte
26 Spiele in der HVW Männer Oberliga Staffel 2 **und** 22 in der KÜS Bezirksliga Mitte –
am selben Wochenende, teils zur selben Zeit. Zwei Teams unter einem Datensatz. Erst
`--phase` trennt sie:

```json
{
  "teams": [
    { "label": "1. Herren", "team_id": 86629, "phase_ids": [12647] },
    { "label": "2. Herren", "team_id": 86629, "phase_ids": [14340] }
  ]
}
```

Gehören mehrere Staffeln **zusammen** (Liga plus Freundschaftsspiele derselben
Mannschaft), kommen sie in einen Eintrag: `--phase 12647 --phase 15539`.
Ohne Staffel-Angabe landet alles im Kalender, was die API unter der `team_id` führt.

### Wenn eine Mannschaft plötzlich keine Spiele mehr liefert

**IDs bei handball.net sind nicht für die Ewigkeit.** Im September 2026 hat der Verband
die Doppelbelegung oben aufgelöst: Die Zweite bekam eine **eigene `team_id` (97297)**,
während die Staffel-ID unverändert blieb. Unser Filter suchte damit unter der alten
`team_id` nach einer Staffel, die dort nicht mehr vorkam – Ergebnis: null Spiele.

Zwei Dinge fangen das inzwischen ab:

- Der Lauf **meldet jede konfigurierte Mannschaft ohne Spiele** in `probleme.txt`, und
  der Actions-Job wird dadurch **rot** – nach dem Deploy, damit die übrigen Feeds
  trotzdem aktuell veröffentlicht werden.
- Aussortierte Spiele werden im Log **mit Staffelnamen und ID** genannt, nicht nur
  gezählt. Wandert eine Mannschaft in eine andere Staffel, steht die neue ID direkt da.

Zum Nachsehen: `python -m tools.discover --club <club_id>` listet alle Mannschaften des
Vereins mit aktueller `team_id` und Staffel.

Nebenbei hat handball.net dabei auch die **Vereins-IDs von Zahlen auf Zeichenketten**
umgestellt (`4868` → `"1t9yc3c"`). Der Filter `?club_id=` nimmt weiterhin die Zahl, in
den Daten steht aber die neue Kennung; `tools/discover.py` prüft deshalb beide.

## Ein Feed je Mannschaft – plus Sammel-Feeds

**Jede Mannschaft bekommt automatisch ihren eigenen Feed** (`docs/<slug>.ics`). Wer nur
eine davon im Kalender will, abonniert nur die eine; wer eine loswerden will, bestellt
sie ab. Das ist der flexible Weg – dafür braucht es keine zweite Konfiguration.

Zusätzlich lassen sich unter `feeds` benannte Zusammenstellungen definieren, wenn man
mehrere Mannschaften mit **einer** URL weitergeben möchte:

```json
{
  "teams": [
    { "label": "HVE 1. Herren", "team_id": 86629, "slug": "hve-1-herren", "phase_ids": [12647] },
    { "label": "HVE 2. Herren", "team_id": 86629, "slug": "hve-2-herren", "phase_ids": [14340] },
    { "label": "PSV Recklinghausen Damen", "team_id": 87292, "slug": "psv-damen", "phase_ids": [14058] }
  ],
  "feeds": [
    { "label": "Alle Mannschaften", "slug": "alle" },
    { "label": "Ohne HVE 1. Herren", "slug": "ohne-hve-1-herren",
      "teams": ["hve-2-herren", "psv-damen"] }
  ]
}
```

Ein Feed ohne `teams` umfasst alle Mannschaften. Fehlt die `feeds`-Liste ganz, entsteht
automatisch ein Feed `alle.ics`. Tippfehler in `teams` melden sich beim Lauf, statt still
einen leeren Kalender zu bauen. `slug` ist optional – ohne Angabe wird er aus dem Label
abgeleitet.

## Feed bauen

```bash
python -m src.main
# -> je Mannschaft eine docs/<slug>.ics, dazu die Sammel-Feeds und docs/index.html
```

Der Lauf braucht einen Request pro Mannschaft (plus Pagination) und ist in Sekunden
durch. `DTSTAMP` und `LAST-MODIFIED` tragen den Zeitpunkt des Laufs – daran erkennen
Kalender-Clients, dass eine Fassung neuer ist als die gespeicherte. Die Dateien in
`docs/` ändern sich deshalb bei jedem Lauf, auch wenn sich an den Spielen nichts getan
hat.

## Automatisch veröffentlichen

1. Repo zu GitHub pushen.
2. **Settings → Pages → Source: GitHub Actions**.
3. Workflow „Build & publish handball.net ICS" einmal manuell starten.
4. Abo-URLs: `https://<user>.github.io/<repo>/<slug>.ics`
   Übersicht mit allen Feeds: `https://<user>.github.io/<repo>/`

Secrets braucht der Job keine – die Daten sind öffentlich. Optionale **Variables**:
`SEASON_START`, `SEASON_END`, `TIMEZONE`, `CALENDAR_NAME`, `MATCH_DURATION_MIN`.
Ein Push auf `main` (z.B. geändertes `teams.json`) baut die Feeds sofort neu, ansonsten
läuft der Job alle sechs Stunden.

## Kalender abonnieren

- **Apple Kalender:** Ablage → Neues Kalenderabonnement → Abo-URL einfügen. Läuft.
- **Google Kalender:** Andere Kalender → Per URL → Abo-URL einfügen, oder direkt über
  `https://calendar.google.com/calendar/u/0/r/settings/addbyurl` (die `u/0` nagelt das
  Konto fest; bei mehreren angemeldeten Konten laufen die `cid`-Links sonst ins Leere).
  Aus der Handy-App geht es nicht, nur im Browser. Google aktualisiert Abos ohnehin nur
  alle paar Stunden. **Achtung:** siehe den Abschnitt weiter unten – hier klemmt es
  derzeit.

## Was im Termin steht

```
SUMMARY:     A · HSG Gevelsberg Silschede – HVE 1. Herren
LOCATION:    SPH Gevelsberg-West, Am Hofe 10, 58285 Gevelsberg
DESCRIPTION: HVW Männer Oberliga Staffel 2
             Auswärtsspiel · Spieltag 2
             Schiedsrichter: Serkan Kahraman, Markus Schürhoff
             https://www.handball.net/match/368939
DTSTART;TZID=Europe/Berlin:20260912T193000     (Dauer 2 h, einstellbar)
UID:         match-368939@handball.net          (stabil -> Verlegung = Update)
```

Der Titel beginnt mit **`H`** oder **`A`**: Heim oder Auswärts steht damit an der
einzigen Stelle, die Kalender-Apps nie abschneiden. Danach die Paarung in der gewohnten
Reihenfolge, **Heimmannschaft links**.

Die eigene Seite trägt dabei das **konfigurierte Label** statt des Namens aus der API.
Das ist nicht Kosmetik: handball.net führt die Erste und die Zweite des HVE unter
demselben Namen („HVE VILLIGST-ERGSTE II"). Erst das Label sagt, welche der beiden
spielt – im Sammel-Feed wären die Termine sonst nicht auseinanderzuhalten.

Ist das Spiel gespielt, hängt das Ergebnis hinten an: `H · HVE 1. Herren – Ahlener SG
93 e.V. II · 28:24`.

Ist das Spiel gespielt, steht das Ergebnis hinten im Titel. Abgesetzte Spiele bekommen
`STATUS:CANCELLED`, Kalender-Apps streichen sie durch.

## Form des Kalenders

Drei Entscheidungen, die sich aus RFC 5545 ergeben und nicht aus dem Geschmack:

- **`VTIMEZONE` wird mitgeliefert.** Wer per `TZID` auf eine Zeitzone verweist, muss sie
  im Kalender definieren. Geschrieben wird die kanonische `RRULE`-Form mit der EU-Regel
  (letzter Sonntag im März bzw. Oktober). `Timezone.from_tzid` der `icalendar`-Bibliothek
  erzeugt stattdessen `RDATE`-Listen, einen `COMMENT` und einen Block mit identischen
  Offsets – formal zulässig, aber unnötig sperrig.
- **Kein `METHOD`.** `METHOD:PUBLISH` macht aus der Datei eine iTIP-Nachricht; ein
  abonnierbarer Kalender braucht das nicht.
- **`DTSTAMP` und `LAST-MODIFIED` tragen den Zeitpunkt des Laufs**, nicht den Anwurf.
  Daran erkennen Clients eine neuere Fassung. Stünde dort die Anwurfzeit, bliebe der
  Wert bei einem reinen Hallenwechsel unverändert und die Änderung käme nicht an.

## Google Calendar nimmt den Feed nicht an (Stand 24.08.2026)

Apple Kalender abonniert die Feeds anstandslos. Google meldet „Hoppla, dieser Kalender
konnte nicht hinzugefügt werden. Bitte versuchen Sie es in ein paar Minuten noch
einmal." **Die Ursache liegt bei Google, nicht am Feed und nicht am Hosting.**

### Der Beweis

Ein Endpunkt, der jeden eingehenden Request protokolliert (webhook.site), wurde als
Kalender-URL in Google eingetragen. **Es kam nie ein Request an** – auch nach Minuten
nicht. Googles Abholdienst versucht es also gar nicht erst; die Anfrage verlässt Google
nie. Damit ist alles, was ein Server ausliefern könnte, ohne Bedeutung.

Dazu passt die von Google selbst angepinnte Meldung im Calendar-Forum vom 3.10.2025,
gekennzeichnet als **Known Issue**: „adding a calendar from a URL appears to be not
working as intended". 655 Nutzer haben sich angeschlossen, der Thread ist gesperrt, ein
Fix wurde nie vermeldet, Meldungen laufen 2026 weiter.

Eine Nebenspur, die unterwegs auftauchte und **nicht** die Ursache war: Nach vielen
Versuchen meldete Google „Sie haben die Obergrenze für die Anzahl neuer Kalender
erreicht" – ein Abo über URL legt einen neuen Kalender an, und dieses Kontingent war
aufgebraucht. Nachdem es sich zurückgesetzt hatte, ließ sich wieder ein Kalender
anlegen, **das Abo über URL aber weiterhin nicht**. Wer also auf diese Meldung stößt:
sie erklärt das Scheitern nicht, sie kommt nur oben drauf.

### Was trotzdem funktioniert – und was das verrät

| Feed | Kannte Google die URL schon? | Ergebnis |
|---|---|---|
| Googles eigene Feiertage | ja, eigener Dienst | klappt |
| officeholidays Deutschland | ja, millionenfach abonniert | klappt |
| eigener SpielerPlus-Feed, im Juni abonniert | ja, seit Juni im System | klappt |
| handball360-Liga-Feed, frisch | nein | scheitert |
| sämtliche Feeds dieses Projekts | nein | scheitert |

Alles, was Google bereits kennt, lässt sich hinzufügen. Alles, was einen frischen Abruf
erfordert, scheitert – ohne dass der Abruf je stattfindet.

### Was vergeblich probiert wurde

Damit niemand denselben Weg noch einmal geht: reines ASCII; reduzierte Feldmenge; ohne
`VTIMEZONE`; Zeiten in UTC statt `TZID`; ein einziger Termin in elf handgeschriebenen
Zeilen; ein Hex-Dateiname; ein Unterordner; ein umbenanntes Repo (kompletter neuer
Pfad); `#1` an die URL gehängt (der Cache-Trick aus dem Google-Forum). Jeder Versuch
scheiterte gleich.

Geprüft und unauffällig: HTTP 200 ohne Weiterleitung, `Content-Type: text/calendar`,
Abruf mit der Kennung `Google-Calendar-Importer` erfolgreich, keine robots.txt, längste
Zeile 75 Oktetts, gültiges UTF-8, Abschluss mit CRLF, keine leeren Werte, keine
Steuerzeichen, eindeutige UIDs, korrekt maskierte Kommas.

### Empfehlung

In Apple abonnieren – das läuft. Für Google bleibt der einmalige Import
(Einstellungen → Importieren), dann allerdings ohne Aktualisierung. Und gelegentlich
erneut versuchen: repariert Google die Funktion, geht es ohne Zutun.

## Projektstruktur

| Datei | Zweck |
|---|---|
| `src/client.py` | HTTP-Client: Pagination, Retry, Pause zwischen Requests |
| `src/parser.py` | Spiel-JSON → `Match` (Zeitzone, ganztägig, Dedupe, Schreibweise) |
| `src/models.py` | `TeamRef` (Mannschaft), `FeedSpec` (Sammel-Feed) und `Match` |
| `src/ics.py` | `Match`-Liste → eine VCALENDAR |
| `src/dashboard.py` | statisches `docs/index.html` mit allen Feeds, nach Mannschaft gruppiert |
| `src/config.py` | `.env` + `teams.json` laden und schreiben |
| `src/main.py` | Orchestrierung |
| `tools/discover.py` | Vereine suchen, Mannschaften mit Staffel-IDs auflisten |
| `tools/teams.py` | `add` / `list` / `remove` für `teams.json` |
| `.github/workflows/build-ics.yml` | Cron-Job + Pages-Deploy |

## Verwandt

`~/Documents/Projects/spieler+` macht dasselbe für **SpielerPlus** (Trainings und
Termine, gefiltert auf die eigene Zusage). Bewusst getrennte Feeds: getrennt
abbestellbar, eigene Kalenderfarbe, und ein Fehler in der einen Quelle legt die andere
nicht lahm. Achtung: SpielerPlus führt Spiele oft ebenfalls als Termin – wer beide
Kalender abonniert, sieht Spiele zweimal.
