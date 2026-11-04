"""Movimenti di mercato su dati freschi.

Per ogni carta si confrontano due prezzi, ENTRAMBI osservati nelle ultime MOVER_WINDOW_HOURS ore
e distanti almeno MOVER_MIN_GAP_HOURS: così un prezzo vecchio di una settimana non viene mai
scambiato per un "crollo" o un "rialzo".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, services
from app.models import Card, PriceObservation


@dataclass
class Move:
    card: Card
    first: int
    last: int
    pct: float
    hours: float
    n: int


def movers(db: Session, limit: int = 5) -> tuple[list[Move], list[Move]]:
    """Ritorna (rialzi, cali) più forti, ordinati per variazione percentuale."""
    since = services.utcnow() - timedelta(hours=config.MOVER_WINDOW_HOURS)
    rows = db.execute(
        select(PriceObservation.card_id, PriceObservation.price, PriceObservation.observed_at)
        .where(PriceObservation.observed_at >= since)
        .order_by(PriceObservation.card_id, PriceObservation.observed_at)).all()
    series: dict[int, list] = {}
    for card_id, price, at in rows:
        series.setdefault(card_id, []).append((services.aware(at), price))

    moves: list[Move] = []
    for card_id, pts in series.items():
        if len(pts) < 2:
            continue
        (t0, p0), (t1, p1) = pts[0], pts[-1]
        hours = (t1 - t0).total_seconds() / 3600
        if hours < config.MOVER_MIN_GAP_HOURS or p0 <= 0 or p1 < config.MOVER_MIN_PRICE:
            continue
        pct = p1 / p0 - 1
        if abs(pct) < config.MOVER_MIN_PCT:
            continue
        moves.append(Move(db.get(Card, card_id), p0, p1, pct, hours, len(pts)))

    ups = sorted((m for m in moves if m.pct > 0), key=lambda m: -m.pct)[:limit]
    downs = sorted((m for m in moves if m.pct < 0), key=lambda m: m.pct)[:limit]
    return ups, downs


def coverage(db: Session) -> dict:
    """Quante carte hanno dati freschi: misura onesta di quanto vede il motore."""
    now = services.utcnow()
    fresh = lambda h: db.query(PriceObservation.card_id).filter(  # noqa: E731
        PriceObservation.observed_at >= now - timedelta(hours=h)).distinct().count()
    return {"carte_totali": db.query(Card).count(), "fresche_6h": fresh(6), "fresche_24h": fresh(24)}
