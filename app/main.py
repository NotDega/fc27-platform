"""Punto di ingresso: API web + job ogni minuto + bot Telegram."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app import config, services, telegram_bot
from app.db import SessionLocal, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("fc27")


def engine_job() -> None:
    """Ogni minuto: annulla le call superate, crea quelle nuove, fa avanzare la simulazione."""
    with SessionLocal() as db:
        closed = services.check_invalidations(db)
        created = services.generate_calls(db)
        services.run_simulation(db)
        db.commit()
        for call, reason in closed:
            telegram_bot.send(f"CALL #{call.id} {call.card.name} {call.card.rating}: {reason}")
        for call in created:
            telegram_bot.send(telegram_bot.format_call(call))
        if created or closed:
            log.info("call create: %d, chiuse: %d", len(created), len(closed))


def futdb_universe_job() -> None:
    from app.providers.futdb import FutDB
    try:
        with SessionLocal() as db:
            FutDB().refresh_universe(db)
    except Exception:
        log.exception("FUT-DB: errore nell'aggiornare l'elenco carte")


def futdb_prices_job() -> None:
    from app.providers.futdb import FutDB
    try:
        with SessionLocal() as db:
            FutDB().fetch_prices(db)
    except Exception:
        log.exception("FUT-DB: errore nell'aggiornare i prezzi")


def fctracker_job() -> None:
    from app.providers.fctracker import FCTracker
    try:
        with SessionLocal() as db:
            FCTracker().ingest(db)
    except Exception:
        log.exception("FC-Tracker: errore nello scaricare il pool")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(engine_job, "interval", seconds=60, max_instances=1, coalesce=True)
    if config.FUTDB_TOKEN:
        now = datetime.utcnow()
        scheduler.add_job(futdb_universe_job, "interval", hours=24, next_run_time=now,
                          max_instances=1, coalesce=True, id="futdb_universe")
        scheduler.add_job(futdb_prices_job, "interval", minutes=config.FUTDB_INTERVAL_MIN,
                          next_run_time=now + timedelta(minutes=2), max_instances=1, coalesce=True, id="futdb_prices")
        log.info("Fornitore FUT-DB attivo: rating %d-%d, max %d carte, ogni %d min",
                 config.FUTDB_RATING_MIN, config.FUTDB_RATING_MAX, config.FUTDB_MAX_PLAYERS, config.FUTDB_INTERVAL_MIN)
    else:
        log.info("Fornitore FUT-DB spento (FUTDB_TOKEN mancante)")
    if config.FCT_ENABLED:
        scheduler.add_job(fctracker_job, "interval", minutes=config.FCT_INTERVAL_MIN,
                          next_run_time=datetime.utcnow() + timedelta(seconds=30),
                          max_instances=1, coalesce=True, id="fctracker")
        log.info("Fornitore FC-Tracker attivo: ogni %d min, prezzi fino a %dh", config.FCT_INTERVAL_MIN, config.FCT_MAX_AGE_HOURS)
    scheduler.start()
    telegram_bot.start_polling()
    log.info("Avviato. Simulazione: %s", config.SIM_MODE)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="FC 27 Market Platform", lifespan=lifespan)


@app.get("/")
def health():
    return {"ok": True, "simulazione": config.SIM_MODE, "piattaforma": config.PLATFORM}


class Observation(BaseModel):
    name: str
    rating: int = Field(ge=40, le=99)
    price: int = Field(gt=0)
    version: str = "Rare"
    source: str = "api"
    observed_at: datetime | None = None


@app.post("/observations")
def add_observations(items: list[Observation], x_api_key: str = Header(default="")):
    """Ingresso dati per i fornitori autorizzati (o per importare un CSV convertito)."""
    if not config.API_KEY or x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="API key mancante o errata")
    with SessionLocal() as db:
        for it in items:
            services.record_price(db, it.name, it.rating, it.price, it.source, it.version, it.observed_at)
        db.commit()
    return {"salvati": len(items)}


@app.get("/calls")
def list_calls(x_api_key: str = Header(default="")):
    if not config.API_KEY or x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="API key mancante o errata")
    with SessionLocal() as db:
        return [
            {"id": c.id, "carta": f"{c.card.name} {c.card.rating}", "entry_max": c.entry_max,
             "vendi": [c.sell_low, c.sell_high], "rischio": c.risk, "stato": services.call_status(db, c),
             "creata": c.created_at}
            for c in services.active_calls(db)
        ]


@app.get("/stats")
def stats(x_api_key: str = Header(default="")):
    if not config.API_KEY or x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="API key mancante o errata")
    with SessionLocal() as db:
        return services.metrics(db)
