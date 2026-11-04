"""Motore numerico: decide se c'è un'operazione sensata. Nessuna AI qui dentro.

Strategia MVP "anomalia di prezzo":
  - prezzo di riferimento = mediana dei prezzi osservati nelle ultime LOOKBACK_HOURS
    (esclusa l'ultima osservazione, per non confrontare il prezzo con se stesso);
  - si vende a ridosso della mediana (fascia sell_low - sell_high);
  - si compra solo se, dopo la tassa EA, resta almeno MIN_NET_PCT di guadagno:
        entry_max = sell_low * (1 - tassa) / (1 + MIN_NET_PCT)
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import config


# ---------- Matematica di base ----------

def net_after_tax(buy: float, sell: float) -> float:
    """Guadagno netto di una carta comprata a `buy` e venduta a `sell`."""
    return sell * (1 - config.EA_TAX) - buy


def breakeven(buy: float) -> float:
    """Prezzo di vendita minimo per non perdere."""
    return buy / (1 - config.EA_TAX)


def price_step(price: float) -> int:
    """Passo dei prezzi sul mercato EA."""
    if price < 1_000:
        return 50
    if price < 10_000:
        return 100
    if price < 50_000:
        return 250
    if price < 100_000:
        return 500
    return 1_000


def floor_to_step(price: float) -> int:
    step = price_step(price)
    return int(price // step * step)


# ---------- Valutazione di una carta ----------

@dataclass
class Signal:
    reference: int
    latest: int
    entry_max: int
    sell_low: int
    sell_high: int
    expected_net_pct: float
    moved_pct: float
    risk: str
    exposure_pct: float
    qty: int
    n_obs: int


def evaluate(prices: list[int], floor_price: int | None = None) -> Signal | None:
    """`prices` = osservazioni nella finestra, dalla più vecchia alla più recente.

    Ritorna un Signal se il prezzo attuale è abbastanza sotto la mediana da lasciare
    un margine netto >= MIN_NET_PCT, altrimenti None.
    """
    if len(prices) < config.MIN_OBSERVATIONS + 1:
        return None
    history, latest = prices[:-1], prices[-1]
    reference = statistics.median(history)

    sell_high = floor_to_step(reference)
    sell_low = floor_to_step(reference * 0.98)          # vendita prudente: 2% sotto la mediana
    entry_max = floor_to_step(sell_low * (1 - config.EA_TAX) / (1 + config.MIN_NET_PCT))

    if latest > entry_max or entry_max <= 0:
        return None

    expected = net_after_tax(entry_max, sell_low) / entry_max

    # Rischio: quanto oscillano i prezzi (coefficiente di variazione) e distanza dal floor.
    spread = statistics.pstdev(history) / reference if reference else 1.0
    if floor_price and entry_max <= floor_price * 1.15:
        risk = "basso"                  # il floor EA limita la perdita
    elif spread < 0.05:
        risk = "basso"
    elif spread < 0.12:
        risk = "medio"
    else:
        risk = "alto"
    exposure = {"basso": 1.0, "medio": 0.5, "alto": 0.25}[risk] * config.MAX_EXPOSURE_PCT
    qty = max(1, int(config.BUDGET * exposure // entry_max))

    return Signal(
        reference=int(reference), latest=latest, entry_max=entry_max,
        sell_low=sell_low, sell_high=sell_high, expected_net_pct=expected,
        moved_pct=latest / reference - 1, risk=risk, exposure_pct=exposure,
        qty=qty, n_obs=len(prices),
    )


def window_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now - timedelta(hours=config.LOOKBACK_HOURS)
