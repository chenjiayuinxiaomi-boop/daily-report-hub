from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

# ── 口语 → 正式表达替换规则 ───────────────────────────────────────────
FORMALIZE_RULES: list[tuple[str, str]] = [
    ("搞定了", "已完成"),
    ("搞了", "处理了"),
    ("弄了", "完成了"),
    ("搞一下", "处理"),
    ("弄一下", "处理"),
    ("跑一下", "执行"),
    ("看看", "排查"),
    ("查了查", "排查分析"),
    ("试了试", "验证"),
    ("改了改", "迭代优化"),
    ("想了想", "评估"),
    ("和xx", "与相关方"),
    ("跑通了", "完成端到端验证"),
    ("没搞定", "未完成"),
    ("卡了", "受阻"),
    ("搞不定", "存在阻碍"),
    ("差不多", "基本"),
    ("可能", "预计"),
    ("大概", "预计"),
    ("然后", "，随后"),
    ("因为", "原因："),
]

RISK_KEYWORDS = (
    "阻塞",
    "block",
    "卡住",
    "失败",
    "异常",
    "等待",
    "依赖",
    "风险",
    "问题",
    "bug",
    "报错",
)

DELIVERY_KEYWORDS = (
    "完成",
    "上线",
    "交付",
    "发布",
    "修复",
    "优化",
    "联调",
    "支持",
)

COLLABORATION_KEYWORDS = (
    "协作",
    "联调",
    "确认",
    "对齐",
    "沟通",
    "评审",
    "依赖",
    "等待",
)


def formalize_text(text: str) -> str:
    """把口语表达替换为正式日报用语，不改变原意。"""
    result = text
    for informal, formal in FORMALIZE_RULES:
        result = result.replace(informal, formal)
    return result


def formalize_items(items: list[str]) -> list[str]:
    return [formalize_text(item) for item in items]


def contains_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def split_lines(raw_text: str) -> list[str]:
    items: list[str] = []
    for line in raw_text.splitlines():
        cleaned = line.strip().lstrip("-*").strip()
        if cleaned:
            items.append(cleaned)
    return items


def to_bullets(items: list[str]) -> str:
    if not items:
        return "- 无"
    return "\n".join(f"- {item}" for item in items)


def build_summary_sentence(payload: dict[str, Any]) -> str:
    completed_count = len(payload["completed"])
    in_progress_count = len(payload["in_progress"])
    blocker_count = len(payload["blockers"])

    if completed_count and not blocker_count:
        return f"今日已完成 {completed_count} 项事项，当前推进稳定，剩余 {in_progress_count} 项在持续跟进。"
    if completed_count and blocker_count:
        return f"今日完成 {completed_count} 项事项，但存在 {blocker_count} 个阻塞点，需要尽快清理依赖避免影响后续交付。"
    if in_progress_count and not completed_count:
        return f"今日以推进中事项为主，共跟进 {in_progress_count} 项，建议尽快形成可验收输出。"
    return "今日日报以状态同步为主，建议补充更明确的产出或下一步里程碑。"


def build_risk_level(payload: dict[str, Any]) -> str:
    blockers = payload["blockers"]
    in_progress = payload["in_progress"]
    completed = payload["completed"]

    if len(blockers) >= 2:
        return "高"
    if blockers:
        return "中"
    if len(in_progress) > len(completed) and in_progress:
        return "中"
    return "低"


def build_key_progress(payload: dict[str, Any]) -> list[str]:
    completed = payload["completed"]
    in_progress = payload["in_progress"]

    progress: list[str] = []
    if completed:
        progress.append(f"已落地产出 {len(completed)} 项，交付重心集中在：{completed[0]}")
    if len(completed) > 1:
        progress.append(f"补充完成事项包括：{completed[1]}")
    if in_progress:
        progress.append(f"当前主要推进项是：{in_progress[0]}")
    if not progress:
        progress.append("当前缺少明确完成项，建议补充可验证结果。")
    return progress


