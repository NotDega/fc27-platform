"""Impostazioni lette dalle variabili d'ambiente (su Railway: scheda Variables)."""
import os


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# Database: su Railway viene impostato in automatico quando aggiungi Postgres.
# In locale, senza variabile, usa un file SQLite.
DATABASE_URL = _get("DATABASE_URL", "sqlite:///./fc27.db")
# Railway dà "postgres://..." o "postgresql://...": diciamo a SQLAlchemy di usare il driver psycopg (v3).
for _prefix in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(_prefix):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len(_prefix):]
        break

# Telegram
TELEGRAM_TOKEN = _get("TELEGRAM_TOKEN")
# Solo questa chat può dare comandi al bot. Se vuota, la prima chat che scrive /start diventa la proprietaria.
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

# Chiave per caricare prezzi via API (POST /observations). Scegline una lunga e casuale.
API_KEY = _get("API_KEY")

# Mercato e budget
PLATFORM = _get("PLATFORM", "console")
BUDGET = int(_get("BUDGET", "500000"))

# Modalità simulazione: finché è "true" la piattaforma NON suggerisce di usare crediti veri.
SIM_MODE = _get("SIM_MODE", "true").lower() == "true"

# Fornitore FUT-DB (premium). Se FUTDB_TOKEN è vuoto, il fornitore resta spento.
FUTDB_TOKEN = _get("FUTDB_TOKEN")
FUTDB_BASE_URL = _get("FUTDB_BASE_URL", "https://api.futdatabase.com")
FUTDB_RATING_MIN = int(_get("FUTDB_RATING_MIN", "84"))
FUTDB_RATING_MAX = int(_get("FUTDB_RATING_MAX", "90"))
FUTDB_MAX_PLAYERS = int(_get("FUTDB_MAX_PLAYERS", "300"))     # carte seguite
FUTDB_INTERVAL_MIN = int(_get("FUTDB_INTERVAL_MIN", "60"))    # ogni quanto aggiornare i prezzi
FUTDB_DAILY_LIMIT = int(_get("FUTDB_DAILY_LIMIT", "18000"))   # margine sotto le 20.000 del piano

# Regole del motore (valori di partenza, si regolano dopo la simulazione)
EA_TAX = 0.05                 # trattenuta EA su ogni vendita
MIN_OBSERVATIONS = int(_get("MIN_OBSERVATIONS", "5"))      # osservazioni minime per calcolare la media
LOOKBACK_HOURS = int(_get("LOOKBACK_HOURS", "48"))         # finestra della media di riferimento
MIN_NET_PCT = float(_get("MIN_NET_PCT", "0.05"))           # rendimento netto minimo di una call (5%)
MAX_EXPOSURE_PCT = float(_get("MAX_EXPOSURE_PCT", "0.10")) # esposizione massima per call (10% del budget)
CALL_HORIZON_HOURS = int(_get("CALL_HORIZON_HOURS", "24")) # dopo quanto una call scade
SIM_DELAY_MIN = (10, 30)      # ritardo simulato tra notifica e acquisto manuale, in minuti
