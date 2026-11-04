"""Fornitore di prezzi FUT-DB (api.futdatabase.com), abbonamento premium.

Cosa fa, in background:
  1. Una volta al giorno costruisce l'"universo": le carte nella fascia di rating scelta
     (POST /api/players/search), fino a FUTDB_MAX_PLAYERS carte.
  2. Ogni FUTDB_INTERVAL_MIN minuti chiede il prezzo di ogni carta
     (GET /api/players/{id}/price) e salva un'osservazione solo se il prezzo è nuovo
     (priceUpdate diverso dall'ultimo salvato). Aggiorna anche il floor EA (minPrice).

Le richieste del giorno vengono contate e non superano mai FUTDB_DAILY_LIMIT
(il piano premium ne consente 20.000 al giorno).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, services
from app.models import Card, PriceObservation

log = logging.getLogger("futdb")
SOURCE = "futdb"


class BudgetExhausted(Exception):
    pass


class FutDB:
    def __init__(self, client: httpx.Client | None = None, pause: float = 0.05):
        self.client = client or httpx.Client(
            base_url=config.FUTDB_BASE_URL,
            headers={"X-AUTH-TOKEN": config.FUTDB_TOKEN, "Accept": "application/json"},
            timeout=20,
        )
        self.pause = pause  # piccola pausa tra le richieste, per non martellare il servizio

    # ---------- contatore richieste ----------

    @staticmethod
    def _counter_key() -> str:
        return "futdb_requests_" + datetime.now(timezone.utc).strftime("%Y%m%d")

    def used_today(self, db: Session) -> int:
        return int(services.get_setting(db, self._counter_key()) or 0)

    def _request(self, db: Session, method: str, url: str, **kw) -> httpx.Response:
        used = self.used_today(db)
        if used >= config.FUTDB_DAILY_LIMIT:
            raise BudgetExhausted(f"limite giornaliero raggiunto ({used})")
        services.set_setting(db, self._counter_key(), str(used + 1))
        resp = self.client.request(method, url, **kw)
        if self.pause:
            time.sleep(self.pause)
        resp.raise_for_status()
        return resp

    # ---------- universo ----------

    def _rarities(self, db: Session) -> dict[int, str]:
        try:
            data = self._request(db, "GET", "/api/rarities").json()
            items = data.get("items", data) if isinstance(data, dict) else data
            return {int(r["id"]): str(r.get("name", "")) for r in items}
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            log.warning("rarità non disponibili: %s", e)
            return {}

    def refresh_universe(self, db: Session) -> int:
        """Aggiunge al database le carte della fascia di rating scelta. Ritorna quante sono seguite."""
        rarities = self._rarities(db)
        body = {"ratingMin": config.FUTDB_RATING_MIN, "ratingMax": config.FUTDB_RATING_MAX}
        tracked = db.query(Card).filter(Card.external_id.isnot(None), ~Card.external_id.like("ea:%")).count()
        page = 1
        while tracked < config.FUTDB_MAX_PLAYERS:
            data = self._request(db, "POST", "/api/players/search", params={"page": page}, json=body).json()
            for p in data.get("items", []):
                if tracked >= config.FUTDB_MAX_PLAYERS:
                    break
                ext = str(p["id"])
                if db.scalar(select(Card.id).where(Card.external_id == ext)):
                    continue
                name = p.get("commonName") or p.get("name") or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
                version = rarities.get(int(p.get("rarity") or 0), "") or "Rare"
                db.add(Card(name=name, rating=int(p["rating"]), version=version[:40],
                            platform=config.PLATFORM, external_id=ext))
                tracked += 1
            db.commit()
            pag = data.get("pagination") or {}
            if page >= int(pag.get("pageTotal") or page):
                break
            page += 1
        log.info("universo FUT-DB: %d carte", tracked)
        return tracked

    # ---------- prezzi ----------

    def fetch_prices(self, db: Session) -> int:
        """Aggiorna i prezzi di tutte le carte seguite. Ritorna quanti prezzi nuovi ha salvato."""
        market = "pc" if config.PLATFORM == "pc" else "playstation"  # console = PlayStation + Xbox
        saved = 0
        cards = db.scalars(select(Card).where(Card.external_id.isnot(None), ~Card.external_id.like("ea:%"))).all()
        for card in cards:
            try:
                data = self._request(db, "GET", f"/api/players/{card.external_id}/price").json()
            except BudgetExhausted as e:
                log.warning("stop prezzi: %s", e)
                break
            except httpx.HTTPError as e:
                log.warning("prezzo %s: %s", card.external_id, e)
                continue
            p = (data or {}).get(market) or {}
            price = p.get("price")
            if not price:
                continue
            if p.get("minPrice"):
                card.floor_price = int(p["minPrice"])
            observed = _parse_time(p.get("priceUpdate")) or services.utcnow()
            last = db.scalar(select(PriceObservation).where(
                PriceObservation.card_id == card.id, PriceObservation.source == SOURCE)
                .order_by(PriceObservation.observed_at.desc()))
            if last and services.aware(last.observed_at) >= observed:
                continue  # prezzo non ancora aggiornato dal fornitore
            db.add(PriceObservation(card_id=card.id, price=int(price), source=SOURCE, observed_at=observed))
            saved += 1
            if saved % 50 == 0:
                db.commit()
        db.commit()
        log.info("FUT-DB: %d prezzi nuovi su %d carte", saved, len(cards))
        return saved


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
