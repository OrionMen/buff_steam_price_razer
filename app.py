from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, flash, redirect, render_template, url_for

from scanner.config import load_settings
from scanner.db import Database
from scanner.service import ScannerService


def present_run(row):
    if row is None:
        return None
    run = dict(row)
    labels = {"success": "成功", "failed": "失败", "running": "进行中"}
    run["status_label"] = labels.get(run["status"], run["status"])
    if run.get("finished_at"):
        finished = datetime.fromisoformat(run["finished_at"])
        local = finished.astimezone(ZoneInfo("Asia/Shanghai"))
        run["finished_at_local"] = local.strftime("%Y-%m-%d %H:%M:%S")
    else:
        run["finished_at_local"] = None
    if run.get("started_at") and run.get("finished_at"):
        started = datetime.fromisoformat(run["started_at"])
        finished = datetime.fromisoformat(run["finished_at"])
        run["duration_seconds"] = max(0, round((finished - started).total_seconds()))
    else:
        run["duration_seconds"] = None
    return run


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "local-cs2-observer"
    settings = load_settings()
    database = Database(settings.database_path)
    service = ScannerService(settings, database)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            quotes=database.top_quotes(50),
            latest_run=present_run(database.latest_run()),
            is_demo=settings.is_demo,
            min_price=settings.buff_min_price,
            max_price=settings.buff_max_price,
        )

    @app.post("/scan")
    def scan():
        try:
            count = service.scan()
            flash(f"扫描完成，成功匹配 {count} 件饰品。", "success")
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(url_for("index"))

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "demo" if settings.is_demo else "live"}

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("APP_PORT", "5050")), debug=False)
