"""Bot Telegram: notifiche delle call e comandi per inserire prezzi e vedere i risultati.

Usa il "long polling" (il bot chiede a Telegram i messaggi nuovi): non serve configurare
nessun indirizzo pubblico.
"""
from __future__ import annotations

import logging
import re
import threading
import time

import httpx

from app import config, services
from app.db import SessionLocal
from app.models import Call

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{token}/{method}"

HELP = (
    "Comandi\n"
    "/prezzo Nome Rating Prezzo [Versione] - registra un prezzo visto nel gioco\n"
    "   es. /prezzo Declan Rice 88 13000\n"
    "/floor Nome Rating Prezzo - prezzo minimo EA della carta\n"
    "/call - call attive\n"
    "/stats - risultati della simulazione\n"
    "/carte - carte seguite e ultimo prezzo\n"
    "/fonte - stato del fornitore di prezzi automatico\n"
    "/aiuto - questo messaggio"
)


def _call(method: str, **params) -> dict | None:
    if not config.TELEGRAM_TOKEN:
        return None
    try:
        r = httpx.post(API.format(token=config.TELEGRAM_TOKEN, method=method), json=params, timeout=40)
        return r.json()
    except httpx.HTTPError as e:
        log.warning("Telegram %s: %s", method, e)
        return None


def owner_chat() -> str | None:
    if config.TELEGRAM_CHAT_ID:
        return config.TELEGRAM_CHAT_ID
    with SessionLocal() as db:
        return services.get_setting(db, "owner_chat")


def send(text: str) -> None:
    chat = owner_chat()
    if chat:
        _call("sendMessage", chat_id=chat, text=text, disable_web_page_preview=True)


def fmt(n: int | float) -> str:
    return f"{int(n):,}".replace(",", ".")


def format_call(call: Call) -> str:
    c = call.card
    mode = "SIMULAZIONE - non usare crediti veri\n\n" if config.SIM_MODE else ""
    return (
        f"{mode}CALL #{call.id} - {c.name} {c.rating} ({c.version}) - {call.platform}\n"
        f"Compra fino a: {fmt(call.entry_max)}\n"
        f"Vendi tra: {fmt(call.sell_low)} e {fmt(call.sell_high)}\n"
        f"Netto atteso: +{call.expected_net_pct:.1%} dopo la tassa EA\n"
        f"Orizzonte: {call.horizon_hours}h - Rischio: {call.risk}\n"
        f"Esposizione massima: {call.exposure_pct:.0%} del budget\n"
        f"Motivo: {call.reason}\n"
        f"Notizia: {call.news_status}\n"
        f"Movimento rispetto alla mediana: {call.moved_pct:+.1%}\n"
        f"Annullamento: {call.invalidation}\n"
        f"Fonti: {call.sources}"
    )


# ---------- Comandi ----------

PRICE_RE = re.compile(r"^(?P<name>.+?)\s+(?P<rating>\d{2})\s+(?P<price>[\d.,]+)(?:\s+(?P<version>\S.*))?$")


def _parse_price(arg: str):
    m = PRICE_RE.match(arg.strip())
    if not m:
        return None
    price = int(re.sub(r"[.,]", "", m["price"]))
    return m["name"], int(m["rating"]), price, (m["version"] or "Rare")


