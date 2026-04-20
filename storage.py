from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
REPORTS_FILE = DATA_DIR / "reports.json"


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not REPORTS_FILE.exists():
        REPORTS_FILE.write_text("[]\n", encoding="utf-8")


def load_reports() -> list[dict[str, Any]]:
    ensure_storage()
    content = REPORTS_FILE.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return json.loads(content)


def save_reports(reports: list[dict[str, Any]]) -> None:
    ensure_storage()
    REPORTS_FILE.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_report(report: dict[str, Any]) -> None:
    reports = load_reports()
    reports.append(report)
    reports.sort(key=lambda item: (item["report_date"], item["author"], item["created_at"]), reverse=True)
    save_reports(reports)
