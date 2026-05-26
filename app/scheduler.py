"""APScheduler wiring — hourly refresh in the background."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .cache import HitsCache
from .config import AppConfig
from .refresh import refresh_once

log = logging.getLogger(__name__)


def start_scheduler(cfg: AppConfig, cache: HitsCache) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")

    def _job():
        try:
            refresh_once(cfg, cache)
        except Exception:
            log.exception("Scheduled refresh failed")

    trigger = CronTrigger(hour=cfg.cron_hour, minute=cfg.cron_minute, timezone="UTC")
    scheduler.add_job(
        _job,
        trigger=trigger,
        id="hits-refresh",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.start()
    log.info("Scheduler started (cron hour=%s minute=%s UTC)",
             cfg.cron_hour, cfg.cron_minute)
    return scheduler
