# Travel Booking Mock API

A FastAPI service that serves the mock catalog (hotels, restaurants, leisure
venues, and their sub-entities) produced by the data generator delivered
earlier, plus availability checks and a booking system designed for a
**90-minute workshop on LLM-based task-oriented dialogue**, where each
attendee's code drives one or more LLM agents against this shared server.

- Every catalog entity is **read-only** and queryable with filters.
- **Availability** endpoints for the three bookable element types (rooms,
  tables, leisure venues).
- **Booking creation** is the only "write" endpoint besides the reset
  endpoint below. It accepts or rejects a booking based on real overlap /
  capacity checks.
- **Per-session isolation**: every booking is tagged with the caller's
  session key (`X-Session-Id` header, a random string each attendee
  generates once at the start of their notebook run). Availability and
  booking checks always consider "the shared seed dataset" + "bookings
  created under the same session key" — never another attendee's
  bookings. This means many attendees can hit the same server at the same
  time without ever colliding with each other, **regardless of whether
  they share an egress IP** (which they typically do on hosted notebook
  runtimes like Google Colab — this is why session keys replaced the
  earlier IP-based design).
- A **reset endpoint** lets an attendee delete everything they created,
  scoped strictly to their own session key.
- An **LLM chat endpoint** that relays a full `messages` list (system
  prompt + history) to OpenAI, so attendees never need an API key of
  their own.

## 1. Project structure

```
booking_api/
├── app/
│   ├── main.py            # FastAPI app: startup, CORS, router registration
│   ├── config.py          # All environment variables, in one place
│   ├── data_store.py       # CSV loading + Catalog + BookingStore (overlap logic)
│   ├── db.py                # SQLite persistence for dynamically created bookings
│   ├── schemas.py           # Pydantic models (catalog entities + booking/LLM I/O)
│   ├── deps.py               # Shared FastAPI dependencies (catalog, IP, pagination)
│   ├── filtering.py           # Small query-filtering helpers
│   ├── security.py             # Client IP resolution + in-memory rate limiter
│   └── routers/
│       ├── cities.py
│       ├── customers.py
│       ├── hotels.py            # hotels, room_types, rooms
│       ├── restaurants.py       # restaurants, tables, dishes
│       ├── activities.py
│       ├── availability.py
│       ├── bookings.py
│       └── llm.py
├── data/                     # Bundled seed CSVs (see section 7 to regenerate)
├── storage/                  # SQLite file with dynamically created bookings (gitignored)
├── requirements.txt
├── Procfile                  # `web: uvicorn app.main:app ...`
├── railway.json              # Explicit Railway build/start configuration
├── .python-version
├── .env.example
└── README.md
```

## 2. How the data is organized

- **`data/*.csv`**: the read-only catalog (cities, hotels, room_types,
  rooms, restaurants, restaurant_tables, dishes, activities, customers)
  plus a **seed** `bookings.csv`. This is loaded into memory once at
  startup (`app/data_store.py::Catalog`).
- **Seed bookings** are treated as shared, immutable "ground truth":
  everyone sees them, and they always count when checking overlaps.
- **Dynamic bookings** are the ones created live through `POST /bookings`.
  They are kept in memory *and* persisted to a small SQLite file
  (`storage/dynamic_bookings.sqlite3`) so a process restart doesn't wipe
  out bookings made during the workshop. Each one is tagged with
  `created_by_session`.
- **Session key** (`X-Session-Id` header): a string each attendee
  generates once (e.g. `secrets.token_hex(8)` in Python) and sends on
  every call to the availability/booking endpoints — it is **required**
  there (missing it returns 422). It replaces the earlier "one attendee =
  one IP" model, which breaks down whenever several attendees share an
  egress IP, as is common on hosted notebook runtimes.
- **Visibility rule** (used by every read: listings, availability,
  overlap checks): `seed bookings ∪ {dynamic bookings where
  created_by_session == requester's session key}`. A booking created
  under session A is never visible to, and never blocks, session B —
  while both still respect the shared baseline from the seed dataset.

## 3. Important operational constraint: run a single instance

The booking store lives in the memory of **one Python process** (backed by
SQLite on disk for the dynamic bookings). If Railway ran multiple
replicas/workers of this service, each would have its own separate copy of
that in-memory state, and two attendees hitting different instances could
both "successfully" book the same room. **Do not** enable multiple
replicas or `uvicorn --workers N > 1` for this service. A single instance
comfortably handles a workshop-sized audience; nothing here is CPU-heavy.

