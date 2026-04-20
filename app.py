from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from report_service import (
    build_analysis,
    build_leader_report,
    build_markdown,
    build_report_payload,
)
from storage import append_report, load_reports
from weekly_service import build_weekly_markdown, build_weekly_summary
from llm_service import generate_leader_summary_llm, rewrite_with_llm
from notifier import send_feishu, send_weixin


def format_items_for_display(items: list[str]) -> str:
    if not items:
        return "- 无"
    return "\n".join(f"- {item}" for item in items)


def build_original_view(payload: dict[str, object]) -> str:
    completed = format_items_for_display(payload["completed"])
    in_progress = format_items_for_display(payload["in_progress"])
    blockers = format_items_for_display(payload["blockers"])
    tomorrow = format_items_for_display(payload["tomorrow"])
    notes = str(payload["notes"]).strip() or "无"

    return f"""## 今日完成
{completed}

## 进行中
{in_progress}

## 阻塞项
{blockers}

## 明日计划
{tomorrow}

## 备注
{notes}
""".strip()


def _get_secret(section: str, key: str, default: str = "") -> str:
    try:
        return str(st.secrets[section][key])
    except Exception:
        return default


st.set_page_config(
    page_title="Daily Report Hub",
    page_icon="📝",
    layout="wide",
)

st.title("Daily Report Hub")
st.caption("本地日报录入、生成与历史查看")

if "last_markdown" not in st.session_state:
    st.session_state["last_markdown"] = ""
if "last_payload" not in st.session_state:
    st.session_state["last_payload"] = None

reports = load_reports()

overview_col, stats_col = st.columns([2, 1])
with overview_col:
    st.subheader("概览")
    st.write("用于维护每日工作完成、进行中事项、阻塞项与明日计划。")
with stats_col:
    st.metric("累计日报", len(reports))

# ── 侧边栏配置 ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("个人设置")
    saved_author = st.session_state.get("author_name", "")
    sidebar_author = st.text_input("你的名字（自动填入日报）", value=saved_author, key="sidebar_author")
    if sidebar_author:
        st.session_state["author_name"] = sidebar_author

    st.divider()
    st.subheader("AI 改写")
    _key_from_secret = _get_secret("llm", "api_key")
    if _key_from_secret:
        llm_api_key: str = _key_from_secret
        llm_base_url: str = _get_secret("llm", "base_url", "https://api.openai.com/v1")
        llm_model: str = _get_secret("llm", "model", "gpt-4o-mini")
        st.success("AI 改写已就绪（后台配置）")
    else:
        llm_api_key = st.text_input("API Key", type="password", key="llm_api_key")
        llm_base_url = st.text_input("Base URL", value="https://api.openai.com/v1", key="llm_base_url")
        llm_model = st.text_input("Model", value="gpt-4o-mini", key="llm_model")
        if llm_api_key:
            st.success("AI 改写已就绪")
        else:
            st.caption("填入 API Key 后可启用 AI 改写")

    st.divider()
    st.subheader("发送通知")
    _wx_secret = _get_secret("weixin", "webhook_url")
    _fs_secret = _get_secret("feishu", "webhook_url")
    weixin_webhook: str = _wx_secret or st.text_input("企业微信 Webhook URL", key="weixin_webhook")
    feishu_webhook: str = _fs_secret or st.text_input("飞书 Webhook URL", key="feishu_webhook")
    if _wx_secret or _fs_secret:
        st.success("通知渠道已配置（后台配置）")

