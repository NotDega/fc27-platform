"""Test v0.3: calendario, movimenti su dati freschi, briefing, dashboard, comandi Telegram."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///" + str(ROOT / "test_v03.db")
(ROOT / "test_v03.db").unlink(missing_ok=True)

from app import briefing, dashboard, events, market, services  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.telegram_bot import handle  # noqa: E402


def test_events():
    wed = datetime(2026, 11, 4, 22, 0, tzinfo=ZoneInfo("Europe/London"))  # mercoledì sera
    up = events.upcoming(now=wed, days=7, limit=20)
    names = [e.name for e in up]
    assert names[0] == "Premi Division Rivals", names
    assert "Road to the Knockouts (RTTK) Team 1" in names
    assert events.countdown(wed + timedelta(hours=10), wed) == "tra 10h 0m"
    print(events.format_event(up[0], wed))


def test_movers_and_briefing():
    init_db()
    now = services.utcnow()
    with SessionLocal() as db:
        # Rice: rialzo vero, entrambi i prezzi recenti
        services.record_price(db, "Declan Rice", 88, 12000, "test", observed_at=now - timedelta(hours=6))
        services.record_price(db, "Declan Rice", 88, 13500, "test", observed_at=now - timedelta(hours=1))
        # Kane: prezzo vecchio di 7 giorni + nuovo -> NON deve risultare un movimento
        services.record_price(db, "Harry Kane", 90, 50000, "test", observed_at=now - timedelta(days=7))
        services.record_price(db, "Harry Kane", 90, 36000, "test", observed_at=now - timedelta(hours=1))
        # Saka: calo vero
        services.record_price(db, "Saka", 87, 8000, "test", observed_at=now - timedelta(hours=5))
        services.record_price(db, "Saka", 87, 7000, "test", observed_at=now)
        db.commit()
        ups, downs = market.movers(db)
        assert [m.card.name for m in ups] == ["Declan Rice"], ups
        assert [m.card.name for m in downs] == ["Saka"], downs
        cov = market.coverage(db)
        assert cov["fresche_6h"] == 3 and cov["carte_totali"] == 3

        text = briefing.build(db)
        print("\n" + text)
        assert "PROSSIMI EVENTI" in text and "Declan Rice" in text and "Harry Kane" not in text.split("MOVIMENTI")[1].split("DATI")[0]

        html = dashboard.render(db)
        assert html.startswith("<!doctype html>") and "Declan Rice" in html and "<script" not in html

        services.set_setting(db, "owner_chat", "7")
        db.commit()
    for cmd in ("/briefing", "/eventi", "/movimenti", "/aiuto"):
        out = handle("7", cmd)
        assert out and "non riconosciuto" not in out, (cmd, out)
    assert "▲ Declan Rice 88" in handle("7", "/movimenti")
    (ROOT / "test_v03.db").unlink(missing_ok=True)


if __name__ == "__main__":
    test_events(); test_movers_and_briefing(); print("\nTEST v0.3 OK")
