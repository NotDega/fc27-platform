"""Briefing: un riepilogo leggibile di cosa sta succedendo e cosa fare."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app import config, events, market, services


def _fmt(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _label(card) -> str:
    return card.name if not card.rating else f"{card.name} {card.rating}"


def build(db: Session) -> str:
    now_local = datetime.now(events.local_tz())
    lines = [f"BRIEFING FC 27 - {now_local:%d/%m %H:%M}"]
    if config.SIM_MODE:
        lines.append("(simulazione: le call non usano crediti veri)")

    # 1. Eventi
    lines.append("\nPROSSIMI EVENTI")
    up = events.upcoming(limit=4)
    lines += [events.format_event(e) for e in up] or ["Nessun evento nei prossimi giorni."]

    # 2. Call attive
    calls = services.active_calls(db)
    lines.append(f"\nCALL ATTIVE ({len(calls)})")
    for c in calls[:3]:
        lines.append(f"#{c.id} {_label(c.card)}: compra fino a {_fmt(c.entry_max)}, "
                     f"vendi {_fmt(c.sell_low)}-{_fmt(c.sell_high)} (+{c.expected_net_pct:.0%}, rischio {c.risk})")
    if not calls:
        lines.append("Nessuna: il motore non ha trovato occasioni con margine dopo la tassa.")

    # 3. Movimenti su dati freschi
    ups, downs = market.movers(db, limit=3)
    lines.append(f"\nMOVIMENTI ULTIME {config.MOVER_WINDOW_HOURS}H (solo prezzi recenti)")
    for m in ups:
        lines.append(f"▲ {_label(m.card)}: {_fmt(m.first)} → {_fmt(m.last)} ({m.pct:+.0%} in {m.hours:.0f}h)")
    for m in downs:
        lines.append(f"▼ {_label(m.card)}: {_fmt(m.first)} → {_fmt(m.last)} ({m.pct:+.0%} in {m.hours:.0f}h)")
    if not ups and not downs:
        lines.append("Nessun movimento forte su dati recenti.")

    # 4. Dati e simulazione
    cov = market.coverage(db)
    m = services.metrics(db)
    lines.append("\nDATI")
    lines.append(f"Carte con prezzo nelle ultime 6h: {cov['fresche_6h']} - nelle ultime 24h: {cov['fresche_24h']} "
                 f"(su {cov['carte_totali']})")
    wr = f"{m['win_rate']:.0%}" if m["win_rate"] is not None else "-"
    lines.append(f"Simulazione: {m['trades_chiusi']} operazioni chiuse, netto {_fmt(m['profitto_netto'])}, win rate {wr}")
    return "\n".join(lines)


def events_text() -> str:
    up = events.upcoming(days=7, limit=10)
    return "PROSSIMI EVENTI\n" + ("\n".join(events.format_event(e) for e in up) or "Nessun evento.")