## 4. Environment variables

All read from the environment, with defaults suitable for local dev (see
`app/config.py` and `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `data` | Folder with the seed CSVs |
| `STORAGE_DIR` | `storage` | Folder for the SQLite file of dynamic bookings (point this at a Railway Volume for persistence across redeploys — see section 8.6) |
| `CORS_ORIGINS` | `*` | Comma-separated list of allowed origins |
| `DEFAULT_PAGE_SIZE` | `50` | Default page size for list endpoints |
| `MAX_PAGE_SIZE` | `500` | Max page size a caller can request |
| `OPENAI_API_KEY` | – | Setting this is what turns `/llm/chat` on |
| `LLM_MODEL` | `gpt-5-nano` | Fixed server-side model; the client cannot choose one |
| `LLM_MAX_COMPLETION_TOKENS` | `600` | Fixed server-side; sent to OpenAI as `max_completion_tokens` |
| `LLM_REQUEST_TIMEOUT` | `30` | Timeout (seconds) for the upstream OpenAI call |
| `LLM_MAX_MESSAGE_CHARS` | `4000` | Max length of any single message's `content` |
| `LLM_MAX_TOTAL_CHARS` | `8000` | Max combined length of all messages in one call |
| `LLM_MAX_MESSAGES` | `40` | Max number of messages in the `messages` list |
| `LLM_MAX_HTTP_BODY_BYTES` | `20000` | Max raw HTTP body size for `POST /llm/chat`, enforced *before* parsing |
| `LLM_RATE_LIMIT_MAX_REQUESTS` | `5` | Requests allowed per caller per window |
| `LLM_RATE_LIMIT_WINDOW_SECONDS` | `1` | Window length (seconds) for the rate limit above — default: **5 requests/second per caller** |
| `LLM_MAX_CONCURRENT_REQUESTS` | `100` | Global cap on simultaneous in-flight requests, across all callers |

"Per caller" above means: the `X-Session-Id` header if the client sends
one on `/llm/chat` (recommended, and what the workshop notebook always
does), otherwise the source IP. There is intentionally **no**
`LLM_ACCESS_KEY`/shared-secret variable and **no** global daily/lifetime
request or spend cap in this app for the LLM endpoint — see section 9 for
why, and for what to configure on the OpenAI side instead.

The booking date limit (no bookings after **2027-12-31**) is a fixed rule
in `app/config.py::MAX_BOOKING_DATE`, not an environment variable, per the
original requirement.

## 5. Running locally

```bash
cd booking_api
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
cp .env.example .env    # edit if you want the LLM endpoint enabled locally
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive Swagger UI (every
endpoint, its filters, and example payloads are documented there
automatically). `http://127.0.0.1:8000/` returns a small health/info
payload.

## 6. Endpoint overview

Full interactive reference is always at `/docs`; this is just a map.

**Catalog (read-only, all support filtering + pagination via `limit`/`offset`, no session header needed):**
- `GET /cities`, `GET /cities/{id}`
- `GET /customers`, `GET /customers/{id}`
- `GET /hotels`, `GET /hotels/{id}` (filters: city, type, category, price_range, rating, pet_friendly, accessible, reception_24h, services)
- `GET /room_types`, `GET /room_types/{id}`, `GET /hotels/{id}/room_types`
- `GET /rooms`, `GET /rooms/{id}`, `GET /hotels/{id}/rooms`
- `GET /restaurants`, `GET /restaurants/{id}` (filters: city, cuisine_type, price_range, dress_code, rating, accessible, pet_friendly, services)
- `GET /tables`, `GET /tables/{id}`, `GET /restaurants/{id}/tables`
- `GET /dishes`, `GET /dishes/{id}`, `GET /restaurants/{id}/dishes` (filters: category, max_price, dietary_tags, exclude_allergens, max_spicy_level)
- `GET /activities`, `GET /activities/{id}` (filters: city, activity_type, category, indoor_outdoor, accessible, rating, max_price, suitable_for_age, services)

**Availability (read-only, isolation-aware — REQUIRES `X-Session-Id`):**
- `GET /availability/rooms?init_day=&end_day=&hotel_id=&room_type_id=&room_id=`
- `GET /availability/tables?day=&hour=&restaurant_id=&table_id=&min_capacity=`
- `GET /availability/activities?day=&activity_id=&num_people=`

**Bookings (the only write endpoints in the API — REQUIRE `X-Session-Id`):**
- `GET /bookings` (filters incl. `only_mine`), `GET /bookings/{id}` — isolation-aware
- `POST /bookings` — create a booking; see below
- `DELETE /bookings/mine` — deletes every booking created under the requester's session key

**LLM (session header optional but recommended):**
- `POST /llm/chat` — see section 9

### The `X-Session-Id` header

Every availability/booking endpoint requires an `X-Session-Id` header —
any non-empty string between 4 and 128 characters that you generate once
per client run and reuse on every call:

```python
import secrets
SESSION_ID = secrets.token_hex(8)   # e.g. "3f9a1c7b2e4d5f60"
HEADERS = {"X-Session-Id": SESSION_ID}
```

Missing it returns `422`. Reusing the literal value `"seed"` is harmless
but pointless — it gets silently rewritten so you can never impersonate
or collide with the shared seed dataset.

### Creating a booking

`POST /bookings` takes exactly the identifiers relevant to the
`booking_type`, plus dates and party size:

```jsonc
// Hotel room
{
  "customer_id": 12,
  "booking_type": "hotel_room",
  "room_id": 345,
  "init_day": "2026-10-05",
  "end_day": "2026-10-08",
  "num_people": 2
}

// Restaurant table
{
  "customer_id": 12,
  "booking_type": "restaurant_table",
  "table_id": 78,
  "init_day": "2026-10-05",
  "hour": "20:30",
  "num_people": 4
}

// Leisure venue
{
  "customer_id": 12,
  "booking_type": "activity",
  "activity_id": 3,
  "init_day": "2026-10-05",
  "num_people": 2
}
```

Responses:
- **201 Created**, `{"success": true, "message": "...", "booking": {...}}` — the slot was free and the booking was made.
- **409 Conflict**, `{"success": false, "message": "...", "booking": null}` — the slot overlaps with an existing (visible) booking, or the requested capacity doesn't fit.
- **404 Not Found** — a referenced id (room/table/activity/customer) doesn't exist.
- **422 Unprocessable Entity** — malformed request (wrong id for the booking_type, missing `hour` for a table booking, date after 2027-12-31, date in the past, etc).

## 7. Regenerating the seed dataset

The CSVs in `data/` were produced by the generator script delivered
earlier in this project (the one with `--num-hotels`, `--num-bookings`,
`--seed`, etc. parameters). To refresh them with different volumes:

```bash
# from the generator project
python main.py --num-cities 12 --num-hotels 25 --num-restaurants 30 \
  --num-activities 15 --num-customers 200 --num-bookings 900 \
  --start-date 2026-09-01 --days-window 240 --seed 42 \
  --output-dir /path/to/booking_api/data
```

Then restart the API (or redeploy). Note that changing the seed data does
**not** touch `storage/dynamic_bookings.sqlite3` — if you want a fully
clean slate, also delete that file.

## 8. Deploying to Railway — step by step

### 8.1. Push the project to GitHub
1. Create a new (empty) GitHub repository, e.g. `booking-api`.
2. From the `booking_api/` folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-user>/booking-api.git
   git push -u origin main
   ```

### 8.2. Create the Railway project
1. Go to [railway.com](https://railway.com) and log in.
2. Click **New Project → Deploy from GitHub repo**.
3. Link your GitHub account if prompted, then select the `booking-api`
   repo. Click **Deploy Now**.
4. Railway detects Python via Nixpacks, installs `requirements.txt`, and
   uses the `startCommand` from `railway.json` (or the `Procfile`) to run
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. `$PORT` is injected
   automatically by Railway — you don't need to set it.

### 8.3. Set environment variables
In the new service, open the **Variables** tab and add at least:
- `OPENAI_API_KEY` — only if you want `/llm/chat` enabled. See section 9
  for the recommended practice of using a dedicated, budget-capped OpenAI
  project/key for the workshop rather than your main one.
- `LLM_MODEL` — leave as `gpt-5-nano` (the default) unless you want a
  different fixed model.
- Any of the other variables from section 4 you want to override.

No access-token variable is needed for `/llm/chat` — by design, that
endpoint has no shared secret (see section 9).

### 8.4. Expose a public URL
By default, a new Railway service isn't publicly reachable. Go to the
service's **Settings → Networking** section and click **Generate Domain**.
You'll get a URL like `https://booking-api-production.up.railway.app`.

### 8.5. Verify the deployment
```bash
curl https://<your-app>.up.railway.app/health
curl https://<your-app>.up.railway.app/hotels?limit=1
```
Open `https://<your-app>.up.railway.app/docs` in a browser to get the full
interactive API explorer — this is the easiest way for workshop attendees
to try the API without writing any code.

### 8.6. (Recommended) Add a Volume for booking persistence across redeploys
Without a volume, `storage/` lives on the container's local disk: it
survives normal restarts but is wiped whenever you push a new deploy. To
keep attendees' bookings across redeploys during a multi-day workshop:
1. In the Railway project canvas, right-click and choose **Volume** (or
   use the command palette, ⌘K → "Volume").
2. Attach it to your service and set a **mount path**, e.g. `/data`.
3. Add an environment variable `STORAGE_DIR=/data`.
4. Redeploy. From now on, `dynamic_bookings.sqlite3` lives on the volume.

(This is optional — for a single-session workshop the default ephemeral
disk is perfectly fine, especially since the SQLite file already means a
simple process restart never loses data.)

### 8.7. Keep a single, always-on instance
In the service's **Settings**, make sure you are **not** running multiple
replicas and are **not** using a `--workers` flag greater than 1 (see
section 3). If Railway's "serverless"/sleep option is enabled for your
plan, consider disabling it for the duration of the workshop so the first
request from each attendee doesn't hit a cold start.

### 8.8. Redeploying after changes
With the GitHub integration, every `git push` to `main` triggers an
automatic redeploy. You can also trigger one manually from the Railway
dashboard, or with the CLI (`railway up`) if you deployed that way instead.

## 9. LLM endpoint — design rationale

This endpoint exists so attendees never need an OpenAI API key of their
own: their code calls `POST /llm/chat` with the messages they want to
send, and the server relays the call to OpenAI. It evolved from an
earlier "2-hour public demo" design (anonymous internet traffic, a single
free-text `message`, 1 req/s/IP) into this workshop version, where callers
are identified attendees who need to design their own system prompts and
manage their own conversation history — the whole point of the exercise.
What changed and why:

| Aspect | Public-demo version | Workshop version (current) |
|---|---|---|
| Request body | Single `message: str` | Full `messages: [{role, content}, ...]` — system prompt + history included |
| System prompt | Fixed server-side | Chosen by the client, as part of `messages` |
| Rate-limit identity | Source IP | `X-Session-Id` if sent (falls back to IP) — avoids every attendee on a shared Colab/notebook IP fighting over one bucket |
| Rate limit | 1 req/s | 5 req/s per caller (agent loops may need to iterate quickly) |
| Body-size cap | ~1 KB | ~20 KB (`LLM_MAX_HTTP_BODY_BYTES`), since a full conversation is naturally bigger than one message |

What **didn't** change — these safety nets stay regardless of scenario:

| Protection | Implementation |
|---|---|
| API key never reaches the client | `OPENAI_API_KEY` stays server-side only, in `app/config.py` |
| Fixed model | `LLM_MODEL` (default `gpt-5-nano`); not a request parameter |
| Fixed max output tokens | `LLM_MAX_COMPLETION_TOKENS`, sent to OpenAI as `max_completion_tokens` |
| Whitelisted request shape | Only `role`/`content` per message are accepted; any extra field anywhere is rejected with 422 (`extra="forbid"`) |
| Max HTTP size before parsing | `app/middleware.py::MaxBodySizeMiddleware` rejects (413) any `/llm/chat` body over `LLM_MAX_HTTP_BODY_BYTES` as it streams in — before FastAPI ever parses JSON. Also protects against a client that omits/lies about `Content-Length` |
| Max combined message size | `LLM_MAX_TOTAL_CHARS` and `LLM_MAX_MESSAGES`, enforced at the Pydantic level as a second, independent layer of defense |
| Global concurrency limit | `LLM_MAX_CONCURRENT_REQUESTS` (default 100) across all callers combined, via the async `ConcurrencyLimiter` — requests beyond the cap are rejected (503) immediately, never queued |
| Timeouts | `LLM_REQUEST_TIMEOUT` on the upstream call |
| No global spend/requests cap in-app | Deliberately **not** implemented here — total spend is bounded on the **OpenAI side** instead (see below) |
| No access token for this endpoint | By explicit choice — the barrier to entry is intentionally zero |
| No leaking internal errors | Any OpenAI/network failure is logged server-side and returned to the client as a generic 502 |

### Recommended OpenAI-side setup (not enforced by this code)

Since the app has no global budget cap by design, set one on OpenAI's
side before the workshop:
1. Create a **separate OpenAI project** just for this event (Platform →
   Settings → Projects), so its usage/budget is tracked independently
   from anything else on your account.
2. Issue a **project-scoped API key** for it, set as `OPENAI_API_KEY` on
   Railway.
3. Set a **hard budget limit** on that project (a `gpt-5-nano` workshop
   for 90 minutes with dozens of attendees is still inexpensive, but a
   hard cap removes any doubt).
4. After the workshop, **revoke the key** (or delete the project).

### Calling it

No access token is required; sending `X-Session-Id` is optional here but
recommended (see the rate-limit identity note above):

```bash
curl -X POST https://<your-app>.up.railway.app/llm/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: <your session key>" \
  -d '{"messages": [
        {"role": "system", "content": "You are a helpful hotel booking assistant."},
        {"role": "user", "content": "What kind of leisure venues are in the catalog?"}
      ]}'
```

Response:
```json
{"reply": "...", "model": "gpt-5-nano", "usage": {"prompt_tokens": 42, "completion_tokens": 30, "total_tokens": 72}}
```

The endpoint itself is stateless: there's no server-side conversation
memory. Your code is responsible for keeping the running history and
resending however much of it (the last *n* turns, a summary, all of it...)
you want on each call — see the notebook, section 3.

### Testing the protections

```bash
BASE=https://<your-app>.up.railway.app
SID="test-session-0001"

# 1) Normal call
curl -s -X POST $BASE/llm/chat -H "Content-Type: application/json" -H "X-Session-Id: $SID" \
  -d '{"messages": [{"role": "user", "content": "Recommend a 3-star hotel"}]}'

# 2) Rate limit: fire 6 requests back to back from the same session —
#    at least one should come back as 429 (limit is 5/s by default)
for i in $(seq 1 6); do
  curl -s -o /dev/null -w "%{http_code} " -X POST $BASE/llm/chat \
    -H "Content-Type: application/json" -H "X-Session-Id: $SID" \
    -d '{"messages": [{"role": "user", "content": "hi"}]}'
done; echo

# 3) Client cannot pick the model or add extra fields — rejected (422)
curl -s -X POST $BASE/llm/chat -H "Content-Type: application/json" -H "X-Session-Id: $SID" \
  -d '{"messages": [{"role": "user", "content": "hi"}], "model": "gpt-5"}'

# 4) Oversized body -> 413, fast (rejected before any OpenAI call)
python3 -c "import json; print(json.dumps({'messages':[{'role':'user','content':'x'*25000}]}))" > /tmp/big.json
curl -s -o /dev/null -w "%{http_code}\n" -X POST $BASE/llm/chat \
  -H "Content-Type: application/json" -H "X-Session-Id: $SID" --data-binary @/tmp/big.json
```

To exercise the 100-concurrent-request cap you need genuinely parallel
requests (a `curl` loop is too slow); a short `asyncio`/`httpx` script or
a tool like `hey`/`wrk` firing >100 requests at once will show some
responses coming back as 503 once the cap is reached.

### If you reuse this endpoint outside this workshop's scenario

The "no access token" and "no global cap" choices are specific to a
short, supervised event with a budget capped on OpenAI's side. For
anything longer-lived or unsupervised, at minimum: reintroduce a
shared-secret header, and/or add an application-level global
request/spend counter in addition to the OpenAI-side budget.

## 10. Known limitations / possible extensions

- Single-instance, in-memory + SQLite design (see section 3) — sufficient
  for a workshop, not meant for high-availability production use.
- No authentication on the catalog/availability/booking endpoints; the
  only "auth" concept is the per-session isolation model. Add proper auth
  if you reuse this outside the workshop context.
- Session keys are entirely client-chosen and unverified (any string of
  the right length works) — by design, since the goal is collision
  avoidance between attendees, not real authentication. A malicious
  client could still guess/reuse someone else's session key; this is
  considered an acceptable risk for a supervised workshop.
- Booking status for API-created bookings is always `confirmed` (no
  pending/cancellation workflow is exposed, matching the "no create/delete
  endpoints except for bookings" requirement).
- The `/llm/chat` endpoint is a thin relay: it does not manage
  conversation state, tool calls, or agent logic — all of that lives in
  the attendees' own notebook code, by design (see the accompanying
  Colab notebook).