input_tab, preview_tab, history_tab, weekly_tab = st.tabs(["填写日报", "生成预览", "历史记录", "周报汇总"])
with input_tab:
    with st.form("daily_report_form"):
        left_col, right_col = st.columns(2)
        with left_col:
            report_date = st.date_input("日期", value=date.today())
            author = st.text_input("姓名", value=st.session_state.get("author_name", ""), placeholder="例如：Hope")
            completed_raw = st.text_area(
                "今日完成",
                placeholder="每行一项，例如：\n完成日报工具首页原型\n联调本地数据存储",
                height=180,
            )
            tomorrow_raw = st.text_area(
                "明日计划",
                placeholder="每行一项",
                height=180,
            )
        with right_col:
            in_progress_raw = st.text_area(
                "进行中",
                placeholder="每行一项",
                height=180,
            )
            blockers_raw = st.text_area(
                "阻塞项",
                placeholder="每行一项，没有可留空",
                height=180,
            )
            notes = st.text_area(
                "备注",
                placeholder="补充说明、风险、协作事项",
                height=180,
            )

        use_ai = st.checkbox(
            "使用 AI 改写",
            value=False,
            help="需在侧边栏配置 API Key",
            disabled=not bool(llm_api_key),
        )
        submitted = st.form_submit_button("生成日报", use_container_width=True)

    if submitted:
        if not author.strip():
            st.error("姓名不能为空。")
        else:
            payload = build_report_payload(
                report_date=report_date,
                author=author,
                completed_raw=completed_raw,
                in_progress_raw=in_progress_raw,
                blockers_raw=blockers_raw,
                tomorrow_raw=tomorrow_raw,
                notes=notes,
            )
            if use_ai and llm_api_key:
                with st.spinner("AI 改写中，请稍候..."):
                    for category, field in [
                        ("今日完成", "completed"),
                        ("进行中", "in_progress"),
                        ("阻塞项", "blockers"),
                        ("明日计划", "tomorrow"),
                    ]:
                        rewritten, err = rewrite_with_llm(
                            payload[field], category, llm_api_key, llm_base_url, llm_model
                        )
                        if err:
                            st.warning(f"{category}: {err}")
                        payload[field] = rewritten
                    payload["analysis"] = build_analysis(payload)
                    payload["leader_report"] = build_leader_report(payload)
                    ai_summary, ai_err = generate_leader_summary_llm(
                        payload, llm_api_key, llm_base_url, llm_model
                    )
                    if ai_summary:
                        payload["ai_summary"] = ai_summary
                    if ai_err:
                        st.warning(ai_err)
            markdown = build_markdown(payload)
            st.session_state["last_payload"] = payload
            st.session_state["last_markdown"] = markdown
            st.success("日报已生成，请到【生成预览】页查看或保存。")

with preview_tab:
    st.subheader("生成概览")
    markdown = st.session_state.get("last_markdown", "")
    payload = st.session_state.get("last_payload")

    if not markdown or not payload:
        st.info("先在【填写日报】页生成内容。")
    else:
        analysis = payload["analysis"]
        original_view = build_original_view(payload)

        st.info(
            f"核心结论：{analysis['summary']} 风险等级：{analysis['risk_level']}。"
        )

        before_col, after_col, question_col = st.columns([1.1, 1.3, 1.0])

        with before_col:
            st.markdown("### 优化前（原始输入）")
            st.caption("你填写的口语原文，便于核对。")
            st.code(original_view, language="markdown")

            # 正式化改写对比（如果有差异才展示）
            original_items = (
                payload.get("completed_raw", [])
                + payload.get("in_progress_raw", [])
                + payload.get("blockers_raw", [])
            )
            formal_items = (
                payload.get("completed", [])
                + payload.get("in_progress", [])
                + payload.get("blockers", [])
            )
            diff_pairs = [
                (o, f) for o, f in zip(original_items, formal_items) if o != f
            ]
            if diff_pairs:
                with st.expander("查看口语 → 正式改写对比", expanded=False):
                    for orig, formal in diff_pairs:
                        st.markdown(f"~~{orig}~~ → **{formal}**")

        with after_col:
            st.markdown("### 优化后")
            st.caption("适合直接汇报的版本，保留结果、风险和下一步。")

            st.markdown("#### 📋 领导精简版")
            leader_report = payload.get("leader_report", "")
            st.info(leader_report)

            escalation = analysis.get("escalation_blockers", [])
            if escalation:
                st.markdown("#### ⚠️ 阻塞识别")
                for item in escalation:
                    color = "🔴" if "需上升" in item else "🟡"
                    st.write(f"{color} {item}")

            st.markdown("#### 关键进展")
            for item in analysis["key_progress"]:
                st.write(f"- {item}")
            st.markdown("#### 风险与动作")
            for item in analysis["risk_points"]:
                st.write(f"- {item}")
            for item in analysis["tomorrow_focus"]:
                st.write(f"- {item}")

        with question_col:
            st.markdown("### 领导可能会问")
            st.caption("这些问题通常决定你这份日报是否站得住。")
            for item in analysis["leadership_questions"]:
                st.write(f"- {item}")

            st.markdown("### 管理关注点")
            for item in analysis["management_insights"]:
                st.write(f"- {item}")

        with st.expander("查看完整优化后 Markdown", expanded=False):
            st.code(markdown, language="markdown")

        # AI 增强摘要（如已启用 AI 改写）
        ai_summary_text = payload.get("ai_summary", "")
        if ai_summary_text:
            st.markdown("### AI 生成领导摘要")
            st.info(ai_summary_text)

        action_col, download_col, wx_col, fs_col = st.columns(4)
        with action_col:
            if st.button("保存到本地历史", use_container_width=True):
                append_report({**payload, "markdown": markdown})
                st.success("已保存到本地历史。")
                st.rerun()
        with download_col:
            file_name = f"daily-report-{payload['report_date']}-{payload['author']}.md"
            st.download_button(
                "下载 Markdown",
                data=markdown.encode("utf-8"),
                file_name=file_name,
                mime="text/markdown",
                use_container_width=True,
            )
        with wx_col:
            if weixin_webhook:
                if st.button("发送到企业微信", use_container_width=True):
                    ok, msg = send_weixin(weixin_webhook, markdown)
                    st.success(msg) if ok else st.error(msg)
            else:
                st.button("发送到企业微信", disabled=True, use_container_width=True,
                          help="请在侧边栏配置 Webhook")
        with fs_col:
            if feishu_webhook:
                if st.button("发送到飞书", use_container_width=True):
                    ok, msg = send_feishu(feishu_webhook, markdown)
                    st.success(msg) if ok else st.error(msg)
            else:
                st.button("发送到飞书", disabled=True, use_container_width=True,
                          help="请在侧边栏配置 Webhook")

