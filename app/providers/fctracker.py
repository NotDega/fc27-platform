"""Fornitore di prezzi FC-Tracker (pool condiviso, uso autorizzato dal gestore per questo bot personale).

Risposta dell'API (GET /v1/prices?p=console):
    {"p": "console", "avg": {"<id EA>": [prezzo_medio, timestamp_ms], ...}, "bin": {...}, "paid": {...}}

Cosa fa, ogni FCT_INTERVAL_MIN minuti:
  - scarica il pool del mercato (console o pc);
  - per ogni carta salva il prezzo medio come osservazione, solo se è più recente
    dell'ultima già salvata e non più vecchio di FCT_MAX_AGE_HOURS;
  - le carte nuove vengono create con nome "EA <id>" (il pool non contiene i nomi);
    se una carta con lo stesso id esiste già (es. da un altro fornitore) viene riusata.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, services
from app.models import Card, PriceObservation

log = logging.getLogger("fctracker")
SOURCE = "fctracker"


class FCTracker:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            base_url=config.FCT_BASE_URL,
            headers={"User-Agent": "fc27-platform (bot personale; autorizzato dal gestore)"},
            timeout=30,
        )

    def fetch(self) -> dict:
        market = "pc" if config.PLATFORM == "pc" else "console"
        resp = self.client.get("/v1/prices", params={"p": market})
        resp.raise_for_status()
        return resp.json()

    def ingest(self, db: Session, data: dict | None = None) -> dict:
        """Salva i prezzi nuovi. Ritorna un riepilogo: salvati, scartati perché vecchi, carte nuove."""
        data = data if data is not None else self.fetch()
        pool = data.get("avg") or {}
        cutoff = services.utcnow() - timedelta(hours=config.FCT_MAX_AGE_HOURS)

        ext_ids = [f"ea:{k}" for k in pool]
        cards = {c.external_id: c for c in db.scalars(select(Card).where(Card.external_id.in_(ext_ids)))} if ext_ids else {}
        last_seen = dict(db.execute(
            select(PriceObservation.card_id, PriceObservation.observed_at)
            .where(PriceObservation.source == SOURCE)
            .order_by(PriceObservation.observed_at)).all())  # l'ultima vince

        saved = stale = new_cards = 0
        for ea_id, entry in pool.items():
            try:
                price, ts_ms = int(entry[0]), int(entry[1])
            except (TypeError, ValueError, IndexError):
                continue
            if price <= 0 or price < config.FCT_MIN_PRICE:
                continue
            observed = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            if observed < cutoff:
                stale += 1
                continue
            ext = f"ea:{ea_id}"
            card = cards.get(ext)
            if card is None:
                card = Card(name=f"EA {ea_id}", rating=0, version="?", platform=config.PLATFORM, external_id=ext)
                db.add(card)
                db.flush()
                cards[ext] = card
                new_cards += 1
            prev = services.aware(last_seen.get(card.id))
            if prev and prev >= observed:
                continue
            db.add(PriceObservation(card_id=card.id, price=price, source=SOURCE, observed_at=observed))
            saved += 1
        db.commit()
        summary = {"carte_nel_pool": len(pool), "salvati": saved, "scartati_vecchi": stale, "carte_nuove": new_cards}
        log.info("FC-Tracker: %s", summary)
        return summary