def build_risk_points(payload: dict[str, Any]) -> list[str]:
    blockers = payload["blockers"]
    in_progress = payload["in_progress"]
    risks: list[str] = []

    for item in blockers:
        risks.append(f"阻塞项需要处理：{item}")

    if not blockers and any(contains_keywords(item, RISK_KEYWORDS) for item in in_progress):
        risks.append("进行中事项中已出现风险信号，建议提前拆解依赖并明确处理人。")

    if len(in_progress) >= 3 and not blockers:
        risks.append("进行中事项偏多，存在任务并行过高导致交付分散的风险。")

    if not risks:
        risks.append("当前未识别到显性阻塞，建议保持节奏并持续关注验收节点。")

    return risks


def build_tomorrow_focus(payload: dict[str, Any]) -> list[str]:
    tomorrow = payload["tomorrow"]
    blockers = payload["blockers"]
    focus: list[str] = []

    if blockers:
        focus.append("优先清理阻塞项，再推进新增工作，避免明日计划继续堆积。")
    if tomorrow:
        focus.append(f"明日第一优先级建议聚焦：{tomorrow[0]}")
    if len(tomorrow) > 1:
        focus.append("建议将明日计划按先验收、后优化排序，保证至少 1 项形成闭环。")
    if not focus:
        focus.append("建议补充明确的明日目标，最好能写成可交付或可验收结果。")

    return focus


def build_management_insights(payload: dict[str, Any]) -> list[str]:
    completed = payload["completed"]
    in_progress = payload["in_progress"]
    blockers = payload["blockers"]
    notes = payload["notes"]
    insights: list[str] = []

    delivery_count = sum(1 for item in completed if contains_keywords(item, DELIVERY_KEYWORDS))
    collaboration_count = sum(
        1
        for item in [*completed, *in_progress, *blockers, notes]
        if isinstance(item, str) and contains_keywords(item, COLLABORATION_KEYWORDS)
    )

    insights.append(f"交付表现：今日完成 {len(completed)} 项，交付型事项 {delivery_count} 项。")
    insights.append(f"推进负载：进行中 {len(in_progress)} 项，阻塞 {len(blockers)} 项。")
    if collaboration_count:
        insights.append("协同信号：内容中出现跨人协作或依赖信息，建议跟进责任人与时间点。")
    else:
        insights.append("协同信号：未识别到明显外部依赖，当前更适合按个人节奏推进闭环。")

    return insights


def build_leadership_questions(payload: dict[str, Any]) -> list[str]:
    completed = payload["completed"]
    in_progress = payload["in_progress"]
    blockers = payload["blockers"]
    tomorrow = payload["tomorrow"]
    questions: list[str] = []

    if completed:
        questions.append(f"今天最有价值的产出具体是什么，如何证明“{completed[0]}”已经形成结果？")
    else:
        questions.append("今天没有明确完成项，实际产出是什么，为什么还没有形成闭环？")

    if blockers:
        questions.append(f"阻塞项“{blockers[0]}”是谁在卡，预计何时解除，需要我协调什么？")
    elif in_progress:
        questions.append(f"进行中事项“{in_progress[0]}”距离完成还差哪一步，最晚何时能验收？")

    if len(in_progress) >= 2:
        questions.append("当前并行事项较多，哪一项是第一优先级，哪些可以延后？")

    if tomorrow:
        questions.append(f"明日计划里的“{tomorrow[0]}”完成标准是什么，是否会影响本周节奏？")

    if not questions:
        questions.append("明天最应该盯的单一目标是什么，完成后带来的业务价值是什么？")

    return questions


def build_escalation_blockers(blockers: list[str], in_progress: list[str]) -> list[str]:
    """识别需要上升处理的 blocker：有外部依赖或持续多项阻塞的情况。"""
    escalation: list[str] = []
    for item in blockers:
        if contains_keywords(item, ("等待", "依赖", "确认", "审批", "资源")):
            escalation.append(f"【需上升】{item}")
        else:
            escalation.append(f"【自内消化】{item}")
    return escalation


