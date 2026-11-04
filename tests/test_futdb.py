"""Test del fornitore FUT-DB con risposte finte (nessuna chiamata reale)."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///" + str(ROOT / "test_futdb.db")
(ROOT / "test_futdb.db").unlink(missing_ok=True)

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Card, PriceObservation  # noqa: E402
from app.providers.futdb import FutDB  # noqa: E402

PLAYERS = [
    {"id": 101, "commonName": "Rice", "rating": 88, "rarity": 1},
    {"id": 102, "name": "Virgil van Dijk", "rating": 88, "rarity": 1},
    {"id": 103, "commonName": "Kane", "rating": 90, "rarity": 2},
]
calls = {"n": 0}


def handler(request: httpx.Request) -> httpx.Response:
    calls["n"] += 1
    assert request.headers["X-AUTH-TOKEN"] == "test"
    path = request.url.path
    if path == "/api/rarities":
        return httpx.Response(200, json={"items": [{"id": 1, "name": "Rare"}, {"id": 2, "name": "Team of the Week"}]})
    if path == "/api/players/search":
        body = json.loads(request.content)
        assert body == {"ratingMin": 84, "ratingMax": 90}
        return httpx.Response(200, json={"pagination": {"pageCurrent": 1, "pageTotal": 1}, "items": PLAYERS})
    if path.endswith("/price"):
        pid = int(path.split("/")[3])
        price = {101: 13000, 102: 13250, 103: 36000}[pid]
        return httpx.Response(200, json={
            "playstation": {"price": price, "minPrice": 8300, "maxPrice": 150000, "priceUpdate": "2026-11-04T20:00:00Z"},
            "pc": {"price": price + 500, "minPrice": 8300, "priceUpdate": "2026-11-04T20:00:00Z"}})
    return httpx.Response(404)


def test_futdb():
    config.FUTDB_TOKEN = "test"
    init_db()
    client = httpx.Client(base_url="https://api.test", headers={"X-AUTH-TOKEN": "test"},
                          transport=httpx.MockTransport(handler))
    fut = FutDB(client=client, pause=0)
    with SessionLocal() as db:
        assert fut.refresh_universe(db) == 3
        kane = db.query(Card).filter(Card.external_id == "103").one()
        assert kane.version == "Team of the Week" and kane.rating == 90

        assert fut.fetch_prices(db) == 3
        assert fut.fetch_prices(db) == 0, "stesso priceUpdate: niente doppioni"
        rice = db.query(Card).filter(Card.external_id == "101").one()
        obs = db.query(PriceObservation).filter(PriceObservation.card_id == rice.id).one()
        assert obs.price == 13000 and obs.source == "futdb"   # prezzo PlayStation, non PC
        assert rice.floor_price == 8300
        assert fut.used_today(db) == calls["n"]
        print("richieste usate:", fut.used_today(db))

        # limite giornaliero rispettato
        config.FUTDB_DAILY_LIMIT = fut.used_today(db)
        assert fut.fetch_prices(db) == 0
    (ROOT / "test_futdb.db").unlink(missing_ok=True)


if __name__ == "__main__":
    test_futdb(); print("TEST FUT-DB OK")
