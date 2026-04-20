from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any


def _iso_week_key(report_date: str) -> str:
    """返回 2026-W16 格式的周标识。"""
    d = date.fromisoformat(report_date)
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _week_range(week_key: str) -> tuple[str, str]:
    """根据 YYYY-Wnn 计算这周的 Mon ~ Sun 日期字符串。"""
    year, week = week_key.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def build_weekly_summary(reports: list[dict[str, Any]], author: str | None = None) -> list[dict[str, Any]]:
    """
    按周聚合日报，返回周列表，每项包含：
      week_key, week_range, authors, total_completed, total_blockers,
      all_completed, all_blockers, risk_level, summary_text
    """
    if author:
        reports = [r for r in reports if r.get("author") == author]

    weeks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        key = _iso_week_key(report["report_date"])
        weeks[key].append(report)

    result = []
    for week_key in sorted(weeks.keys(), reverse=True):
        week_reports = weeks[week_key]
        mon, sun = _week_range(week_key)

        all_completed: list[str] = []
        all_blockers: list[str] = []
        authors: set[str] = set()

        for r in week_reports:
            all_completed.extend(r.get("completed", []))
            all_blockers.extend(r.get("blockers", []))
            authors.add(r.get("author", ""))

        # 整周风险等级：有多个阻塞 → 高；有阻塞 → 中；否则低
        if len(all_blockers) >= 3:
            risk = "高"
        elif all_blockers:
            risk = "中"
        else:
            risk = "低"

        days_count = len(week_reports)
        summary_text = (
            f"本周共 {days_count} 天日报，"
            f"累计完成 {len(all_completed)} 项事项，"
            f"阻塞 {len(all_blockers)} 项，"
            f"整体风险：{risk}。"
        )

        result.append({
            "week_key": week_key,
            "week_range": f"{mon} ~ {sun}",
            "authors": sorted(authors),
            "total_completed": len(all_completed),
            "total_blockers": len(all_blockers),
            "all_completed": all_completed,
            "all_blockers": all_blockers,
            "risk_level": risk,
            "summary_text": summary_text,
            "days_count": days_count,
        })

    return result


def build_weekly_markdown(week: dict[str, Any]) -> str:
    """生成一周的 Markdown 周报。"""
    week_key = week["week_key"]
    week_range = week["week_range"]
    authors = "、".join(week["authors"]) or "未知"
    summary = week["summary_text"]

    completed_lines = "\n".join(f"- {item}" for item in week["all_completed"]) or "- 无"
    blockers_lines = "\n".join(f"- {item}" for item in week["all_blockers"]) or "- 无"

    return f"""# 周报 - {week_key} ({week_range})

**成员：** {authors}

## 本周总结
{summary}

## 本周累计完成事项
{completed_lines}

## 本周阻塞汇总
{blockers_lines}
""".strip()