def build_leader_report(payload: dict[str, Any]) -> str:
    """生成适合发给领导的精简版日报，严格控制在 5 行以内。"""
    analysis = payload["analysis"]
    completed = payload["completed"]
    blockers = payload["blockers"]
    tomorrow = payload["tomorrow"]

    lines: list[str] = []

    # 一句话总结今日产出
    if completed:
        top = formalize_text(completed[0])
        suffix = f"等 {len(completed)} 项" if len(completed) > 1 else ""
        lines.append(f"【今日】完成{top}{suffix}。")
    else:
        lines.append("【今日】以推进为主，暂无完结项。")

    # 阻塞 / 需上升
    if blockers:
        escalation_items = build_escalation_blockers(blockers, payload["in_progress"])
        need_escalate = [i for i in escalation_items if "需上升" in i]
        if need_escalate:
            clean = need_escalate[0].replace("【需上升】", "")
            lines.append(f"【阻塞】{clean}，需协调资源支持。")
        else:
            lines.append(f"【阻塞】{blockers[0]}，当前自行跟进中。")

    # 风险提示
    risk = analysis["risk_level"]
    if risk in ("高", "中"):
        lines.append(f"【风险】等级{risk}，{analysis['risk_points'][0]}")

    # 明日计划
    if tomorrow:
        lines.append(f"【明日】优先推进：{formalize_text(tomorrow[0])}。")

    return "\n".join(lines)


def build_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": build_summary_sentence(payload),
        "risk_level": build_risk_level(payload),
        "key_progress": build_key_progress(payload),
        "risk_points": build_risk_points(payload),
        "tomorrow_focus": build_tomorrow_focus(payload),
        "management_insights": build_management_insights(payload),
        "leadership_questions": build_leadership_questions(payload),
        "escalation_blockers": build_escalation_blockers(
            payload["blockers"], payload["in_progress"]
        ),
    }


def build_markdown(payload: dict[str, Any]) -> str:
    report_date = payload["report_date"]
    author = payload["author"]
    completed = to_bullets(payload["completed"])
    in_progress = to_bullets(payload["in_progress"])
    blockers = to_bullets(payload["blockers"])
    tomorrow = to_bullets(payload["tomorrow"])
    notes = payload["notes"].strip() or "无"
    analysis = payload["analysis"]
    summary = analysis["summary"]
    risk_level = analysis["risk_level"]
    key_progress = to_bullets(analysis["key_progress"])
    risk_points = to_bullets(analysis["risk_points"])
    tomorrow_focus = to_bullets(analysis["tomorrow_focus"])
    leader_report = payload.get("leader_report", "")

    return f"""# 日报 - {report_date} - {author}

## 今日摘要
{summary}  风险等级：{risk_level}

## 精简版（适合发给领导）
{leader_report}

---

## 今日完成
{completed}

## 进行中
{in_progress}

## 阻塞项
{blockers}

## 明日计划
{tomorrow}

## 关键进展提炼
{key_progress}

## 风险与阻塞分析
{risk_points}

## 明日建议动作
{tomorrow_focus}

## 备注
{notes}
""".strip()


def build_report_payload(
    report_date: date,
    author: str,
    completed_raw: str,
    in_progress_raw: str,
    blockers_raw: str,
    tomorrow_raw: str,
    notes: str,
) -> dict[str, Any]:
    completed_raw_items = split_lines(completed_raw)
    in_progress_raw_items = split_lines(in_progress_raw)
    blockers_raw_items = split_lines(blockers_raw)
    tomorrow_raw_items = split_lines(tomorrow_raw)

    payload = {
        "id": str(uuid4()),
        "report_date": report_date.isoformat(),
        "author": author.strip(),
        # 原始口语输入，用于「优化前」对比展示
        "completed_raw": completed_raw_items,
        "in_progress_raw": in_progress_raw_items,
        "blockers_raw": blockers_raw_items,
        "tomorrow_raw": tomorrow_raw_items,
        # 正式化改写后版本，用于日报输出
        "completed": formalize_items(completed_raw_items),
        "in_progress": formalize_items(in_progress_raw_items),
        "blockers": formalize_items(blockers_raw_items),
        "tomorrow": formalize_items(tomorrow_raw_items),
        "notes": notes.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    payload["analysis"] = build_analysis(payload)
    payload["leader_report"] = build_leader_report(payload)

    return payload
