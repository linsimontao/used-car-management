# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

An inventory management system for a Japanese used-car dealership. Sales staff use colloquial text input to query vehicles, lock them as "in negotiation", release locks, and mark them sold.

## Ground rules

- **[SPEC.md](SPEC.md) is the single source of truth.** When something is unclear, read the relevant SPEC.md section rather than guessing. If this file and SPEC.md disagree, SPEC.md wins.

## Language policy (SPEC §1.2 — strictly enforced)

This is a product for Japanese customers. **This file is written in English, but the project's own artifacts are not.** The rule applies to everything you produce in the repository:

| Artifact | Language |
|---|---|
| Docs, code comments, docstrings | **Japanese** |
| Test data and seed data | **Japanese** (realistic Japanese used cars and Japanese personal names) |
| Error messages and UI copy | **Japanese** (text that can be shown to users verbatim) |
| Variable/function names, DB columns, API paths | **English** (snake_case) |
| Enum values stored in the DB | **English** (`IN_STOCK` etc.; display labels are Japanese, kept separately) |
| Commit messages | **Japanese** |

Test function names are written in Japanese too (e.g. `test_同時ロックは1件のみ成功する`). Follow that convention. Never use Chinese or English placeholder data.

## Commands

### Backend (run from `backend/`)

```bash
# Setup (Python 3.12 — the system python3 is 3.9 and will not work)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env          # optional; defaults work as-is

# Run → http://localhost:8000 (Swagger UI at /docs, health check at /health)
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Tests
.venv/bin/pytest                                    # all (integration tests auto-excluded)
.venv/bin/pytest tests/test_state_machine.py        # single file
.venv/bin/pytest tests/test_state_machine.py::test_t1_在庫から商談中へロックできる   # single test
.venv/bin/pytest -k ロック -v                        # filter by name
.venv/bin/pytest -m integration                     # live Gemini tests (skipped by default)

# Migrations
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate -m "変更内容の説明"
.venv/bin/alembic check          # detect drift between models.py and migrations; always run after editing models
.venv/bin/alembic downgrade -1

# Seed data (3 staff members + ~30 Japanese used cars)
.venv/bin/python -m app.seed
```

### Frontend (run from `frontend/`)

```bash
npm install
npm run dev       # http://localhost:5173; /api is proxied to localhost:8000
npm run build     # includes tsc type checking — this is how you catch type errors
npm run lint      # oxlint
```

Start the backend before working on the frontend; both must be running to verify anything end to end.

## State machine and lock semantics

**Exclusive locking is the core value of this system.** At any moment a vehicle can be held by exactly one staff member, and that hold has a definite owner, a definite expiry, and a complete audit trail.

### Statuses

| DB value | Display label | Badge color |
|---|---|---|
| `IN_STOCK` | 在庫 | green |
| `NEGOTIATING` | 商談中 | orange |
| `SOLD` | 売却済 | gray |

### Transitions (SPEC §5.1)

| # | Transition | Operation | Precondition | Allowed role | Event |
|---|---|---|---|---|---|
| T1 | 在庫 → 商談中 | `lock` | currently `IN_STOCK` | staff / admin | `locked` |
| T2 | 商談中 → 在庫 | `unlock` | actor == `locked_by` | lock owner | `unlocked` |
| T3 | 商談中 → 在庫 | `force_unlock` | actor != `locked_by` and `force=true` | **admin only** | `force_unlocked` |
| T4 | 商談中 → 在庫 | `lock_expired` | `now > lock_expires_at` | system (lazy) | `lock_expired` |
| T5 | 商談中 → 商談中 | `renew` | actor == `locked_by` | lock owner | `lock_renewed` |
| T6 | 在庫 → 売却済 | `sold` | currently `IN_STOCK` | staff / admin | `sold` |
| T7 | 商談中 → 売却済 | `sold` | actor == `locked_by`, or actor is admin | lock owner / admin | `sold` |
| T8 | 売却済 → 在庫 | `unsold` | — | **admin only** | `unsold` |

**Every transition not listed above must be rejected with `409 INVALID_TRANSITION`.**

### Invariants that must never be broken

- `status = 'NEGOTIATING'` ⟺ `locked_by IS NOT NULL AND lock_expires_at IS NOT NULL`
- `status = 'IN_STOCK'` or `'SOLD'` ⟹ all three lock fields (`locked_by` / `locked_at` / `lock_expires_at`) are `NULL`
- The lock fields **always share the same fate**: either all NULL, or all populated. There is no third state.
- `version` increments by 1 after **every** successful write, including the T4 lazy-expiry write-back
- When transitioning to `SOLD` from `NEGOTIATING`, clear the lock fields in the same statement

Lock data lives inside `vehicles` rather than a separate `locks` table because the lock and the status are two sides of one invariant; splitting them creates room for inconsistency. The design depends on being able to constrain both in a single conditional UPDATE.

### Lock details

- The TTL comes from `LOCK_TTL_MINUTES` (default 120) and is global. **Users cannot specify it.** Spoken durations like「1時間だけ押さえて」are deliberately not parsed.
- **A re-`lock` by the current owner is a renewal (T5), not an error.** Reset `lock_expires_at` to `now + TTL` and record `lock_renewed`, not `locked`. This makes the `lock` API naturally idempotent for the same user.
- Locking a vehicle held by someone else returns `409 VEHICLE_LOCKED`. The response must include **the lock owner's name and the remaining minutes** so staff can sort it out between themselves on the spot.

