"""Calendario degli eventi di Ultimate Team: cosa succede, quando, e cosa conviene fare.

Due tipi di eventi:
  - ricorrenti: ogni settimana alla stessa ora UK (premi Rivals, premi Champs, TOTW, contenuti);
  - datati: promo e upgrade con data attesa (aggiornali qui quando EA conferma le date).
Gli orari UK vengono convertiti nel fuso di Diego (config.TIMEZONE).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import config

UK = ZoneInfo("Europe/London")


@dataclass
class Event:
    when: datetime          # con fuso orario
    name: str
    action: str             # cosa fare: Compra / Vendi / Attendi
    note: str
    confirmed: bool = True


# (giorno della settimana 0=lun, ora UK, minuti, nome, azione, nota)
WEEKLY = [
    (0, 8, 0, "Premi FUT Champions", "Compra", "Tanti pacchetti aperti: carte meta più economiche"),
    (2, 18, 0, "Nuova TOTW", "Vendi", "Chiudi i flip prima dei nuovi contenuti"),
    (3, 8, 0, "Premi Division Rivals", "Compra", "Ondata di pacchetti: momento migliore per comprare fodder"),
    (3, 20, 0, "Picco pre-promo (sera)", "Vendi", "Domanda SBC prima della promo: vendi il fodder"),
    (4, 18, 0, "Nuovi contenuti / promo", "Attendi", "Niente in mano prima; compra dopo il calo"),
    (5, 12, 0, "Weekend League", "Vendi", "Tanta domanda di carte meta: listing alto"),
]

# Promo con data attesa (ora UK 18:00 salvo diversa indicazione). Aggiornare quando EA conferma.
DATED = [
    ("2026-11-06 18:00", "Road to the Knockouts (RTTK) Team 1", "Attendi",
     "Non comprare carte RTTK prima che il percorso upgrade sia pubblico", False),
    ("2026-11-20 18:00", "Hall of FUT Unleashed", "Vendi", "Seconda finestra di vendita fodder", False),
    ("2026-11-24 18:00", "Upgrade 99 Ultimate Scream", "Attendi", "Le carte Scream possono salire prima dell'upgrade", True),
    ("2026-11-27 18:00", "Black Friday Thunderstruck", "Vendi", "Picco di domanda SBC, poi crollo da pacchetti", False),
]


def local_tz() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def upcoming(now: datetime | None = None, days: int = 7, limit: int = 8) -> list[Event]:
    """Eventi dei prossimi `days` giorni, in ordine di tempo."""
    now = (now or datetime.now(UK)).astimezone(UK)
    end = now + timedelta(days=days)
    out: list[Event] = []
    for d in range(days + 1):
        day = (now + timedelta(days=d)).date()
        for wd, h, m, name, action, note in WEEKLY:
            if day.weekday() == wd:
                when = datetime(day.year, day.month, day.day, h, m, tzinfo=UK)
                if now <= when <= end:
                    out.append(Event(when, name, action, note))
    for stamp, name, action, note, confirmed in DATED:
        when = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=UK)
        if now <= when <= end + timedelta(days=21):  # le promo si vedono con più anticipo
            out.append(Event(when, name, action, note, confirmed))
    out.sort(key=lambda e: e.when)
    return out[:limit]


def countdown(when: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(when.tzinfo)
    secs = int((when - now).total_seconds())
    if secs <= 0:
        return "adesso"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"tra {d}g {h}h"
    if h:
        return f"tra {h}h {m}m"
    return f"tra {m}m"


def format_event(e: Event, now: datetime | None = None) -> str:
    local = e.when.astimezone(local_tz())
    days = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
    tag = "" if e.confirmed else " (data attesa)"
    return (f"{days[local.weekday()]} {local:%d/%m %H:%M} ({countdown(e.when, now)}) - "
            f"{e.name}{tag}\n   {e.action}: {e.note}")
