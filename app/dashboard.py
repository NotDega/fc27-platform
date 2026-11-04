"""Dashboard web (GET /dashboard): la stessa informazione del briefing, in una pagina da telefono."""
from __future__ import annotations

from datetime import datetime
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, events, market, services
from app.models import PriceObservation

CSS = """
:root{--bg:#f4f6f3;--panel:#fff;--ink:#17201b;--muted:#5f6b64;--line:#dde3dd;--coin:#9c6f0c;--gain:#1c7a46;--loss:#b3372d}
@media (prefers-color-scheme:dark){:root{--bg:#101512;--panel:#18201b;--ink:#e6ebe7;--muted:#98a49c;--line:#2a342d;--coin:#e3b341;--gain:#4fc483;--loss:#ef7a6e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,sans-serif}
.wrap{max-width:60rem;margin:0 auto;padding:20px max(16px,env(safe-area-inset-left)) 40px;display:grid;gap:16px}
h1{font-size:1.6rem;margin:0}h1 span{color:var(--coin)}h2{font-size:1rem;text-transform:uppercase;letter-spacing:.05em;margin:0 0 8px;color:var(--muted)}
.sub{color:var(--muted);font-size:13px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:10px}
.tile,.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.k{font-size:12px;color:var(--muted)}.v{font-size:1.4rem;font-variant-numeric:tabular-nums;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:7px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto}.gain{color:var(--gain)}.loss{color:var(--loss)}.empty{color:var(--muted)}
.chip{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
"""


def _fmt(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _label(card) -> str:
    return card.name if not card.rating else f"{card.name} {card.rating}"


def _day(when) -> str:
    local = when.astimezone(events.local_tz())
    return ["lun", "mar", "mer", "gio", "ven", "sab", "dom"][local.weekday()] + local.strftime(" %d/%m %H:%M")


def render(db: Session) -> str:
    now_local = datetime.now(events.local_tz())
    cov = market.coverage(db)
    m = services.metrics(db)
    calls = services.active_calls(db)
    ups, downs = market.movers(db, limit=6)
    up_events = events.upcoming(limit=6)
    sources = db.execute(select(PriceObservation.source, func.count(), func.max(PriceObservation.observed_at))
                         .group_by(PriceObservation.source)).all()
    e = escape
    wr = f"{m['win_rate']:.0%}" if m["win_rate"] is not None else "-"

    tiles = "".join(f'<div class="tile"><div class="k">{e(k)}</div><div class="v">{e(str(v))}</div></div>' for k, v in [
        ("Carte con prezzo < 6h", cov["fresche_6h"]),
        ("Carte con prezzo < 24h", cov["fresche_24h"]),
        ("Call attive", len(calls)),
        ("Netto simulato", _fmt(m["profitto_netto"])),
        ("Win rate simulato", wr),
    ])

    ev_rows = "".join(
        f"<tr><td>{e(_day(ev.when))}<br>"
        f"<span class='sub'>{e(events.countdown(ev.when))}</span></td>"
        f"<td>{e(ev.name)}{'' if ev.confirmed else ' <span class=chip>attesa</span>'}<br>"
        f"<span class='sub'>{e(ev.action)}: {e(ev.note)}</span></td></tr>" for ev in up_events
    ) or "<tr><td class='empty' colspan=2>Nessun evento.</td></tr>"

    call_rows = "".join(
        f"<tr><td>#{c.id} {e(_label(c.card))}<br><span class='sub'>{e(c.reason)}</span></td>"
        f"<td class=n>{_fmt(c.entry_max)}</td><td class=n>{_fmt(c.sell_low)}–{_fmt(c.sell_high)}</td>"
        f"<td class='n gain'>+{c.expected_net_pct:.1%}</td><td>{e(c.risk)}</td></tr>" for c in calls[:20]
    ) or "<tr><td class='empty' colspan=5>Nessuna call attiva: il motore non ha trovato occasioni con margine dopo la tassa.</td></tr>"

    mv_rows = "".join(
        f"<tr><td>{e(_label(x.card))}</td><td class=n>{_fmt(x.first)}</td><td class=n>{_fmt(x.last)}</td>"
        f"<td class='n {'gain' if x.pct > 0 else 'loss'}'>{x.pct:+.0%}</td><td class=n>{x.hours:.0f}h</td></tr>"
        for x in ups + downs
    ) or f"<tr><td class='empty' colspan=5>Nessun movimento di almeno {config.MOVER_MIN_PCT:.0%} su prezzi recenti.</td></tr>"

    src_rows = "".join(
        f"<tr><td>{e(s)}</td><td class=n>{_fmt(n)}</td>"
        f"<td class=n>{e(services.aware(last).astimezone(events.local_tz()).strftime('%d/%m %H:%M')) if last else '-'}</td></tr>"
        for s, n, last in sources
    ) or "<tr><td class='empty' colspan=3>Nessun prezzo ancora.</td></tr>"

    mode = "Simulazione: le call non usano crediti veri." if config.SIM_MODE else "Modalità reale."
    return f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="refresh" content="300"><title>FC 27 Market</title><style>{CSS}</style></head><body><div class="wrap">
<header><h1>FC 27 <span>Market</span></h1>
<div class="sub">Aggiornato {now_local:%d/%m %H:%M} · {e(config.PLATFORM)} · {e(mode)} La pagina si ricarica ogni 5 minuti.</div></header>
<section class="tiles">{tiles}</section>
<section class="card"><h2>Prossimi eventi</h2><table>{ev_rows}</table></section>
<section class="card"><h2>Call attive</h2><div class="scroll"><table>
<tr><th>Carta</th><th>Compra fino a</th><th>Vendi</th><th>Netto</th><th>Rischio</th></tr>{call_rows}</table></div></section>
<section class="card"><h2>Movimenti ultime {config.MOVER_WINDOW_HOURS}h (solo prezzi recenti)</h2><div class="scroll"><table>
<tr><th>Carta</th><th>Da</th><th>A</th><th>Var.</th><th>In</th></tr>{mv_rows}</table></div></section>
<section class="card"><h2>Fonti dati</h2><table><tr><th>Fonte</th><th>Prezzi</th><th>Più recente</th></tr>{src_rows}</table></section>
</div></body></html>"""
