from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

try:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


DEFAULT_BASE_URL = "https://atc.bmwgroup.net/confluence"
DEFAULT_STATE_FILE = Path("data/confluence_weekly_row_copier_state.json")


@dataclass(frozen=True)
class Rule:
    key: str
    parent_id: str
    title_suffix: str
    feature: str
    fos_names: tuple[str, ...] = ()
    min_cells: int = 1
    title_pattern: str | None = None
    second_cell_values: tuple[str, ...] = ()
    copy_all_by_occurrence: bool = False
    copy_header_contexts: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CellRef:
    inner_start: int
    inner_end: int
    inner_html: str
    text: str
    col_start: int
    col_span: int


@dataclass(frozen=True)
class RowRef:
    table_index: int
    row_index: int
    cells: tuple[CellRef, ...]


@dataclass(frozen=True)
class WeeklyPage:
    week: int
    title: str
    page_id: str


RULES = [
    Rule(
        key="idc_cn_vod",
        parent_id="7669198289",
        title_suffix="IDC",
        feature="CN VOD",
        min_cells=6,
        copy_header_contexts=(
            ("release circle target date (required field)", "11/26(pu info)"),
            ("11/26(pu info)", "11/26(pu info)"),
            ("11/26(pu info)", "which version will be used for this test?"),
            ("which version will be used for this test?", "release circle target date (required field)"),
        ),
    ),
    Rule(
        key="mgu_tencent_mpp",
        parent_id="7665084818",
        title_suffix="MGU",
        feature="Video Streaming in Tencent MPP",
        fos_names=("Zain Qian", "Zhu Zola", "Liu Arun"),
        min_cells=6,
    ),
    Rule(
        key="mgu_padi_victoria",
        parent_id="7665084818",
        title_suffix="MGU",
        feature="Padi",
        second_cell_values=("Chu Vivian/victoria zhao",),
        min_cells=2,
    ),
    Rule(
        key="idcevo_cn_launcher",
        parent_id="7665067082",
        title_suffix="IDCEvo",
        feature="CN Launcher",
        min_cells=4,
        title_pattern=r"^2026_CW(\d+)_IDCEvo(?:(?:/|\+|\s+)PENT)?$",
        second_cell_values=("Use Co-Driver Entertainment", "Use Rear Seat Entertainment"),
    ),
    Rule(
        key="idcevo_cn_vod",
        parent_id="7665067082",
        title_suffix="IDCEvo",
        feature="CN VOD",
        min_cells=4,
        title_pattern=r"^2026_CW(\d+)_IDCEvo(?:(?:/|\+|\s+)PENT)?$",
        second_cell_values=("Video Streaming China",),
        copy_all_by_occurrence=True,
    ),
]


TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
CELL_RE = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>", re.IGNORECASE | re.DOTALL)


