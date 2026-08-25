# Uptime Monitor

A self-hosted uptime and response-time monitor. It polls a list of HTTP
endpoints on a schedule, records every result, opens and closes incidents as
services fail and recover, and sends real Slack alerts when something breaks.

Containerised with Docker Compose, tested and linted in GitHub Actions, and
deployed to a cloud VM.

![CI](https://github.com/chanllawala/uptime-monitor/actions/workflows/ci.yml/badge.svg)

---

## What it does

- **Scheduled checks.** A worker process polls each monitor on its own
  interval, recording status code, response time, and any error.
- **Incident tracking.** Consecutive failures open an incident; a success
  closes it. The dashboard shows a timeline of outages with their durations.
- **Real Slack alerts.** One message when a service goes down, one when it
  recovers, with the downtime included.
- **Uptime reporting.** Uptime percentage and average response time over a
  rolling window, plus a response-time chart per monitor.
- **Managed from the browser.** Add, pause, delete, and force an immediate
  re-check without touching the database.

## Alerting behaviour

This is the part that makes it usable rather than annoying:

- **A single failed check does not alert.** A monitor must fail
  `FAILURE_THRESHOLD` times consecutively (default 3) before it is declared
  down, so a momentary blip stays quiet.
- **A service that stays down alerts once, not once per poll.** Alerts fire on
  state *transitions*, driven off incidents rather than individual checks.
- **A success resets the failure count**, so flapping does not accumulate
  toward the threshold.
- **Recovery is always announced**, with how long the outage lasted.

`tests/test_engine.py` covers each of these rules directly.

## Architecture

Three containers, so that a slow or hanging HTTP check can never block the
dashboard from rendering:

```
┌──────────┐        ┌──────────────┐
│  worker  │        │     web      │   FastAPI + Jinja2 dashboard
│ (poller) │        │  (dashboard) │   → :8000
└────┬─────┘        └──────┬───────┘
     │                     │
     └──────────┬──────────┘
                ▼
          ┌───────────┐
          │ postgres  │  monitors · checks · incidents
          └───────────┘
```

| Module | Responsibility |
| --- | --- |
| `app/checker.py` | Performs one HTTP check; classifies the outcome |
| `app/engine.py` | State machine: thresholds, incidents, when to alert |
| `app/scheduler.py` | Worker loop; finds due monitors, handles shutdown |
| `app/notifier.py` | Slack delivery, with a logging fallback |
| `app/stats.py` | Uptime and response-time aggregation |
| `app/web.py` | Dashboard routes |

`engine.py` is deliberately separate from `scheduler.py` so the alerting logic
can be tested without any sleeping, threading, or real network calls.

## Running it

### With Docker (how it runs in production)

```bash
cp .env.example .env     # add your Slack webhook URL
docker compose up -d --build
docker compose exec web python -m app.seed    # optional starter monitors
```

Dashboard at <http://localhost:8000>.

```bash
docker compose logs -f worker    # watch checks happen live
```

### Without Docker

Falls back to SQLite, so no database server is needed:

```bash
python -m venv venv
./venv/Scripts/pip install -r requirements-dev.txt   # Windows
# source venv/bin/activate && pip install -r requirements-dev.txt

python -m app.seed
python -m app.scheduler                              # terminal 1
python -m uvicorn app.web:app --port 8000            # terminal 2
```

## Slack alerts

1. Create an Incoming Webhook at <https://api.slack.com/messaging/webhooks>.
2. Put it in `.env` as `SLACK_WEBHOOK_URL`.
3. Restart: `docker compose restart worker`.

Without a webhook the app runs normally and logs alerts instead of sending
them, which is how the tests and local development work. A failed delivery is
logged and swallowed — a broken webhook must never take the poller down with
it, and the failure is logged without the URL so the secret stays out of the
logs.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./uptime.db` | Postgres URL in Docker |
| `SLACK_WEBHOOK_URL` | *(empty)* | Blank disables sending |
| `FAILURE_THRESHOLD` | `3` | Consecutive failures before alerting |
| `SCHEDULER_TICK_SECONDS` | `5` | How often the worker looks for due monitors |
| `DEFAULT_INTERVAL_SECONDS` | `60` | Default poll interval for new monitors |
| `DEFAULT_TIMEOUT_SECONDS` | `10` | Request timeout per check |

## Tests

```bash
pytest -v
ruff check . && ruff format --check .
```

28 tests covering HTTP classification (including timeouts and DNS failures),
the incident state machine, uptime maths, and Slack payload construction —
including one asserting that a failed delivery never writes the webhook URL
into the logs.

## CI/CD

`.github/workflows/ci.yml` runs on every push and pull request:

1. **Lint and test** — `ruff check`, `ruff format --check`, `pytest`
2. **Build image** — builds the container, starts it, and polls `/health`
   until it answers, so a broken image fails CI rather than production
3. **Deploy** — SSHes to the VM and runs `docker compose up -d --build`

The deploy job only runs on `master`, never on pull requests, and is gated on
a `DEPLOY_ENABLED` repository variable so the workflow stays green before any
VM exists.

## Deployment

See [`deploy/oracle-cloud.md`](deploy/oracle-cloud.md) for provisioning an
Oracle Cloud Always Free VM, opening both firewall layers, installing Docker,
and wiring up the GitHub Actions deploy secrets.

## Notes and limitations

- Checks run sequentially within a tick. That is fine for tens of monitors;
  hundreds would want a thread pool or async client.
- There is no authentication on the dashboard. It is intended to sit behind a
  reverse proxy or on a private network — see the Caddy section of the deploy
  guide.
- Check history grows without bound. A production deployment would want a
  retention policy or downsampling of older data.