with history_tab:
    st.subheader("历史记录")
    reports = load_reports()
    if not reports:
        st.info("还没有保存过日报。")
    else:
        df = pd.DataFrame(reports)
        authors = ["全部"] + sorted(df["author"].dropna().unique().tolist())
        filter_col, search_col = st.columns(2)
        with filter_col:
            author_filter = st.selectbox("按人员筛选", options=authors)
        with search_col:
            keyword = st.text_input("关键词搜索", placeholder="搜索完成项、备注、阻塞项")

        filtered_df = df.copy()
        if author_filter != "全部":
            filtered_df = filtered_df[filtered_df["author"] == author_filter]
        if keyword.strip():
            mask = filtered_df.apply(
                lambda row: keyword.lower() in str(row.to_dict()).lower(),
                axis=1,
            )
            filtered_df = filtered_df[mask]

        st.dataframe(
            filtered_df[["report_date", "author", "created_at"]],
            use_container_width=True,
            hide_index=True,
        )

        record_options = {
            f"{row.report_date} | {row.author} | {row.created_at}": row.id
            for row in filtered_df.itertuples(index=False)
        }
        selected_label = st.selectbox("选择一条日报", options=list(record_options.keys()))
        selected_id = record_options[selected_label]
        selected_row = next(item for item in reports if item["id"] == selected_id)

        if "analysis" in selected_row:
            history_summary_col, history_risk_col = st.columns(2)
            with history_summary_col:
                st.info(selected_row["analysis"].get("summary", ""))
            with history_risk_col:
                st.metric("风险等级", selected_row["analysis"].get("risk_level", "-"))

        st.markdown(selected_row["markdown"])
        st.download_button(
            "下载选中日报",
            data=selected_row["markdown"].encode("utf-8"),
            file_name=f"daily-report-{selected_row['report_date']}-{selected_row['author']}.md",
            mime="text/markdown",
        )

with weekly_tab:
    st.subheader("周报汇总")
    all_reports = load_reports()
    if not all_reports:
        st.info("还没有保存过日报，先在【填写日报】页生成并保存。")
    else:
        df_all = pd.DataFrame(all_reports)
        all_authors = ["全部"] + sorted(df_all["author"].dropna().unique().tolist())
        weekly_author = st.selectbox("按人员筛选", options=all_authors, key="weekly_author")

        weekly_data = build_weekly_summary(
            all_reports,
            author=None if weekly_author == "全部" else weekly_author,
        )

        if not weekly_data:
            st.info("该人员暂无日报记录。")
        else:
            for week in weekly_data:
                risk_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(week["risk_level"], "")
                with st.expander(
                    f"{risk_color} {week['week_key']} ({week['week_range']})  "
                    f"完成 {week['total_completed']} 项 | 阻塞 {week['total_blockers']} 项",
                    expanded=False,
                ):
                    st.write(week["summary_text"])

                    w_left, w_right = st.columns(2)
                    with w_left:
                        st.markdown("**本周完成事项**")
                        for item in week["all_completed"]:
                            st.write(f"- {item}")
                    with w_right:
                        st.markdown("**本周阻塞汇总**")
                        if week["all_blockers"]:
                            for item in week["all_blockers"]:
                                st.write(f"- {item}")
                        else:
                            st.write("- 无")

                    weekly_md = build_weekly_markdown(week)
                    st.download_button(
                        f"下载 {week['week_key']} 周报 Markdown",
                        data=weekly_md.encode("utf-8"),
                        file_name=f"weekly-report-{week['week_key']}.md",
                        mime="text/markdown",
                        key=f"dl_{week['week_key']}",
                    )