def _token_from_env() -> str:
    for name in (
        "ATC_CONFLUENCE_TOKEN",
        "CONFLUENCE_TOKEN",
        "CONFLUENCE_API_TOKEN",
        "CC_CONFLUENCE_API_TOKEN",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            return re.sub(r"(?i)^bearer\s+", "", value).strip()
    return ""


def _session(base_url: str) -> requests.Session:
    token = _token_from_env()
    if not token:
        raise RuntimeError(
            "Missing Confluence token. Set ATC_CONFLUENCE_TOKEN or CONFLUENCE_TOKEN."
        )
    session = requests.Session()
    session.trust_env = False
    session.verify = False
    session.headers.update(
        {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
    )
    session.base_url = base_url.rstrip("/")  # type: ignore[attr-defined]
    return session


def _request_json(
    session: requests.Session,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url = session.base_url  # type: ignore[attr-defined]
    response = session.request(
        method,
        f"{base_url}{path}",
        params=params,
        json=payload,
        timeout=45,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Confluence {method} {path} failed: HTTP {response.status_code} "
            f"{response.text[:500]}"
        )
    return response.json()


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"rules": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _cell_text(inner_html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", inner_html, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    return _normalize_text(text)


def _parse_rows(storage_html: str) -> list[RowRef]:
    rows: list[RowRef] = []
    for table_index, table_match in enumerate(TABLE_RE.finditer(storage_html), 1):
        table_html = table_match.group(0)
        table_start = table_match.start()
        for row_index, row_match in enumerate(TR_RE.finditer(table_html), 1):
            row_inner_html = row_match.group(1)
            row_inner_start = table_start + row_match.start(1)
            cells: list[CellRef] = []
            current_col = 1
            for cell_match in CELL_RE.finditer(row_inner_html):
                attrs = cell_match.group(2) or ""
                inner_html = cell_match.group(3)
                colspan_match = re.search(r"\bcolspan\s*=\s*[\"']?(\d+)", attrs, flags=re.IGNORECASE)
                col_span = int(colspan_match.group(1)) if colspan_match else 1
                if col_span < 1:
                    col_span = 1
                cells.append(
                    CellRef(
                        inner_start=row_inner_start + cell_match.start(3),
                        inner_end=row_inner_start + cell_match.end(3),
                        inner_html=inner_html,
                        text=_cell_text(inner_html),
                        col_start=current_col,
                        col_span=col_span,
                    )
                )
                current_col += col_span
            if cells:
                rows.append(RowRef(table_index=table_index, row_index=row_index, cells=tuple(cells)))
    return rows


def _column_pairs_by_logical_column(source_row: RowRef, target_row: RowRef) -> list[tuple[CellRef, CellRef]]:
    def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
        return max(0, min(a_end, b_end) - max(a_start, b_start))

    used_target: set[int] = set()
    pairs: list[tuple[CellRef, CellRef]] = []

    for source_cell in source_row.cells:
        s_start = source_cell.col_start
        s_end = s_start + source_cell.col_span
        best_tidx: int | None = None
        best_score = 0
        for tidx, target_cell in enumerate(target_row.cells):
            if tidx in used_target:
                continue
            t_start = target_cell.col_start
            t_end = t_start + target_cell.col_span
            score = _overlap(s_start, s_end, t_start, t_end)
            if score > best_score:
                best_score = score
                best_tidx = tidx
        if best_tidx is not None and best_score > 0:
            used_target.add(best_tidx)
            pairs.append((source_cell, target_row.cells[best_tidx]))

    if pairs:
        return pairs
    pair_count = min(len(source_row.cells), len(target_row.cells))
    return list(zip(source_row.cells[:pair_count], target_row.cells[:pair_count]))


def _find_weekly_pages(session: requests.Session, rule: Rule) -> list[WeeklyPage]:
    pages: list[WeeklyPage] = []
    start = 0
    pattern = re.compile(rule.title_pattern or (rf"^2026_CW(\d+)_" + re.escape(rule.title_suffix) + r"$"))
    while True:
        data = _request_json(
            session,
            "GET",
            f"/rest/api/content/{rule.parent_id}/child/page",
            params={"limit": 100, "start": start, "expand": "version"},
        )
        results = data.get("results") or []
        for item in results:
            title = str(item.get("title") or "")
            match = pattern.match(title)
            if match:
                pages.append(WeeklyPage(int(match.group(1)), title, str(item.get("id"))))
        if not (data.get("_links") or {}).get("next") or not results:
            break
        start += len(results)
    return sorted(pages, key=lambda page: page.week)


def _fetch_page(session: requests.Session, page_id: str) -> dict[str, Any]:
    return _request_json(
        session,
        "GET",
        f"/rest/api/content/{page_id}",
        params={"expand": "body.storage,version,space"},
    )


def _storage_html(page: dict[str, Any]) -> str:
    return str((((page.get("body") or {}).get("storage") or {}).get("value")) or "")


def _matches_rule(row: RowRef, rule: Rule) -> bool:
    if len(row.cells) < rule.min_cells:
        return False
    texts = [_normalize_text(cell.text) for cell in row.cells]
    if not texts or texts[0].lower() != rule.feature.lower():
        return False
    if rule.second_cell_values:
        if len(texts) < 2:
            return False
        return any(texts[1].lower() == value.lower() for value in rule.second_cell_values)
    if rule.fos_names:
        if len(texts) < 2:
            return False
        fos_text = texts[1].lower()
        return all(name.lower() in fos_text for name in rule.fos_names)
    return True


def _find_target_row(storage_html: str, rule: Rule) -> RowRef:
    matches = [row for row in _parse_rows(storage_html) if _matches_rule(row, rule)]
    if len(matches) != 1:
        locations = ", ".join(f"table {row.table_index} row {row.row_index}" for row in matches)
        raise RuntimeError(
            f"Rule {rule.key} expected exactly one matching row, found {len(matches)}"
            + (f" ({locations})" if locations else "")
        )
    return matches[0]


def _find_header_row(storage_html: str, table_index: int, before_row_index: int) -> RowRef | None:
    rows = [row for row in _parse_rows(storage_html) if row.table_index == table_index and row.row_index < before_row_index]
    if not rows:
        return None

    def _score(row: RowRef) -> tuple[int, int, int]:
        texts = [_normalize_text(cell.text).lower() for cell in row.cells]
        non_empty = sum(1 for text in texts if text)
        first = texts[0] if texts else ""
        # Prefer rows that look like table headers, otherwise pick the densest row.
        header_like = 1 if first in {"feature", "function", "module", "feature/function"} else 0
        return (header_like, non_empty, len(row.cells))

    return max(rows, key=_score)


def _header_label_for_col(header_row: RowRef, col: int) -> str:
    for cell in header_row.cells:
        start = cell.col_start
        end = start + cell.col_span
        if start <= col < end:
            return _normalize_text(cell.text).lower()
    return ""


def _header_left_anchor_for_col(header_row: RowRef, col: int) -> str:
    anchor = ""
    for cell in header_row.cells:
        start = cell.col_start
        if start >= col:
            break
        text = _normalize_text(cell.text).lower()
        if text:
            anchor = text
    return anchor


def _cell_header_context(header_row: RowRef, cell: CellRef) -> tuple[str, str]:
    return (
        _header_left_anchor_for_col(header_row, cell.col_start),
        _header_label_for_col(header_row, cell.col_start),
    )


def _column_pairs_by_header_context(
    source_header: RowRef,
    target_header: RowRef,
    source_row: RowRef,
    target_row: RowRef,
) -> list[tuple[CellRef, CellRef]]:
    # Use (left non-empty header, current header) as semantic key to disambiguate
    # repeated column titles like "Which version will be used for this test?".
    target_buckets: dict[tuple[str, str], list[int]] = {}
    for tidx, target_cell in enumerate(target_row.cells):
        col = target_cell.col_start
        key = (
            _header_left_anchor_for_col(target_header, col),
            _header_label_for_col(target_header, col),
        )
        target_buckets.setdefault(key, []).append(tidx)

    bucket_pos: dict[tuple[str, str], int] = {}
    pairs: list[tuple[CellRef, CellRef]] = []
    used_target: set[int] = set()

    for source_cell in source_row.cells:
        col = source_cell.col_start
        key = (
            _header_left_anchor_for_col(source_header, col),
            _header_label_for_col(source_header, col),
        )
        candidates = target_buckets.get(key) or []
        start_idx = bucket_pos.get(key, 0)
        chosen: int | None = None
        for idx in range(start_idx, len(candidates)):
            tidx = candidates[idx]
            if tidx not in used_target:
                chosen = tidx
                bucket_pos[key] = idx + 1
                break
        if chosen is None:
            for idx, target_cell in enumerate(target_row.cells):
                if idx in used_target:
                    continue
                if target_cell.col_start == col:
                    chosen = idx
                    break
        if chosen is not None:
            used_target.add(chosen)
            pairs.append((source_cell, target_row.cells[chosen]))

    if pairs:
        return pairs
    pair_count = min(len(source_row.cells), len(target_row.cells))
    return list(zip(source_row.cells[:pair_count], target_row.cells[:pair_count]))


def _filter_pairs_for_rule(
    rule: Rule,
    pairs: list[tuple[CellRef, CellRef]],
    source_header: RowRef | None,
    target_header: RowRef | None,
) -> list[tuple[CellRef, CellRef]]:
    if not rule.copy_header_contexts or not source_header or not target_header:
        return pairs

    allowed = {(left.lower(), label.lower()) for left, label in rule.copy_header_contexts}
    filtered: list[tuple[CellRef, CellRef]] = []
    for source_cell, target_cell in pairs:
        source_key = _cell_header_context(source_header, source_cell)
        if source_key in allowed:
            filtered.append((source_cell, target_cell))
    return filtered


def _targeted_pairs_for_rule(
    rule: Rule,
    source_row: RowRef,
    target_row: RowRef,
    source_header: RowRef | None,
    target_header: RowRef | None,
) -> list[tuple[CellRef, CellRef]]:
    if not rule.copy_header_contexts or not source_header or not target_header:
        return []

    allowed = [(left.lower(), label.lower()) for left, label in rule.copy_header_contexts]
    source_by_key: dict[tuple[str, str], list[CellRef]] = {}
    target_by_key: dict[tuple[str, str], list[CellRef]] = {}

    for cell in source_row.cells:
        key = _cell_header_context(source_header, cell)
        if key in allowed:
            source_by_key.setdefault(key, []).append(cell)

    for cell in target_row.cells:
        key = _cell_header_context(target_header, cell)
        if key in allowed:
            target_by_key.setdefault(key, []).append(cell)

    pairs: list[tuple[CellRef, CellRef]] = []
    for key in allowed:
        source_cells = source_by_key.get(key) or []
        target_cells = target_by_key.get(key) or []
        for source_cell, target_cell in zip(source_cells, target_cells):
            pairs.append((source_cell, target_cell))
    return pairs


def _column_pairs_by_header(
    source_html: str,
    target_html: str,
    source_row: RowRef,
    target_row: RowRef,
) -> list[tuple[CellRef, CellRef]]:
    logical_pairs = _column_pairs_by_logical_column(source_row, target_row)
    if len(logical_pairs) >= min(len(source_row.cells), len(target_row.cells)):
        return logical_pairs

    source_count = len(source_row.cells)
    target_count = len(target_row.cells)
    if source_count < 3 or target_count < 3:
        raise RuntimeError(
            f"Cell count too small to copy safely: source has {source_count}, "
            f"target has {target_count}"
        )

    source_header = _find_header_row(source_html, source_row.table_index, source_row.row_index)
    target_header = _find_header_row(target_html, target_row.table_index, target_row.row_index)

    if source_header and target_header:
        contextual_pairs = _column_pairs_by_header_context(source_header, target_header, source_row, target_row)
        if len(contextual_pairs) >= min(len(source_row.cells), len(target_row.cells)):
            return contextual_pairs

    used_source: set[int] = set()
    used_target: set[int] = set()
    mappings: list[tuple[int, int]] = []

    if source_header and target_header:
        target_by_label: dict[str, list[int]] = {}
        for idx, cell in enumerate(target_header.cells):
            label = _normalize_text(cell.text).lower()
            if label:
                target_by_label.setdefault(label, []).append(idx)

        for sidx, cell in enumerate(source_header.cells):
            label = _normalize_text(cell.text).lower()
            if not label:
                continue
            if sidx >= source_count:
                continue
            candidates = target_by_label.get(label) or []
            for tidx in candidates:
                if tidx >= target_count:
                    continue
                if tidx in used_target:
                    continue
                mappings.append((sidx, tidx))
                used_source.add(sidx)
                used_target.add(tidx)
                break

    # Keep key identifier columns aligned by position if still not mapped.
    for fixed in (0, 1):
        if fixed < source_count and fixed < target_count and fixed not in used_source and fixed not in used_target:
            mappings.append((fixed, fixed))
            used_source.add(fixed)
            used_target.add(fixed)

    # Fill remaining columns by positional order to maximize copied content.
    pair_count = min(source_count, target_count)
    for idx in range(pair_count):
        if idx in used_source or idx in used_target:
            continue
        mappings.append((idx, idx))
        used_source.add(idx)
        used_target.add(idx)

    return [(source_row.cells[sidx], target_row.cells[tidx]) for sidx, tidx in mappings]


def _row_second_cell(row: RowRef) -> str:
    if len(row.cells) < 2:
        return ""
    return _normalize_text(row.cells[1].text)


def _row_has_copy_content(row: RowRef) -> bool:
    return any(cell.inner_html.strip() for cell in row.cells[2:])


def _find_rows_by_second_cell(storage_html: str, rule: Rule, *, source: bool) -> dict[str, RowRef]:
    matches = [row for row in _parse_rows(storage_html) if _matches_rule(row, rule)]
    by_label: dict[str, list[RowRef]] = {label: [] for label in rule.second_cell_values}
    for row in matches:
        row_label = _row_second_cell(row)
        for label in rule.second_cell_values:
            if row_label.lower() == label.lower():
                by_label[label].append(row)

    selected: dict[str, RowRef] = {}
    for label, rows in by_label.items():
        if not rows:
            raise RuntimeError(f"Rule {rule.key} found no row for second cell {label!r}")
        if source:
            rows_with_content = [row for row in rows if _row_has_copy_content(row)]
            selected[label] = rows_with_content[0] if rows_with_content else rows[0]
        else:
            selected[label] = rows[0]
    return selected


def _find_all_rows_by_second_cell(storage_html: str, rule: Rule) -> dict[str, list[RowRef]]:
    matches = [row for row in _parse_rows(storage_html) if _matches_rule(row, rule)]
    by_label: dict[str, list[RowRef]] = {label: [] for label in rule.second_cell_values}
    for row in matches:
        row_label = _row_second_cell(row)
        for label in rule.second_cell_values:
            if row_label.lower() == label.lower():
                by_label[label].append(row)

    for label, rows in by_label.items():
        if not rows:
            raise RuntimeError(f"Rule {rule.key} found no row for second cell {label!r}")
    return by_label


def _copy_row_cells(
    target_html: str,
    source_row: RowRef,
    target_row: RowRef,
    *,
    rule: Rule | None = None,
    source_storage_html: str | None = None,
    target_storage_html: str | None = None,
) -> tuple[str, bool]:
    source_count = len(source_row.cells)
    target_count = len(target_row.cells)
    if source_count == target_count:
        pairs = list(zip(source_row.cells, target_row.cells))
    elif source_storage_html and target_storage_html:
        # Prefer header-name alignment when table schemas drift across weeks.
        pairs = _column_pairs_by_header(source_storage_html, target_storage_html, source_row, target_row)
    else:
        pair_count = min(source_count, target_count)
        pairs = list(zip(source_row.cells[:pair_count], target_row.cells[:pair_count]))
    if rule and source_storage_html and target_storage_html:
        source_header = _find_header_row(source_storage_html, source_row.table_index, source_row.row_index)
        target_header = _find_header_row(target_storage_html, target_row.table_index, target_row.row_index)
        targeted_pairs = _targeted_pairs_for_rule(rule, source_row, target_row, source_header, target_header)
        if targeted_pairs:
            pairs = targeted_pairs
        else:
            pairs = _filter_pairs_for_rule(rule, pairs, source_header, target_header)

    changed = any(source.inner_html != target.inner_html for source, target in pairs)
    if not changed:
        return target_html, False

    updated = target_html
    for source, target in reversed(pairs):
        updated = updated[: target.inner_start] + source.inner_html + updated[target.inner_end :]
    return updated, True


def _copy_labeled_rows(
    target_html: str,
    source_rows: dict[str, RowRef],
    target_rows: dict[str, RowRef],
    *,
    rule: Rule | None = None,
    source_storage_html: str | None = None,
    target_storage_html: str | None = None,
) -> tuple[str, bool]:
    updated = target_html
    changed_any = False
    for label in reversed(list(source_rows.keys())):
        updated, changed = _copy_row_cells(
            updated,
            source_rows[label],
            target_rows[label],
            rule=rule,
            source_storage_html=source_storage_html,
            target_storage_html=target_storage_html,
        )
        changed_any = changed_any or changed
    return updated, changed_any


def _copy_labeled_rows_by_occurrence(
    target_html: str,
    source_rows: dict[str, list[RowRef]],
    target_rows: dict[str, list[RowRef]],
    *,
    rule: Rule | None = None,
    source_storage_html: str | None = None,
    target_storage_html: str | None = None,
) -> tuple[str, bool]:
    replacements: list[tuple[CellRef, CellRef]] = []
    changed_any = False
    source_header = None
    target_header = None
    if rule and source_storage_html and target_storage_html:
        sample_source_rows = next(iter(source_rows.values()), [])
        sample_target_rows = next(iter(target_rows.values()), [])
        if sample_source_rows and sample_target_rows:
            source_header = _find_header_row(source_storage_html, sample_source_rows[0].table_index, sample_source_rows[0].row_index)
            target_header = _find_header_row(target_storage_html, sample_target_rows[0].table_index, sample_target_rows[0].row_index)

    for label, rows in source_rows.items():
        if len(rows) != len(target_rows[label]):
            raise RuntimeError(
                f"Row count mismatch for {label}: source has {len(rows)}, "
                f"target has {len(target_rows[label])}"
            )
        for source_row, target_row in zip(rows, target_rows[label]):
            if source_storage_html and target_storage_html:
                row_pairs = _column_pairs_by_header(source_storage_html, target_storage_html, source_row, target_row)
            else:
                pair_count = min(len(source_row.cells), len(target_row.cells))
                row_pairs = list(zip(source_row.cells[:pair_count], target_row.cells[:pair_count]))
            if rule:
                targeted_pairs = _targeted_pairs_for_rule(rule, source_row, target_row, source_header, target_header)
                row_pairs = targeted_pairs if targeted_pairs else _filter_pairs_for_rule(rule, row_pairs, source_header, target_header)
            for source_cell, target_cell in row_pairs:
                replacements.append((source_cell, target_cell))
                changed_any = changed_any or source_cell.inner_html != target_cell.inner_html

    if not changed_any:
        return target_html, False

    updated = target_html
    for source_cell, target_cell in sorted(replacements, key=lambda pair: pair[1].inner_start, reverse=True):
        updated = updated[: target_cell.inner_start] + source_cell.inner_html + updated[target_cell.inner_end :]
    return updated, True


def _update_page(session: requests.Session, page: dict[str, Any], new_html: str, message: str) -> None:
    page_id = str(page["id"])
    payload = {
        "id": page_id,
        "type": page.get("type") or "page",
        "title": page["title"],
        "space": {"key": ((page.get("space") or {}).get("key"))},
        "body": {"storage": {"value": new_html, "representation": "storage"}},
        "version": {
            "number": int((page.get("version") or {}).get("number") or 1) + 1,
            "message": message,
        },
    }
    _request_json(session, "PUT", f"/rest/api/content/{page_id}", payload=payload)


def _state_key(rule: Rule) -> str:
    return rule.key


def _mark_processed(state: dict[str, Any], rule: Rule, page: WeeklyPage) -> None:
    rules = state.setdefault("rules", {})
    rules[_state_key(rule)] = {
        "last_processed_week": page.week,
        "last_page_id": page.page_id,
        "last_page_title": page.title,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _process_rule(
    session: requests.Session,
    rule: Rule,
    state: dict[str, Any],
    *,
    apply: bool,
    init_state: bool,
) -> bool:
    pages = _find_weekly_pages(session, rule)
    if not pages:
        print(f"[{rule.key}] no weekly pages found")
        return False

    latest = pages[-1]
    page_by_week = {page.week: page for page in pages}
    saved = (state.get("rules") or {}).get(_state_key(rule)) or {}
    last_processed_week = int(saved.get("last_processed_week") or 0)
    print(
        f"[{rule.key}] latest={latest.title} ({latest.page_id}), "
        f"last_processed=CW{last_processed_week or 'none'}"
    )

    if init_state and not last_processed_week:
        _mark_processed(state, rule, latest)
        print(f"[{rule.key}] initialized state at {latest.title}")
        return True

    if not last_processed_week:
        if apply:
            _mark_processed(state, rule, latest)
            print(f"[{rule.key}] state missing; initialized at {latest.title}")
            return True
        print(f"[{rule.key}] state missing; run with --init-state once before applying")
        return False

    changed_state = False
    pending = [page for page in pages if page.week > last_processed_week]
    if not pending:
        print(f"[{rule.key}] no new weekly page")
        return False

    for target_page_info in pending:
        source_page_info = page_by_week.get(target_page_info.week - 1)
        if not source_page_info:
            print(f"[{rule.key}] skip {target_page_info.title}: missing previous CW{target_page_info.week - 1}")
            continue

        source_page = _fetch_page(session, source_page_info.page_id)
        target_page = _fetch_page(session, target_page_info.page_id)
        source_html = _storage_html(source_page)
        target_html = _storage_html(target_page)
        if rule.second_cell_values:
            if rule.copy_all_by_occurrence:
                all_source_rows = _find_all_rows_by_second_cell(source_html, rule)
                all_target_rows = _find_all_rows_by_second_cell(target_html, rule)
                new_html, changed = _copy_labeled_rows_by_occurrence(
                    target_html,
                    all_source_rows,
                    all_target_rows,
                    rule=rule,
                    source_storage_html=source_html,
                    target_storage_html=target_html,
                )
                for label in rule.second_cell_values:
                    for index, (source_row, target_row) in enumerate(zip(all_source_rows[label], all_target_rows[label]), 1):
                        print(
                            f"[{rule.key}] {label} #{index}: {source_page_info.title} table {source_row.table_index} row {source_row.row_index} "
                            f"-> {target_page_info.title} table {target_row.table_index} row {target_row.row_index}"
                        )
            else:
                source_rows = _find_rows_by_second_cell(source_html, rule, source=True)
                target_rows = _find_rows_by_second_cell(target_html, rule, source=False)
                new_html, changed = _copy_labeled_rows(
                    target_html,
                    source_rows,
                    target_rows,
                    rule=rule,
                    source_storage_html=source_html,
                    target_storage_html=target_html,
                )
                for label in rule.second_cell_values:
                    source_row = source_rows[label]
                    target_row = target_rows[label]
                    print(
                        f"[{rule.key}] {label}: {source_page_info.title} table {source_row.table_index} row {source_row.row_index} "
                        f"-> {target_page_info.title} table {target_row.table_index} row {target_row.row_index}"
                    )
            print(f"[{rule.key}] {'would update' if changed else 'already same'}")
        else:
            source_row = _find_target_row(source_html, rule)
            target_row = _find_target_row(target_html, rule)
            new_html, changed = _copy_row_cells(
                target_html,
                source_row,
                target_row,
                rule=rule,
                source_storage_html=source_html,
                target_storage_html=target_html,
            )
            print(
                f"[{rule.key}] {source_page_info.title} table {source_row.table_index} row {source_row.row_index} "
                f"-> {target_page_info.title} table {target_row.table_index} row {target_row.row_index}: "
                f"{'would update' if changed else 'already same'}"
            )
        if apply:
            if changed:
                _update_page(
                    session,
                    target_page,
                    new_html,
                    f"Copy weekly test row from {source_page_info.title}",
                )
                print(f"[{rule.key}] updated {target_page_info.title}")
            _mark_processed(state, rule, target_page_info)
            changed_state = True
    return changed_state


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy selected Confluence weekly rows into newly created child pages.")
    parser.add_argument("--base-url", default=os.environ.get("ATC_CONFLUENCE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--only", choices=[rule.key for rule in RULES], action="append")
    parser.add_argument("--apply", action="store_true", help="Write Confluence updates and advance state.")
    parser.add_argument("--init-state", action="store_true", help="Record current latest pages as already processed.")
    args = parser.parse_args()

    selected_rules = [rule for rule in RULES if not args.only or rule.key in args.only]
    state = _load_state(args.state_file)
    session = _session(args.base_url)
    changed_state = False

    print("mode=" + ("apply" if args.apply else "dry-run"))
    for rule in selected_rules:
        changed_state = (
            _process_rule(session, rule, state, apply=args.apply, init_state=args.init_state)
            or changed_state
        )

    if args.init_state or (args.apply and changed_state):
        _save_state(args.state_file, state)
        print(f"state_saved={args.state_file}")
    elif not args.apply:
        print("dry_run_no_remote_changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())