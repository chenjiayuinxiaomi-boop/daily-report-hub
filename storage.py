from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
LEGACY_FILE = DATA_DIR / "reports.json"


def _sanitize(name: str) -> str:
    """把用户名转换成安全的文件名片段。"""
    return re.sub(r"[^\w\-]", "_", name.strip())[:50]


def _author_file(author: str) -> Path:
    return DATA_DIR / f"user_{_sanitize(author)}.json"


def _load_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return []


def _save_file(path: Path, reports: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_reports(author: str | None = None) -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if author:
        per_user = _load_file(_author_file(author))
        legacy = [r for r in _load_file(LEGACY_FILE) if r.get("author") == author]
        combined: dict[str, dict[str, Any]] = {r["id"]: r for r in legacy}
        combined.update({r["id"]: r for r in per_user})
        return sorted(
            combined.values(),
            key=lambda r: (r.get("report_date", ""), r.get("created_at", "")),
            reverse=True,
        )
    all_combined: dict[str, dict[str, Any]] = {}
    for path in [LEGACY_FILE, *sorted(DATA_DIR.glob("user_*.json"))]:
        for r in _load_file(path):
            all_combined[r["id"]] = r
    return sorted(
        all_combined.values(),
        key=lambda r: (r.get("report_date", ""), r.get("created_at", "")),
        reverse=True,
    )


def save_reports(reports: list[dict[str, Any]], author: str | None = None) -> None:
    target = _author_file(author) if author else LEGACY_FILE
    _save_file(target, reports)


def append_report(report: dict[str, Any]) -> None:
    author = report.get("author", "")
    target = _author_file(author) if author else LEGACY_FILE
    existing = _load_file(target)
    if not any(r["id"] == report["id"] for r in existing):
        existing.append(report)
    existing.sort(
        key=lambda r: (r.get("report_date", ""), r.get("created_at", "")),
        reverse=True,
    )
    _save_file(target, existing)
