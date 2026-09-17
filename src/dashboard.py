"""Rendert ein self-contained docs/index.html (kein externes Asset, kein Skript).

Die Seite ist die Anlaufstelle fürs Abonnieren: oben die Liste der Feeds mit ihren
Dateinamen, darunter je Mannschaft die Spiele.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from src.config import Config
from src.models import Match

_WOCHENTAG = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _wann(m: Match) -> str:
    tag = f"{_WOCHENTAG[m.start.weekday()]} {m.start.strftime('%d.%m.%Y')}"
    return tag if m.all_day else f"{tag} · {m.start.strftime('%H:%M')}"


def _row(m: Match) -> str:
    ort = f" · {html.escape(m.venue)}" if m.venue else ""
    badges = []
    if m.all_day:
        badges.append('<span class="badge">Zeit offen</span>')
    if m.result:
        badges.append(f'<span class="badge res">{html.escape(m.result)}</span>')
    if m.status and m.status not in ("Angesetzt", "Beendet"):
        badges.append(f'<span class="badge">{html.escape(m.status)}</span>')
    heim = "H" if m.is_home else "A"
    return (
        '<li class="ev">'
        f'<span class="when">{html.escape(_wann(m))}</span>'
        f'<span class="ha">{heim}</span>'
        f'<span class="title"><a href="{html.escape(m.url)}">'
        f"{html.escape(m.home)} – {html.escape(m.away)}</a>{ort}</span>"
        f'{"".join(badges)}'
        "</li>"
    )


def _feed_zeile(slug: str, name: str, anzahl: int) -> str:
    return (
        '<li class="feed">'
        f'<code>{html.escape(slug)}.ics</code>'
        f'<span class="fname">{html.escape(name)}</span>'
        f'<span class="count">{anzahl} Spiele</span>'
        "</li>"
    )


def render_dashboard(
    je_team: dict[str, list[Match]],
    *,
    cfg: Config,
    feeds: list[tuple[str, str, int]],
    out: Path,
    gebaut_am: datetime | None = None,
) -> None:
    abschnitte = []
    for team in cfg.teams:
        spiele = sorted(je_team.get(team.feed_slug, []), key=lambda x: x.start)
        if not spiele:
            continue
        ligen = sorted({s.league for s in spiele if s.league})
        untertitel = " · ".join(ligen)
        rows = "\n".join(_row(s) for s in spiele)
        abschnitte.append(
            f'<h2>{html.escape(team.display)} <span class="count">{len(spiele)}</span></h2>'
            f'<div class="liga">{html.escape(untertitel)} · '
            f'<code>{html.escape(team.feed_slug)}.ics</code></div>'
            f"<ul>{rows}</ul>"
        )
    body = "\n".join(abschnitte) or '<p class="empty">Keine Spiele gefunden.</p>'

    gesamt = sum(len(v) for v in je_team.values())
    stand = f" · Stand {gebaut_am.strftime('%d.%m.%Y %H:%M')}" if gebaut_am else ""
    # Die Quelle je Mannschaft steht in teams.json – im Untertitel nennen wir, was
    # tatsächlich benutzt wurde, statt pauschal handball.net.
    quellen = " und ".join(
        sorted({"handball4all" if t.ist_h4a else "handball.net" for t in cfg.teams})
    )
    feed_liste = "\n".join(_feed_zeile(*f) for f in feeds)

    page = f"""<title>{html.escape(cfg.calendar_name)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         max-width: 820px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
  h1 {{ font-size: 1.4rem; margin-bottom: .25rem; }}
  h2 {{ font-size: 1.05rem; margin: 1.8rem 0 .1rem; }}
  a {{ color: inherit; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  code {{ font-size: .85em; }}
  .count {{ color: #6b7280; font-weight: 400; font-size: .85rem; }}
  .liga {{ color: #6b7280; font-size: .8rem; margin-bottom: .4rem; }}
  .sub {{ color: #6b7280; font-size: .9rem; margin-bottom: 1rem; }}
  .abo {{ background: #f3f4f6; border-radius: 10px; padding: .75rem 1rem; margin: 1rem 0 1.5rem;
          font-size: .85rem; }}
  .abo p {{ margin: 0 0 .5rem; }}
  .abo ul {{ margin: 0; }}
  .feed {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem;
           padding: .2rem 0; }}
  .feed code {{ min-width: 12rem; }}
  .fname {{ flex: 1; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  .ev {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem;
         padding: .5rem .2rem; border-bottom: 1px solid #e5e7eb; }}
  .when {{ font-variant-numeric: tabular-nums; font-weight: 600; min-width: 11.5rem; }}
  .ha {{ font-size: .7rem; color: #6b7280; border: 1px solid #d1d5db; border-radius: 4px;
         padding: 0 .25rem; }}
  .title {{ flex: 1; min-width: 14rem; }}
  .badge {{ font-size: .7rem; background: #fde68a; color: #78350f; border-radius: 6px;
            padding: .05rem .4rem; }}
  .badge.res {{ background: #bbf7d0; color: #14532d; }}
  .empty {{ color: #6b7280; }}
  @media (prefers-color-scheme: dark) {{
    .abo {{ background: #1f2937; }} .ev {{ border-color: #374151; }}
    .badge {{ background: #78350f; color: #fde68a; }}
    .badge.res {{ background: #14532d; color: #bbf7d0; }}
  }}
</style>
<h1>{html.escape(cfg.calendar_name)}</h1>
<div class="sub">Spielpläne von {html.escape(quellen)} · {gesamt} Spiele{html.escape(stand)}</div>
<div class="abo">
  <p>📅 Abo-URL ist diese Seite plus der Dateiname – einzeln abonnierbar:</p>
  <ul>
{feed_liste}
  </ul>
</div>
{body}
"""
    out.write_text(page, encoding="utf-8")
