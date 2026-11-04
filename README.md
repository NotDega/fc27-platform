# FC 27 Market Platform — v0.1 (MVP)

Piattaforma personale di analisi del mercato di EA SPORTS FC 27 Ultimate Team.
Raccoglie prezzi, trova anomalie, genera **call** con prezzo massimo di ingresso e condizione di annullamento,
le manda su **Telegram** e le **simula** per misurare se c'è un vantaggio reale.

**Non compra e non vende nulla nel gioco.** Nessun accesso all'account EA, nessuna richiesta al mercato EA.

## Come funziona (v0.1)

```
prezzi (/prezzo su Telegram, o API per fornitori autorizzati)
   -> database (storico)
   -> motore a regole (ogni minuto): prezzo attuale vs mediana 48h
   -> call (immutabile) + messaggio Telegram
   -> simulazione: acquisto dopo 10-30 min, vendita a fascia, tassa EA 5%, invenduti
   -> /stats: profitto netto, win rate, drawdown, immobilizzo
```

| File | Cosa contiene |
|---|---|
| `app/engine/rules.py` | Matematica: tassa, pareggio, passi di prezzo, regola "anomalia di prezzo" |
| `app/services.py` | Salvataggio prezzi, creazione/annullamento call, simulazione, metriche |
| `app/telegram_bot.py` | Comandi e notifiche Telegram |
| `app/main.py` | Server web, job ogni minuto, API |
| `app/models.py` | Tabelle del database |
| `tests/test_flow.py` | Test del flusso completo |

## Deploy su Railway, passo passo

### 1. Codice su GitHub
Il repository `fc27-platform` sul tuo GitHub contiene questo codice (lo carico io, oppure trascini i file in "Add file → Upload files").

### 2. Progetto su Railway
1. Vai su [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → scegli `fc27-platform`.
2. Nello stesso progetto: **+ New** → **Database** → **PostgreSQL**.
3. Apri il servizio `fc27-platform` → scheda **Variables** → **+ New Variable** → **Add Reference** → scegli `DATABASE_URL` di Postgres.

### 3. Variabili
Sempre in **Variables** del servizio `fc27-platform`, aggiungi:

| Nome | Valore |
|---|---|
| `TELEGRAM_TOKEN` | il token di @BotFather |
| `API_KEY` | una password lunga a tua scelta (serve per le API) |
| `SIM_MODE` | `true` |
| `BUDGET` | `500000` |

Railway riavvia da solo il servizio.

### 4. Collega Telegram
Apri il tuo bot e scrivi **/start**. La prima chat che lo fa diventa la proprietaria: il bot risponde solo a te.

### 5. Verifica
- Nella scheda **Deployments** → **View logs** deve comparire `Avviato. Simulazione: True`.
- Su Telegram `/aiuto` mostra i comandi.

## Prezzi automatici: FUT-DB (premium)

Con un abbonamento premium a [futdatabase.com](https://www.futdatabase.com) la piattaforma lavora da sola in background:

- una volta al giorno sceglie le carte da seguire (rating 84-90, massimo 300);
- ogni ora scarica il prezzo PlayStation/console di ognuna e il floor EA;
- il motore controlla i prezzi ogni minuto e ti scrive su Telegram quando trova un'occasione.

Per attivarlo aggiungi su Railway la variabile `FUTDB_TOKEN` con la chiave API di FUT-DB. Facoltative:

| Variabile | Predefinito | Significato |
|---|---|---|
| `FUTDB_RATING_MIN` / `FUTDB_RATING_MAX` | 84 / 90 | Fascia di rating seguita |
| `FUTDB_MAX_PLAYERS` | 300 | Numero massimo di carte |
| `FUTDB_INTERVAL_MIN` | 60 | Minuti tra un aggiornamento e l'altro |
| `FUTDB_DAILY_LIMIT` | 18000 | Richieste massime al giorno (il piano ne dà 20.000) |

Consumo: 300 carte × 24 aggiornamenti = 7.200 richieste al giorno. Su Telegram `/fonte` mostra lo stato.

## Uso quotidiano (Fase 1)

Finché non abbiamo un fornitore di dati autorizzato, i prezzi li inserisci tu dal gioco:

```
/prezzo Declan Rice 88 13000
/prezzo Elliot Anderson 85 20000 TOTW
/floor Declan Rice 88 8300
```

Servono almeno 6 prezzi per carta nelle ultime 48 ore prima che il motore possa generare una call.
Altri comandi: `/call`, `/stats`, `/carte`.

## Regole del motore (si regolano dopo la simulazione)

- Riferimento: mediana dei prezzi delle ultime 48h (esclusa l'ultima osservazione).
- Vendita: tra il 98% e il 100% della mediana.
- Ingresso massimo: `vendita_bassa × 0,95 ÷ 1,05` (almeno +5% netto dopo la tassa).
- Rischio: basso/medio/alto in base a quanto oscilla il prezzo e alla distanza dal floor EA.
- Esposizione: 10% del budget (rischio basso), 5% (medio), 2,5% (alto).
- Annullamento: prezzo sopra l'ingresso massimo prima dell'acquisto, margine azzerato dalla mediana, o dopo 24h.

## Test in locale (facoltativo)

```
pip install -r requirements.txt
python tests/test_flow.py
```
