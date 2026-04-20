from __future__ import annotations

import json
import urllib.error
import urllib.request


def _post(url: str, payload: dict) -> tuple[bool, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
        result = json.loads(body)
        # 企业微信: errcode=0；飞书: StatusCode=0 或 code=0
        if (
            result.get("errcode") == 0
            or result.get("StatusCode") == 0
            or result.get("code") == 0
        ):
            return True, "发送成功"
        return False, f"接口返回：{body[:200]}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, str(e)


def send_weixin(webhook_url: str, content: str) -> tuple[bool, str]:
    """发送 Markdown 消息到企业微信群机器人。"""
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content[:4096]},
    }
    return _post(webhook_url, payload)


def send_feishu(webhook_url: str, content: str) -> tuple[bool, str]:
    """发送卡片消息到飞书群机器人。"""
    payload = {
        "msg_type": "interactive",
        "card": {
            "elements": [
                {"tag": "div", "text": {"content": content, "tag": "lark_md"}}
            ],
            "header": {
                "title": {"content": "日报通知", "tag": "plain_text"},
                "template": "blue",
            },
        },
    }
    return _post(webhook_url, payload)
