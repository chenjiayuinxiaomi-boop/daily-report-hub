from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def _call_api(prompt: str, api_key: str, base_url: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 800,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"].strip()


def rewrite_with_llm(
    items: list[str],
    category: str,
    api_key: str,
    base_url: str,
    model: str,
) -> tuple[list[str], str | None]:
    """把口语条目改写成正式日报语言。返回 (改写后列表, 错误信息)。"""
    if not items or not api_key.strip():
        return items, None

    numbered = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))
    prompt = (
        f"将下列「{category}」条目改写为正式、简洁的工作日报语言。\n"
        "要求：保持原意，去口语化，结果导向，每条独立输出，"
        "格式严格为「序号. 内容」，不要有多余说明。\n\n"
        f"{numbered}"
    )
    try:
        raw = _call_api(prompt, api_key, base_url, model)
        result: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line[0].isdigit() and ". " in line:
                result.append(line.split(". ", 1)[1].strip())
            else:
                result.append(line)
        if len(result) == len(items):
            return result, None
        return items, "AI 返回条数不匹配，已保留原始输入"
    except urllib.error.HTTPError as e:
        return items, f"API 错误 {e.code}"
    except Exception as e:
        return items, f"调用失败: {e}"


def generate_leader_summary_llm(
    payload: dict[str, Any],
    api_key: str,
    base_url: str,
    model: str,
) -> tuple[str, str | None]:
    """用 LLM 生成面向领导的精简摘要。返回 (摘要, 错误信息)。"""
    if not api_key.strip():
        return "", None

    completed = "、".join(payload.get("completed", [])) or "无"
    in_progress = "、".join(payload.get("in_progress", [])) or "无"
    blockers = "、".join(payload.get("blockers", [])) or "无"
    tomorrow = "、".join(payload.get("tomorrow", [])) or "无"

    prompt = (
        "你是专业项目经理助手，根据以下日报生成面向领导的精简摘要，不超过3句话，"
        "突出核心产出、阻塞和明日优先级，语气专业简洁，直接输出内容无需标题。\n\n"
        f"今日完成：{completed}\n进行中：{in_progress}\n阻塞项：{blockers}\n明日计划：{tomorrow}"
    )
    try:
        return _call_api(prompt, api_key, base_url, model), None
    except Exception as e:
        return "", f"AI 摘要失败: {e}"
