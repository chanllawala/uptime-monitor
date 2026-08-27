"""Dashboard: server-rendered FastAPI + Jinja2."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import logging_setup, stats
from .config import settings
from .database import Base, engine, get_db
from .engine import check_monitor
from .metrics import render_metrics
from .models import Monitor
from .timeutil import humanize_duration, utcnow

logging_setup.configure("web")

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.run_scheduler_in_web:
        # Imported here rather than at module scope so the web app does not
        # pull in the scheduler at all in the normal two-process deployment.
        from .scheduler import start_background_thread

        start_background_thread()
    yield


app = FastAPI(title="Uptime Monitor", version="1.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["duration"] = humanize_duration


@app.get("/health")
def health():
    """Liveness endpoint — also handy as a monitor target for a second instance."""
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(db: Session = Depends(get_db)):
    """Prometheus scrape endpoint."""
    body = render_metrics(db, hours=settings.metrics_window_hours)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, hours: int = 24, db: Session = Depends(get_db)):
    summaries = stats.summarize_all(db, hours=hours)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "summaries": summaries,
            "hours": hours,
            "now": utcnow(),
            "incidents": stats.recent_incidents(db, limit=10),
            "slack_enabled": settings.slack_enabled,
            "up_count": sum(1 for s in summaries if s.status == "up"),
            "down_count": sum(1 for s in summaries if s.status == "down"),
        },
    )


@app.get("/monitors/{monitor_id}", response_class=HTMLResponse)
def monitor_detail(
    monitor_id: int, request: Request, hours: int = 24, db: Session = Depends(get_db)
):
    monitor = _get_monitor(db, monitor_id)
    series = stats.check_series(db, monitor, hours=hours)
    return templates.TemplateResponse(
        "monitor.html",
        {
            "request": request,
            "summary": stats.summarize(db, monitor, hours=hours),
            "hours": hours,
            "now": utcnow(),
            "incidents": stats.recent_incidents(db, monitor, limit=20),
            "labels": [c.checked_at.strftime("%H:%M:%S") for c in series],
            "values": [c.response_time_ms if c.is_up else None for c in series],
            "recent": list(reversed(series))[:25],
        },
    )


@app.post("/monitors")
def create_monitor(
    name: str = Form(...),
    url: str = Form(...),
    interval_seconds: int = Form(None),
    expected_status: int = Form(200),
    db: Session = Depends(get_db),
):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    monitor = Monitor(
        name=name.strip(),
        url=url,
        expected_status=expected_status,
        interval_seconds=interval_seconds or settings.default_interval_seconds,
        timeout_seconds=settings.default_timeout_seconds,
    )
    db.add(monitor)
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/monitors/{monitor_id}/toggle")
def toggle_monitor(monitor_id: int, db: Session = Depends(get_db)):
    monitor = _get_monitor(db, monitor_id)
    monitor.enabled = not monitor.enabled
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/monitors/{monitor_id}/check")
def check_now(monitor_id: int, db: Session = Depends(get_db)):
    """Run a check immediately instead of waiting for the worker's next tick."""
    monitor = _get_monitor(db, monitor_id)
    check_monitor(db, monitor)
    return RedirectResponse(f"/monitors/{monitor_id}", status_code=303)


@app.post("/monitors/{monitor_id}/delete")
def delete_monitor(monitor_id: int, db: Session = Depends(get_db)):
    monitor = _get_monitor(db, monitor_id)
    db.delete(monitor)
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/api/monitors/{monitor_id}/series")
def series_json(monitor_id: int, hours: int = 24, db: Session = Depends(get_db)):
    monitor = _get_monitor(db, monitor_id)
    series = stats.check_series(db, monitor, hours=hours)
    return {
        "monitor": monitor.name,
        "points": [
            {
                "at": c.checked_at.isoformat(),
                "up": c.is_up,
                "status_code": c.status_code,
                "response_time_ms": c.response_time_ms,
            }
            for c in series
        ],
    }


def _get_monitor(db: Session, monitor_id: int) -> Monitor:
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor
