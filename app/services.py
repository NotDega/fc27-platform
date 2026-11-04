"""Logica dell'applicazione: salvare prezzi, generare e annullare call, simulare operazioni."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.engine import rules
from app.models import Call, CallEvent, Card, PriceObservation, Setting, SimTrade

TERMINAL = {"invalidated", "expired"}


def it(n) -> str:
    """Numero all'italiana: 13.000"""
    return f"{int(n):,}".replace(",", ".")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite restituisce date senza fuso orario: le consideriamo UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------- Carte e prezzi ----------

def get_or_create_card(db: Session, name: str, rating: int, version: str = "Rare") -> Card:
    name = name.strip()
    card = db.scalar(select(Card).where(
        Card.name.ilike(name), Card.rating == rating, Card.version.ilike(version), Card.platform == config.PLATFORM))
    if card is None:
        card = Card(name=name, rating=rating, version=version, platform=config.PLATFORM)
        db.add(card)
        db.flush()
    return card


def record_price(db: Session, name: str, rating: int, price: int, source: str,
                 version: str = "Rare", observed_at: datetime | None = None) -> PriceObservation:
    card = get_or_create_card(db, name, rating, version)
    obs = PriceObservation(card_id=card.id, price=int(price), source=source, observed_at=observed_at or utcnow())
    db.add(obs)
    db.flush()
    return obs


def window_prices(db: Session, card_id: int, since: datetime) -> list[PriceObservation]:
    return list(db.scalars(select(PriceObservation)
                           .where(PriceObservation.card_id == card_id, PriceObservation.observed_at >= since)
                           .order_by(PriceObservation.observed_at)))


# ---------- Call ----------

def call_status(db: Session, call: Call) -> str:
    last = db.scalar(select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.id.desc()))
    return last.kind if last else "created"


def active_calls(db: Session) -> list[Call]:
    calls = db.scalars(select(Call).order_by(Call.created_at.desc())).all()
    return [c for c in calls if call_status(db, c) not in TERMINAL]


def generate_calls(db: Session) -> list[Call]:
    """Valuta ogni carta e crea una call dove il motore trova un'occasione."""
    created = []
    since = rules.window_start()
    busy = {c.card_id for c in active_calls(db)}
    for card in db.scalars(select(Card)).all():
        if card.id in busy:
            continue
        obs = window_prices(db, card.id, since)
        sig = rules.evaluate([o.price for o in obs], card.floor_price)
        if sig is None:
            continue
        sources = sorted({o.source for o in obs})
        call = Call(
            card_id=card.id, strategy="anomalia_prezzo", platform=card.platform,
            entry_max=sig.entry_max, sell_low=sig.sell_low, sell_high=sig.sell_high,
            horizon_hours=config.CALL_HORIZON_HOURS, expected_net_pct=sig.expected_net_pct,
            risk=sig.risk, exposure_pct=sig.exposure_pct, reference_price=sig.reference,
            moved_pct=sig.moved_pct, news_status="nessuna notizia (solo dati di prezzo)",
            reason=(f"Prezzo attuale {it(sig.latest)} sotto la mediana {it(sig.reference)} "
                    f"delle ultime {config.LOOKBACK_HOURS}h ({sig.n_obs} osservazioni)."),
            invalidation=(f"Annullata se il prezzo supera {it(sig.entry_max)} prima dell'acquisto, "
                          f"se la mediana scende tanto da azzerare il margine, "
                          f"o dopo {config.CALL_HORIZON_HOURS}h."),
            sources=", ".join(sources),
        )
        db.add(call)
        db.flush()
        db.add(CallEvent(call_id=call.id, kind="created"))
        delay = random.randint(*config.SIM_DELAY_MIN)
        db.add(SimTrade(call_id=call.id, qty=sig.qty, buy_after=call.created_at + timedelta(minutes=delay)))
        created.append(call)
    return created


def check_invalidations(db: Session) -> list[tuple[Call, str]]:
    """Chiude le call scadute o senza più margine. Ritorna (call, motivo)."""
    closed = []
    now = utcnow()
    since = rules.window_start(now)
    for call in active_calls(db):
        created = aware(call.created_at)
        if now >= created + timedelta(hours=call.horizon_hours):
            reason = "scaduta: orizzonte temporale superato"
            db.add(CallEvent(call_id=call.id, kind="expired", note=reason))
            closed.append((call, reason))
            continue
        prices = [o.price for o in window_prices(db, call.card_id, since)]
        if len(prices) >= config.MIN_OBSERVATIONS:
            import statistics
            ref = statistics.median(prices)
            if rules.net_after_tax(call.entry_max, ref * 0.98) <= 0:
                reason = f"annullata: la mediana è scesa a {it(int(ref))}, il margine non c'è più"
                db.add(CallEvent(call_id=call.id, kind="invalidated", note=reason))
                closed.append((call, reason))
                continue
            if prices[-1] > call.entry_max and _trade_status(db, call) == "waiting":
                reason = f"annullata: il prezzo è risalito a {it(prices[-1])}, sopra l'ingresso massimo"
                db.add(CallEvent(call_id=call.id, kind="invalidated", note=reason))
                closed.append((call, reason))
    return closed


