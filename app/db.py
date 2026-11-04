"""Connessione al database."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Colonne aggiunte dopo la prima versione: (tabella, colonna, tipo SQL)
_MIGRATIONS = [
    ("cards", "external_id", "VARCHAR(40)"),
]


def init_db() -> None:
    from app import models  # noqa: F401  (registra le tabelle)
    Base.metadata.create_all(engine)
    # create_all non modifica tabelle già esistenti: aggiungiamo a mano le colonne nuove.
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, sql_type in _MIGRATIONS:
            existing = {c["name"] for c in insp.get_columns(table)}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