def handle(chat_id: str, text: str) -> str | None:
    cmd, _, arg = text.strip().partition(" ")
    cmd = cmd.split("@")[0].lower()
    with SessionLocal() as db:
        owner = config.TELEGRAM_CHAT_ID or services.get_setting(db, "owner_chat")
        if cmd == "/start":
            if not owner:
                services.set_setting(db, "owner_chat", chat_id)
                db.commit()
                return "Collegato. Da ora ricevi qui le call (in simulazione).\n\n" + HELP
            if owner != chat_id:
                return "Questo bot è privato."
            return HELP
        if owner != chat_id:
            return None  # ignora chiunque non sia il proprietario
        if cmd in ("/aiuto", "/help"):
            return HELP
        if cmd in ("/prezzo", "/floor"):
            parsed = _parse_price(arg)
            if not parsed:
                return "Formato: /prezzo Nome Rating Prezzo [Versione]\nes. /prezzo Declan Rice 88 13000"
            name, rating, price, version = parsed
            if cmd == "/floor":
                card = services.get_or_create_card(db, name, rating, version)
                card.floor_price = price
                db.commit()
                return f"Floor di {card.name} {rating} impostato a {fmt(price)}."
            services.record_price(db, name, rating, price, source="manuale", version=version)
            db.commit()
            return f"Registrato: {name} {rating} a {fmt(price)}."
        if cmd == "/call":
            calls = services.active_calls(db)
            if not calls:
                return "Nessuna call attiva."
            return "\n\n".join(format_call(c) for c in calls[:5])
        if cmd == "/stats":
            m = services.metrics(db)
            wr = f"{m['win_rate']:.0%}" if m["win_rate"] is not None else "-"
            hold = f"{m['immobilizzo_medio_ore']:.1f}h" if m["immobilizzo_medio_ore"] is not None else "-"
            return (
                "Simulazione\n"
                f"Call generate: {m['calls']}\n"
                f"Operazioni chiuse: {m['trades_chiusi']} (invendute: {m['invenduti']})\n"
                f"In corso: {m['in_corso']} - Mancate: {m['mancati']}\n"
                f"Profitto netto: {fmt(m['profitto_netto'])}\n"
                f"Win rate: {wr} - Drawdown massimo: {fmt(m['drawdown_max'])}\n"
                f"Immobilizzo medio: {hold}"
            )
        if cmd == "/fonte":
            if not config.FUTDB_TOKEN:
                return "Fornitore automatico spento: manca FUTDB_TOKEN su Railway. Prezzi solo manuali (/prezzo)."
            from sqlalchemy import func, select
            from app.models import Card, PriceObservation
            from app.providers.futdb import FutDB, SOURCE
            n_cards = db.query(Card).filter(Card.external_id.isnot(None)).count()
            n_obs = db.query(PriceObservation).filter(PriceObservation.source == SOURCE).count()
            last = db.scalar(select(func.max(PriceObservation.observed_at)).where(PriceObservation.source == SOURCE))
            used = FutDB.used_today(FutDB.__new__(FutDB), db)
            last_txt = f"{last:%d/%m %H:%M} UTC" if last else "nessuno ancora"
            return (
                "FUT-DB attivo\n"
                f"Carte seguite: {n_cards} (rating {config.FUTDB_RATING_MIN}-{config.FUTDB_RATING_MAX})\n"
                f"Prezzi salvati: {fmt(n_obs)}\n"
                f"Ultimo prezzo: {last_txt}\n"
                f"Richieste oggi: {fmt(used)} / {fmt(config.FUTDB_DAILY_LIMIT)}"
            )
        if cmd == "/carte":
            from sqlalchemy import select
            from app.models import Card, PriceObservation
            lines = []
            for card in db.scalars(select(Card).order_by(Card.name)).all()[:30]:
                last = db.scalar(select(PriceObservation).where(PriceObservation.card_id == card.id)
                                 .order_by(PriceObservation.observed_at.desc()))
                n = db.query(PriceObservation).filter(PriceObservation.card_id == card.id).count()
                lines.append(f"{card.name} {card.rating}: {fmt(last.price) if last else '-'} ({n} prezzi)")
            return "\n".join(lines) or "Nessuna carta ancora. Usa /prezzo."
        return "Comando non riconosciuto. /aiuto per la lista."


def _poll_forever() -> None:
    offset = 0
    while True:
        res = _call("getUpdates", offset=offset, timeout=30)
        if not res or not res.get("ok"):
            time.sleep(5)
            continue
        for upd in res["result"]:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = msg.get("text")
            if not text or not text.startswith("/"):
                continue
            chat_id = str(msg["chat"]["id"])
            try:
                reply = handle(chat_id, text)
            except Exception:  # un comando sbagliato non deve fermare il bot
                log.exception("Errore nel comando %s", text)
                reply = "Errore interno, riprova."
            if reply:
                _call("sendMessage", chat_id=chat_id, text=reply)


def start_polling() -> None:
    if not config.TELEGRAM_TOKEN:
        log.warning("TELEGRAM_TOKEN mancante: bot disattivato")
        return
    threading.Thread(target=_poll_forever, daemon=True, name="telegram").start()