def _trade_status(db: Session, call: Call) -> str:
    t = db.scalar(select(SimTrade).where(SimTrade.call_id == call.id))
    return t.status if t else "none"


# ---------- Simulazione ----------

def run_simulation(db: Session) -> None:
    """Fa avanzare le operazioni simulate con le osservazioni di prezzo disponibili.

    - Acquisto: al primo prezzo <= entry_max osservato dopo il ritardo simulato (entro 1h).
    - Vendita: appena un prezzo osservato raggiunge sell_low, al prezzo sell_low (listing realistico).
    - Invenduta: allo scadere dell'orizzonte si esce al prezzo osservato più recente.
    """
    now = utcnow()
    for t in db.scalars(select(SimTrade).where(SimTrade.status.in_(["waiting", "holding"]))).all():
        call = t.call
        end = aware(call.created_at) + timedelta(hours=call.horizon_hours)
        if t.status == "waiting":
            buy_after = aware(t.buy_after)
            if now < buy_after:
                continue
            if call_status(db, call) in TERMINAL and not _has_obs(db, call, buy_after, buy_after + timedelta(hours=1)):
                t.status = "missed"
                continue
            obs = _first_obs(db, call.card_id, buy_after, buy_after + timedelta(hours=1), max_price=call.entry_max)
            if obs:
                t.status, t.buy_price, t.bought_at = "holding", obs.price, obs.observed_at
            elif now > buy_after + timedelta(hours=1):
                t.status = "missed"
            continue
        # holding
        obs = _first_obs(db, call.card_id, aware(t.bought_at), end, min_price=call.sell_low)
        if obs:
            t.status, t.sell_price, t.sold_at = "sold", call.sell_low, obs.observed_at
            t.net = int(t.qty * rules.net_after_tax(t.buy_price, call.sell_low))
        elif now > end:
            last = db.scalar(select(PriceObservation).where(PriceObservation.card_id == call.card_id)
                             .order_by(PriceObservation.observed_at.desc()))
            exit_price = last.price if last else t.buy_price
            t.status, t.sell_price, t.sold_at = "unsold", exit_price, now
            t.net = int(t.qty * rules.net_after_tax(t.buy_price, exit_price))


def _first_obs(db, card_id, start, end, max_price=None, min_price=None):
    q = select(PriceObservation).where(PriceObservation.card_id == card_id,
                                       PriceObservation.observed_at >= start, PriceObservation.observed_at <= end)
    if max_price is not None:
        q = q.where(PriceObservation.price <= max_price)
    if min_price is not None:
        q = q.where(PriceObservation.price >= min_price)
    return db.scalar(q.order_by(PriceObservation.observed_at))


def _has_obs(db, call, start, end):
    return _first_obs(db, call.card_id, start, end, max_price=call.entry_max) is not None


def metrics(db: Session) -> dict:
    """Profitto netto, win rate, drawdown massimo, tempo medio di immobilizzo."""
    trades = db.scalars(select(SimTrade)).all()
    closed = sorted([t for t in trades if t.status in ("sold", "unsold")], key=lambda t: aware(t.sold_at))
    total, peak, max_dd, cum = 0, 0, 0, 0
    for t in closed:
        cum += t.net or 0
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    total = cum
    wins = sum(1 for t in closed if (t.net or 0) > 0)
    holds = [(aware(t.sold_at) - aware(t.bought_at)).total_seconds() / 3600 for t in closed if t.bought_at]
    return {
        "calls": db.query(Call).count(),
        "trades_chiusi": len(closed),
        "in_corso": sum(1 for t in trades if t.status in ("waiting", "holding")),
        "mancati": sum(1 for t in trades if t.status == "missed"),
        "invenduti": sum(1 for t in closed if t.status == "unsold"),
        "profitto_netto": total,
        "win_rate": wins / len(closed) if closed else None,
        "drawdown_max": max_dd,
        "immobilizzo_medio_ore": sum(holds) / len(holds) if holds else None,
    }


# ---------- Impostazioni ----------

def get_setting(db: Session, key: str) -> str | None:
    s = db.get(Setting, key)
    return s.value if s else None


def set_setting(db: Session, key: str, value: str) -> None:
    s = db.get(Setting, key)
    if s:
        s.value = value
    else:
        db.add(Setting(key=key, value=value))
