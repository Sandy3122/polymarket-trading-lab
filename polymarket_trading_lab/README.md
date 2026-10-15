# Polymarket Trading Lab

Portable, local-first Polymarket paper-trading application.

The project is **paper-only**. It does not contain a live order-submission
adapter or wallet/private-key handling. The core application runs locally and
uses a normal SQLAlchemy database URL. Supabase is only an optional PostgreSQL
provider; no Supabase SDK or Supabase-specific feature is required.

## Current scope

- Local SQLite by default
- PostgreSQL-compatible database configuration, including Supabase
- Database-backed markets, paper orders, fills, positions, ledger and decisions
- Risk limits
- Observable M1 strategy using market end time and current bids
- Deterministic JSONL market-data replay contracts
- Public Gamma/CLOB market-data REST adapter
- Public CLOB market WebSocket parser with heartbeat handling
- Continuous paper worker with idempotent trade fills and resolution settlement
- FastAPI local dashboard and API
- Read-only account/reconciliation contracts with no credentials
- Persisted read-only public account snapshots, activity, and reconciliation history
- Explicitly disabled live execution boundary

The historical research used the eventual on-chain resolution time. A live
system cannot know that future timestamp, so this implementation deliberately
uses only the published market end time and data observed at decision time.
Its paper results must be evaluated prospectively and must not be presented as
the historical result without that distinction.

## Requirements

- Python 3.11 or newer
- Internet access when using live public market data
- No Docker requirement for the local application
- Docker Compose files are included for later deployment

## Install and run locally

```bash
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
cp .env.example .env
polymarket-lab init-db
polymarket-lab serve
```

For a migration-managed database, run `alembic upgrade head` instead of
`polymarket-lab init-db`.

Open <http://127.0.0.1:8000>.

Start the continuous public-data paper worker in a second terminal:

```bash
polymarket-lab paper-worker
```

For one bounded discovery/book cycle:

```bash
polymarket-lab paper-worker --once
```

The default worker selection is deliberately narrow: binary markets with a
10–20 minute duration and crypto-related question/slug text. For arbitrary
fixture markets, set `WORKER_REQUIRE_CRYPTO=false`.

## Use Supabase or another database

Set only the standard database URL:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres
```

Install the PostgreSQL driver in the environment where it is needed:

```bash
python -m pip install "psycopg[binary]>=3.2,<4"
```

The application does not import a Supabase client. Moving to another
PostgreSQL provider changes the connection string, not the strategy or paper
engine.

## Deploy later

The same application can run locally or in Docker. The API and paper worker
are separate services in `docker-compose.yml`; both use the same standard
`DATABASE_URL`. For a hosted PostgreSQL provider, set `DATABASE_URL` in `.env`
and run migrations before starting services:

```bash
cp .env.example .env
# edit DATABASE_URL and other limits
docker compose run --rm api alembic upgrade head
docker compose up --build
```

The container contains no wallet, private key, account credential, or live
execution configuration.

If Docker Desktop is not running, use the local Python commands above; Docker
is an optional deployment path, not a runtime requirement.

## API endpoints

```text
GET  /health
GET  /markets
POST /markets
GET  /orders
POST /paper/orders
GET  /portfolio
GET  /decisions
POST /paper/evaluate/{market_id}
POST /accounts/{account_id}/sync
GET  /accounts/{account_id}/snapshots
GET  /accounts/{account_id}/activities
GET  /accounts/{account_id}/reconciliations
```

## Phase 4 read-only account monitoring

Account monitoring uses only the official public Polymarket Data API:

- `https://data-api.polymarket.com/positions?user=<account_id>`
- `https://data-api.polymarket.com/activity?user=<account_id>`

The account ID is a public wallet/proxy address supplied in the URL. The
application does not accept or load API credentials, private keys, wallets,
signatures, or order-placement clients. The positions and activity paths are
configurable with `ACCOUNT_DATA_BASE_URL`, `ACCOUNT_POSITIONS_PATH`, and
`ACCOUNT_ACTIVITY_PATH`; invalid or unavailable paths fail the sync clearly.

The public positions endpoint does not reliably expose a cash balance. Cash is
therefore optional in the provider-neutral account model. When no public cash
field is present, reconciliation is stored with status `cash_unavailable`
while still comparing observed positions. When cash is present, the service
compares it with the paper ledger. Unknown, missing, quantity, and average-price
position differences are persisted as JSON. Sync and reconciliation never
mutate paper orders, fills, ledger entries, or paper positions.

Apply the account tables to an existing database with:

```bash
alembic upgrade head
```

## Public Polymarket market data

The read-only adapter uses the official public surfaces:

- Gamma: `https://gamma-api.polymarket.com`
- CLOB REST: `https://clob.polymarket.com`
- CLOB market WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws/market`

No Etherscan key is required for this phase. The existing `.etherscan_key` is
only relevant to the older blockchain research package and is not read by this
application.

Example discovery and one-shot book snapshot:

```python
from app.market_data import PolymarketPublicClient

client = PolymarketPublicClient()
markets = client.list_markets(limit=100, max_pages=2, closed=False)
for market in markets:
    for event in client.market_events(market):
        print(event.event_type, event.payload)
```

The WebSocket stream is asynchronous and accepts discovered markets:

```python
from app.market_data import PolymarketMarketStream

stream = PolymarketMarketStream(markets[:10])
async for event in stream.events():
    print(event.event_type, event.payload)
```

The adapter does not claim that an exchange fill occurred. It only supplies
public books and market lifecycle events to the paper simulator.

The worker creates maker orders from observable M1 signals, leaves them open,
and fills them only when a later public SELL trade matches the token and price.
It persists external trade IDs so a restart cannot count the same fill twice.
It settles positions only on a normalized resolution event. Real order
submission is not part of this worker.

### Queue/fill models

Because public data cannot reveal exact queue position, paper orders use one of
three explicit models:

```env
PAPER_QUEUE_MODEL=baseline
```

- `optimistic`: assumes the paper order is first at its price.
- `baseline`: starts behind the visible bid size at placement.
- `conservative`: starts behind twice the visible bid size.

Later matching SELL volume consumes estimated queue-ahead volume first. Only
remaining volume can fill the paper order. The selected model and queue
consumption are persisted on every paper order and exposed by `GET /orders`.

## Phase 5 safety boundary

The execution interface has a paper implementation and a deliberately failing
`DisabledLiveExecutionAdapter`. There is no live order client in this project.
This is intentional: account authentication, wallet signing, order submission,
and live canary limits require an explicit separate security review and must
not be enabled by changing one environment variable. The current complete
system therefore supports local paper trading, public-data monitoring,
read-only account sync, reconciliation, replay, and deployment, with real
execution blocked.

## Data boundaries

`app/market_data.py` defines vendor-neutral market, book, and resolution
objects. `JsonlMarketDataSource` supports deterministic replay. The public
adapter translates Gamma/CLOB responses into those objects without changing
the paper ledger or strategy.

## Tests

```bash
pytest
python -m compileall -q app tests migrations
```

All external adapter tests use mocked transports. They do not contact
Polymarket during the test suite.
