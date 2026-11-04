"""Tabelle del database.

Regola chiave: una call, una volta creata, non si modifica. I cambi di stato
(annullata, scaduta, ...) vengono registrati come nuove righe in call_events.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Card(Base):
    """Una carta precisa: nome + versione + rating (es. Rice, Rare, 88)."""
    __tablename__ = "cards"
    __table_args__ = (UniqueConstraint("name", "version", "rating", "platform"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(40), default="Rare")
    rating: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(10), default="console")
    floor_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # prezzo minimo EA, se noto


class PriceObservation(Base):
    """Un prezzo osservato in un momento, con la sua fonte (manuale, fornitore autorizzato, ...)."""
    __tablename__ = "price_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), index=True)
    price: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(40))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    card: Mapped[Card] = relationship()


class Call(Base):
    """Una call di trading. Mai modificata dopo la creazione."""
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    strategy: Mapped[str] = mapped_column(String(40))
    platform: Mapped[str] = mapped_column(String(10))
    entry_max: Mapped[int] = mapped_column(Integer)          # prezzo massimo di ingresso
    sell_low: Mapped[int] = mapped_column(Integer)           # fascia di vendita
    sell_high: Mapped[int] = mapped_column(Integer)
    horizon_hours: Mapped[int] = mapped_column(Integer)
    expected_net_pct: Mapped[float] = mapped_column(Float)
    risk: Mapped[str] = mapped_column(String(10))            # basso / medio / alto
    reason: Mapped[str] = mapped_column(Text)
    news_status: Mapped[str] = mapped_column(String(40), default="nessuna notizia")
    moved_pct: Mapped[float] = mapped_column(Float, default=0.0)
    exposure_pct: Mapped[float] = mapped_column(Float)
    invalidation: Mapped[str] = mapped_column(Text)
    sources: Mapped[str] = mapped_column(Text)
    reference_price: Mapped[int] = mapped_column(Integer)    # media usata per il calcolo

    card: Mapped[Card] = relationship()


class CallEvent(Base):
    """Storia di una call: creata, annullata, scaduta, simulata comprata/venduta."""
    __tablename__ = "call_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    kind: Mapped[str] = mapped_column(String(30))   # created / invalidated / expired
    note: Mapped[str] = mapped_column(Text, default="")


class SimTrade(Base):
    """Operazione simulata generata da una call."""
    __tablename__ = "sim_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="waiting")  # waiting / holding / sold / unsold / missed
    buy_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # momento simulato dell'acquisto manuale
    qty: Mapped[int] = mapped_column(Integer, default=0)
    buy_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bought_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sell_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    net: Mapped[int | None] = mapped_column(Integer, nullable=True)

    call: Mapped[Call] = relationship()


class Setting(Base):
    """Piccolo archivio chiave/valore (es. la chat Telegram proprietaria)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
