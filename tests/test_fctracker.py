"""Test del fornitore FC-Tracker con un pool finto nel formato reale dell'API."""
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///" + str(ROOT / "test_fct.db")
(ROOT / "test_fct.db").unlink(missing_ok=True)

import httpx  # noqa: E402

from app import services  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Card, PriceObservation  # noqa: E402
from app.providers.fctracker import FCTracker  # noqa: E402
from app.providers.futdb import FutDB  # noqa: E402
from app.telegram_bot import handle  # noqa: E402


def ms(dt):
    return int(dt.timestamp() * 1000)


def test_fctracker():
    init_db()
    now = services.utcnow()
    pool = {"p": "console", "bin": {}, "paid": {}, "avg": {
        "1845": [91000, ms(now - timedelta(hours=1))],     # recente -> salvato
        "27": [345205, ms(now - timedelta(days=7))],        # vecchio -> scartato
        "5467": [800, ms(now - timedelta(hours=2))],        # sotto FCT_MIN_PRICE -> ignorato
        "bad": ["x", 1],                                    # malformato -> ignorato
    }}

    def handler(req: httpx.Request):
        assert req.url.path == "/v1/prices" and req.url.params["p"] == "console"
        return httpx.Response(200, json=pool)

    fct = FCTracker(client=httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler)))
    with SessionLocal() as db:
        s = fct.ingest(db)
        assert s == {"carte_nel_pool": 4, "salvati": 1, "scartati_vecchi": 1, "carte_nuove": 1}, s
        card = db.query(Card).filter(Card.external_id == "ea:1845").one()
        assert card.name == "EA 1845"
        assert fct.ingest(db)["salvati"] == 0, "stesso timestamp: niente doppioni"
        pool["avg"]["1845"] = [93000, ms(now)]
        assert fct.ingest(db)["salvati"] == 1
        assert db.query(PriceObservation).filter(PriceObservation.card_id == card.id).count() == 2

        # FUT-DB non deve trattare le carte di FC-Tracker come sue
        from app import config
        config.FUTDB_TOKEN = "x"
        calls = []
        fut = FutDB(client=httpx.Client(base_url="https://x", transport=httpx.MockTransport(
            lambda r: calls.append(r) or httpx.Response(200, json={}))), pause=0)
        fut.fetch_prices(db)
        assert calls == [], "FUT-DB ha chiamato l'API per una carta FC-Tracker"
        config.FUTDB_TOKEN = ""

    # /fonte con FC-Tracker attivo
    from app import config
    config.FCT_ENABLED = True
    with SessionLocal() as db:
        services.set_setting(db, "owner_chat", "42")
        db.commit()
    out = handle("42", "/fonte")
    print(out)
    assert "FC-Tracker attivo" in out
    (ROOT / "test_fct.db").unlink(missing_ok=True)


if __name__ == "__main__":
    test_fctracker(); print("TEST FC-TRACKER OK")
