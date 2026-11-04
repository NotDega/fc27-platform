"""Test del flusso completo con prezzi finti: osservazioni -> call -> acquisto simulato -> vendita."""
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///" + str(ROOT / "test.db")
(ROOT / "test.db").unlink(missing_ok=True)

from app import services  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.engine import rules  # noqa: E402
from app.telegram_bot import _parse_price, format_call  # noqa: E402


def test_math():
    assert rules.floor_to_step(13_180) == 13_000
    assert rules.floor_to_step(9_950) == 9_900
    assert round(rules.net_after_tax(10_000, 12_000)) == 1_400
    assert rules.evaluate([13_000] * 3 + [11_000]) is None  # troppe poche osservazioni


def test_parse():
    assert _parse_price("Declan Rice 88 13000") == ("Declan Rice", 88, 13000, "Rare")
    assert _parse_price("Rice 88 13.250 TOTW") == ("Rice", 88, 13250, "TOTW")
    assert _parse_price("Rice 13000") is None


def test_flow():
    init_db()
    t0 = services.utcnow() - timedelta(hours=10)
    with SessionLocal() as db:
        for i, p in enumerate([13_000, 13_250, 12_750, 13_000, 13_250, 13_000]):
            services.record_price(db, "Declan Rice", 88, p, "test", observed_at=t0 + timedelta(hours=i))
        # crollo: anomalia
        services.record_price(db, "Declan Rice", 88, 10_500, "test", observed_at=t0 + timedelta(hours=7))
        db.commit()

        calls = services.generate_calls(db)
        db.commit()
        assert len(calls) == 1, "deve nascere una call"
        call = calls[0]
        print("\n" + format_call(call))
        assert call.entry_max >= 10_500
        assert services.generate_calls(db) == [], "niente doppioni sulla stessa carta"

        # simulazione: il prezzo resta basso dopo il ritardo, poi risale
        trade = db.query(services.SimTrade).one()
        trade.buy_after = services.utcnow() - timedelta(minutes=5)
        services.record_price(db, "Declan Rice", 88, 10_400, "test", observed_at=services.utcnow() - timedelta(minutes=2))
        services.run_simulation(db)
        assert trade.status == "holding", trade.status
        services.record_price(db, "Declan Rice", 88, 13_000, "test", observed_at=services.utcnow())
        services.run_simulation(db)
        assert trade.status == "sold", trade.status
        db.commit()
        m = services.metrics(db)
        print(m)
        assert m["profitto_netto"] > 0 and m["win_rate"] == 1.0


if __name__ == "__main__":
    test_math(); test_parse(); test_flow(); print("\nTUTTI I TEST OK")
