# Daily Report Hub

一个本地使用的日报工具，基于 Streamlit 构建。

## 功能

- 填写今日日报内容
- 自动生成优化后的 Markdown 日报
- 自动提炼关键进展、风险等级、管理视角和明日建议
- 本地保存日报历史
- 按日期和人员查看历史记录
- 导出 Markdown

## 启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

如果默认端口被占用，可以显式指定端口：

```bash
streamlit run app.py --server.port 8502
```

## Jira 自动清理脚本

仓库中新增了一个独立脚本 `jira_target_end_cleaner.py`，用于持续轮询 Jira。

脚本行为：

- 启动时先记录当前 filter 命中的 issue，不做清理
- 后续如果有 issue 新进入该 filter，则自动把 `Target end` 字段清空
- 状态保存在 `data/jira_target_end_state.json`，避免重复处理

需要的环境变量：

```bash
export JIRA_BASE_URL="https://your-company.atlassian.net"
export JIRA_USER_EMAIL="you@example.com"
export JIRA_API_TOKEN="your-api-token"
```

也可以直接在项目根目录放一个 `.env` 文件，内容例如：

```bash
JIRA_BASE_URL="https://your-company.atlassian.net"
JIRA_USER_EMAIL="you@example.com"
JIRA_API_TOKEN="your-api-token"
```

可选环境变量：

```bash
export JIRA_MATCH_JQL='project = IDCEVODEV AND issuetype in (Bug, "TAEE Defect") AND (component = "CN VoD" OR team = 5154) AND status in (Open, New) AND "Target end" is not EMPTY AND resolution = Unresolved AND reporter = shiminglelipartner'
export TARGET_END_FIELD_NAME='Target end'
export TARGET_END_FIELD_ID='customfield_12345'
export POLL_INTERVAL_SECONDS='3600'
export ALIGN_TO_HOUR='true'
export TARGET_END_STATE_FILE='data/jira_target_end_state.json'
export DRY_RUN='false'
```

运行方式：

```bash
python3 jira_target_end_cleaner.py
```

默认行为：

- 默认使用你指定的那条 filter
- 首次启动只建立基线，不清当前已存在的票
- 从下一次整点开始，如果有新票进入 filter，就清空该票的 `Target end`

如果你已经知道 `Target end` 的字段 ID，建议直接设置 `TARGET_END_FIELD_ID`，这样可以避免字段名解析歧义。
