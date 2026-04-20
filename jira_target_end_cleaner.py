"""
整点自动清除 Jira Target end 字段
改这里三行就能跑：
"""
JIRA_BASE_URL   = "https://your-company.atlassian.net"
JIRA_USER_EMAIL = "you@example.com"
JIRA_API_TOKEN  = "your-api-token"

import time
from datetime import datetime, timedelta

import requests
from requests.auth import HTTPBasicAuth

JQL = (
    'project = IDCEVODEV AND issuetype in (Bug, "TAEE Defect") '
    'AND (component = "CN VoD" OR team = 5154) '
    'AND status in (Open, New) '
    'AND "Target end" is not EMPTY '
    'AND resolution = Unresolved '
    'AND reporter = shiminglelipartner'
)

auth = HTTPBasicAuth(JIRA_USER_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json", "Content-Type": "application/json"}


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def get_target_end_field_id():
    resp = requests.get(f"{JIRA_BASE_URL}/rest/api/2/field", auth=auth, headers=headers, timeout=30)
    resp.raise_for_status()
    for field in resp.json():
        if field.get("name", "").lower() == "target end":
            return field["id"]
    raise RuntimeError("找不到 'Target end' 字段，请确认字段名是否正确")


def search_issues(field_id):
    issues, start = [], 0
    while True:
        resp = requests.post(
            f"{JIRA_BASE_URL}/rest/api/2/search",
            auth=auth, headers=headers, timeout=30,
            json={"jql": JQL, "startAt": start, "maxResults": 100, "fields": [field_id]},
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("issues", [])
        issues.extend(batch)
        start += len(batch)
        if start >= data.get("total", 0) or not batch:
            break
    return issues


def clear_target_end(issue_key, field_id):
    resp = requests.put(
        f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}",
        auth=auth, headers=headers, timeout=30,
        json={"fields": {field_id: None}},
    )
    resp.raise_for_status()
    log(f"已清除 {issue_key} 的 Target end")


def run_once(field_id):
    issues = search_issues(field_id)
    if not issues:
        log("当前 filter 下没有匹配的票")
        return
    for issue in issues:
        try:
            clear_target_end(issue["key"], field_id)
        except Exception as e:
            log(f"处理 {issue['key']} 失败：{e}")


def seconds_until_next_hour():
    now = datetime.now()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(1, int((next_hour - now).total_seconds()))


if __name__ == "__main__":
    log("启动，每个整点自动清除 Target end")
    field_id = get_target_end_field_id()
    log(f"Target end 字段 ID：{field_id}")
    while True:
        run_once(field_id)
        sleep = seconds_until_next_hour()
        log(f"下次检查在 {datetime.now() + timedelta(seconds=sleep):%H:%M}，等待 {sleep//60} 分钟")
        time.sleep(sleep)