## Architectural notes

These are the design decisions you would otherwise have to read several files to reconstruct.

### 1. Expiry is a lazy write-back — there is no background task

**Every entry point that reads or writes a vehicle must call `vehicle_service.expire_if_needed()` before any business logic.** The list endpoint uses `expire_all_if_needed()` to bulk-expire before querying.

No periodic job is used. This guarantees that a direct `SELECT` against the DB at any moment returns the correct current state, which removes the need for any notion of a recomputed "effective status" in the application layer. **When you add a new code path that touches vehicles, put this call at the top of it.**

### 2. Writes use a conditional UPDATE plus a `version` optimistic lock

Every write API requires the client's `version` in the request body. Put **both the status precondition and the `version` check** in the UPDATE's WHERE clause, then branch on `rowcount`:

- `rowcount == 1` → success
- `rowcount == 0` → **re-read the row to determine why**, and map it:
  - row missing → `404 VEHICLE_NOT_FOUND`
  - `status == 'NEGOTIATING'` → `409 VEHICLE_LOCKED` (attach owner name and remaining minutes)
  - `status == 'SOLD'` → `409 INVALID_TRANSITION`
  - `status == 'IN_STOCK'` but version differs → `409 VERSION_CONFLICT`

Never write "SELECT to check the precondition, then UPDATE". That opens a race window between the check and the write.

### 3. SQLite handling ([app/db.py](backend/app/db.py))

- `journal_mode=WAL`, `foreign_keys=ON`, and `busy_timeout=3000` are applied automatically by the engine's `connect` event listener
- **Every write transaction must go through `immediate_transaction(db)`.** `BEGIN IMMEDIATE` takes the write lock up front and avoids the deadlocks caused by SQLite's deferred lock escalation.
- That helper deliberately calls `rollback()` to discard SQLAlchemy's implicit DEFERRED transaction before issuing `BEGIN IMMEDIATE`. Reversing the order fails with "cannot start a transaction within a transaction".

### 4. The LLM interprets; it never acts

- **SDK: `google-genai` (imported as `google.genai`). Model: `gemini-3.5-flash`**, overridable via `GEMINI_MODEL`. Never hardcode a model ID in the code.
- **Enforce the schema with Gemini's function calling / structured output.** Do not prompt for "output JSON" and parse the string yourself. Catch schema-mismatched responses and fall back to `{"intent": "unknown", "confidence": 0.0}`.
- The LLM's only job is converting natural language into a single structured intent. **It must never read or write the DB, decide permissions, or generate user-facing prose.** Results are rendered by fixed frontend templates, to avoid misread numbers and extra latency.
- **Never trust the LLM's `vehicle_no` directly.** Always run it through `normalize_vehicle_no()` in [llm/normalize.py](backend/app/llm/normalize.py), which deterministically handles kanji numerals, kana readings (イチマルイチ), full-width characters, positional readings (ひゃくいち), and suffixes (番の車 / 号車). If the result is not 3–4 digits, set it to `None` and add it to `missing`. This is the single most error-prone spot in the voice path.
- Parsers are injected through the `IntentParser` interface. With no `GEMINI_API_KEY` set, `get_parser()` returns `MockParser` automatically.
- **All backend unit tests use `MockParser` — no network calls, no token spend.** Live Gemini calls belong in tests marked `@pytest.mark.integration`, which are skipped by default.

### 5. Writes always require explicit confirmation

An LLM parse result must never trigger a DB write on its own. Write intents (lock / unlock / sold) **always** go through a frontend confirmation dialog, **regardless of confidence**. The `LOW_CONFIDENCE_THRESHOLD` setting only adjusts the wording shown; it never skips the confirmation step.

Confirmation state lives **only in frontend memory**. The backend has no pending-session table. The `version` comes from the `GET` that preceded the confirmation, which guarantees that what the user approved is exactly the version they were shown. On `VERSION_CONFLICT` the frontend re-GETs and re-shows the dialog automatically, at most once.

### 6. Error response shape

Every non-2xx response uses `{ "code", "message", "detail" }`. `message` is **Japanese text that can be displayed verbatim**. Add new errors as `AppError` subclasses in [app/errors.py](backend/app/errors.py) — do not raise `HTTPException` directly. The full code list is in SPEC §8.6.

### 7. Authentication is a deliberate simplification

The backend simply trusts the `X-User-Id` header, which is sent on every request except `/api/users`. No passwords, no JWT, no expiry. **This is an MVP tradeoff, not a security measure.** Check SPEC §12.2 (explicit non-goals) before proposing to harden it.

### 8. Alembic's database URL

`sqlalchemy.url` in `alembic.ini` is **intentionally empty**. [alembic/env.py](backend/alembic/env.py) reads `DB_PATH` from `app.config` instead, so the database location has exactly one source of truth. Do not put the URL back into `alembic.ini`.

## Out of scope (SPEC §12.2)

The following are outside the MVP. Do not implement them on your own initiative:

Real speech input (STT); a dedicated admin screen; an event-history screen (the API exists, but no frontend view); vehicle create/edit/CSV import; real authentication; multiple operations in one utterance (only the first is processed); user-specified lock durations; LLM-generated replies or TTS; purchase cost / margin fields; multi-store or multi-tenant support.
