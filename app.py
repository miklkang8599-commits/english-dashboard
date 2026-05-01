# ╔══════════════════════════════════════════════════════════╗
# ║  英文全能練習系統 — 數據監控儀表板 (獨立版)              ║
# ║  dashboard.py  V1.0                                      ║
# ╚══════════════════════════════════════════════════════════╝

import streamlit as st
import pandas as pd
import re
from datetime import date, datetime, timedelta
from supabase import create_client, Client
from streamlit_gsheets import GSheetsConnection

st.set_page_config(
    page_title="英文練習 — 數據監控",
    page_icon="📊",
    layout="wide"
)

# ── 常數 ──────────────────────────────────────────────────────────────────────
DASHBOARD_VERSION = "1.1"

LOGS_COLS = {
    "created_at": "時間", "name": "姓名", "group_id": "分組",
    "question_id": "題目ID", "result": "結果",
    "student_answer": "學生答案", "score": "分數", "task_name": "任務名稱"
}
ASSIGN_COLS = {
    "created_at": "建立時間", "task_name": "任務名稱",
    "target_group": "對象班級", "assigned_students": "指派學生",
    "student_count": "指派人數", "content": "內容",
    "description": "任務說明", "question_count": "題目數",
    "question_ids": "題目ID清單", "start_date": "開始日期",
    "end_date": "結束日期", "ref_students": "參考學生",
    "status": "狀態", "task_type": "類型", "task_id": "任務編號",
    "vocab_cfg": "單字設定"
}

# ── 工具函式 ──────────────────────────────────────────────────────────────────
def get_now():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Taipei"))

def is_admin(group_id):
    return str(group_id).upper() in ["ADMIN", "TEACHER"]

def _group_label(g):
    return str(g)

def _sort_task_names(names):
    def _key(n):
        return re.sub(r'^\[T\d+\]\s*', '', str(n)).strip().lower()
    return sorted(names, key=_key)

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

def _to_cn(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    return df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

# ── 資料載入（輕量版，只載入需要的）────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_assignments():
    try:
        sb  = get_supabase()
        res = sb.table("assignments").select("*").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df = _to_cn(df, ASSIGN_COLS)
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"載入任務失敗：{e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_logs():
    try:
        sb  = get_supabase()
        all_logs = []
        page = 0
        while True:
            res = sb.table("logs").select(
                "created_at,name,group_id,question_id,result,student_answer,score,task_name"
            ).order("created_at", desc=False).range(page*1000, (page+1)*1000-1).execute()
            if not res.data:
                break
            all_logs.extend(res.data)
            if len(res.data) < 1000:
                break
            page += 1
        if all_logs:
            df = pd.DataFrame(all_logs)
            df = _to_cn(df, LOGS_COLS)
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"載入 logs 失敗：{e}")
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_students():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df   = conn.read(worksheet="students", ttl=600).fillna("").astype(str)
        return df
    except:
        return pd.DataFrame()

# ── 登入 ──────────────────────────────────────────────────────────────────────
if 'dash_logged_in' not in st.session_state:
    st.session_state['dash_logged_in'] = False

if not st.session_state['dash_logged_in']:
    st.title("📊 英文練習 — 數據監控")
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("### 🔐 請登入")
        pwd = st.text_input("密碼", type="password", key="dash_pwd")
        if st.button("登入", use_container_width=True, type="primary"):
            # 從 secrets 讀取管理員密碼
            admin_pwd = st.secrets.get("ADMIN_PASSWORD", "admin123")
            if pwd == admin_pwd:
                st.session_state['dash_logged_in'] = True
                st.rerun()
            else:
                st.error("密碼錯誤")
    st.stop()

# ── 主介面 ────────────────────────────────────────────────────────────────────
st.title("📊 英文全能練習系統 — 數據監控儀表板")
st.caption(f"V{DASHBOARD_VERSION}　獨立版，直連 Supabase")

# 載入資料
df_a = load_assignments()
df_l = load_logs()
df_s = load_students()

# 頂部資料更新按鈕
col_r1, col_r2, col_r3 = st.columns([4, 1, 1])
col_r2.caption(f"logs: {len(df_l)} 筆　任務: {len(df_a)} 個")
if col_r3.button("🔄 更新資料", use_container_width=True):
    load_assignments.clear()
    load_logs.clear()
    st.rerun()

st.divider()

# ── Tab ───────────────────────────────────────────────────────────────────────
tab_monitor, tab_report = st.tabs(["📊 數據監控", "📋 全能英文學習報告"])

# 共用：班級清單（Tab1/Tab2 都需要）
all_groups_t2 = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique()) if not df_s.empty and '分組' in df_s.columns else []

# ══════════════════════════════════════════════════════════════════════════════
# Tab1：數據監控
# ══════════════════════════════════════════════════════════════════════════════
with tab_monitor:
    st.subheader("📊 數據監控")
    now_tw   = get_now()
    today_t2 = now_tw.date()

    # 時間範圍
    st.markdown("**⏱ 時間範圍**")
    _t2_periods = ["今日", "昨天", "前天", "三天", "七天", "30天"]
    if "t2_period" not in st.session_state:
        st.session_state["t2_period"] = "三天"
    _t2_cols = st.columns(6)
    for _i, _p in enumerate(_t2_periods):
        _active = st.session_state["t2_period"] == _p
        if _t2_cols[_i].button(_p, key=f"t2_btn_{_p}",
                               type="primary" if _active else "secondary",
                               use_container_width=True):
            st.session_state["t2_period"] = _p
            st.session_state["t2_do_query"] = False

    # 自訂時間
    with st.expander("📅 自訂時間範圍"):
        _cc1, _cc2, _cc3 = st.columns([2, 2, 1])
        t2_from_custom = _cc1.date_input("開始", value=today_t2, key="t2_custom_from_inp")
        t2_to_custom   = _cc2.date_input("結束", value=today_t2, key="t2_custom_to_inp")
        if _cc3.button("套用", use_container_width=True):
            st.session_state["t2_custom_from"] = t2_from_custom
            st.session_state["t2_custom_to"]   = t2_to_custom
            st.session_state["t2_period"]       = "自訂"
            st.session_state["t2_do_query"]     = False

    period = st.session_state.get("t2_period", "今日")
    _d_map = {
        "今日": (today_t2, today_t2),
        "昨天": (today_t2 - timedelta(days=1), today_t2 - timedelta(days=1)),
        "前天": (today_t2 - timedelta(days=2), today_t2 - timedelta(days=2)),
        "三天": (today_t2 - timedelta(days=2), today_t2),
        "七天": (today_t2 - timedelta(days=6), today_t2),
        "30天": (today_t2 - timedelta(days=29), today_t2),
        "自訂": (st.session_state.get("t2_custom_from", today_t2),
                st.session_state.get("t2_custom_to",   today_t2)),
    }
    date_from_t2, date_to_t2 = _d_map.get(period, (today_t2, today_t2))
    date_from_str = date_from_t2.strftime("%Y-%m-%d")
    date_to_str   = date_to_t2.strftime("%Y-%m-%d")
    st.caption(f"📅 {period}：{date_from_str} ～ {date_to_str}")

    # 依時間篩選 logs
    df_lf = df_l.copy() if not df_l.empty else pd.DataFrame()
    if not df_lf.empty and "時間" in df_lf.columns:
        df_lf = df_lf[
            (df_lf["時間"].str[:10] >= date_from_str) &
            (df_lf["時間"].str[:10] <= date_to_str)
        ]
    df_lf_ans = df_lf[~df_lf["結果"].str.contains("📖", na=False)] if not df_lf.empty and "結果" in df_lf.columns else pd.DataFrame()

    # 整體統計
    st.divider()
    mc1, mc2, mc3, mc4 = st.columns(4)
    total_ans = len(df_lf_ans)
    total_ok  = len(df_lf_ans[df_lf_ans["結果"] == "✅"]) if not df_lf_ans.empty else 0
    total_err = len(df_lf_ans[df_lf_ans["結果"] == "❌"]) if not df_lf_ans.empty else 0
    acc       = f"{int(total_ok/total_ans*100)}%" if total_ans else "—"
    mc1.metric("📝 總答題", total_ans)
    mc2.metric("✅ 答對",   total_ok)
    mc3.metric("❌ 答錯",   total_err)
    mc4.metric("🎯 正確率", acc)

    # ── 工具：時間加星期 ──────────────────────────────────────────────
    _WEEKDAY_CN = ["一","二","三","四","五","六","日"]
    def _fmt_time_with_weekday(t_str):
        """把 '2026-04-16 15:09' 轉成 '04-16(三) 15:09'"""
        try:
            dt = pd.to_datetime(str(t_str)[:16])
            wd = _WEEKDAY_CN[dt.weekday()]
            return dt.strftime(f"%m-%d({wd}) %H:%M")
        except:
            return str(t_str)[:16]

    def _clean_task_name(name):
        """去掉任務名稱第一個全形空格（\u3000）後的所有內容"""
        s = str(name)
        idx = s.find('\u3000')  # 全形空格
        if idx != -1:
            s = s[:idx]
        return s.strip()

    # 學生清單（縮排，展開後顯示詳細答題）
    if not df_lf_ans.empty and "姓名" in df_lf_ans.columns:
        st.markdown("**👥 學生答題狀況**")
        # 依 students 工作表 note1 欄升冪排列
        if not df_s.empty and "姓名" in df_s.columns and "note1" in df_s.columns:
            df_s_order = df_s[["姓名","note1"]].copy()
            df_s_order["_note1_num"] = pd.to_numeric(df_s_order["note1"], errors="coerce")
            df_s_order = df_s_order.sort_values("_note1_num")
            ordered_names = df_s_order["姓名"].tolist()
            present = set(df_lf_ans["姓名"].unique())
            student_names = [n for n in ordered_names if n in present]
            # 有答題但不在 students 名單的，補在最後
            student_names += sorted([n for n in present if n not in set(student_names)])
        else:
            student_names = sorted(df_lf_ans["姓名"].unique().tolist())
        for stu in student_names:
            stu_df = df_lf_ans[df_lf_ans["姓名"] == stu].copy()
            ok  = len(stu_df[stu_df["結果"] == "✅"])
            err = len(stu_df[stu_df["結果"] == "❌"])
            tot = len(stu_df)
            acc_stu = f"{int(ok/tot*100)}%" if tot else "—"
            label = f"{stu}　📝 {tot} 題　✅ {ok}　❌ {err}　🎯 {acc_stu}"
            with st.expander(label, expanded=False):
                show_cols = [c for c in ["時間","分組","題目ID","結果","學生答案","任務名稱"] if c in stu_df.columns]
                disp = stu_df[show_cols].reset_index(drop=True).copy()
                # 時間加星期
                if "時間" in disp.columns:
                    disp["時間"] = disp["時間"].apply(_fmt_time_with_weekday)
                # 任務名稱去序號後綴
                if "任務名稱" in disp.columns:
                    disp["任務名稱"] = disp["任務名稱"].apply(_clean_task_name)
                # 欄位寬度設定
                col_cfg = {}
                if "時間"   in disp.columns: col_cfg["時間"]   = st.column_config.TextColumn("時間",   width=120)
                if "分組"   in disp.columns: col_cfg["分組"]   = st.column_config.TextColumn("班級",   width=60)
                if "題目ID" in disp.columns: col_cfg["題目ID"] = st.column_config.TextColumn("題目",   width=70)
                if "結果"   in disp.columns: col_cfg["結果"]   = st.column_config.TextColumn("結果",   width=50)
                if "學生答案" in disp.columns: col_cfg["學生答案"] = st.column_config.TextColumn("答案", width=80)
                if "任務名稱" in disp.columns: col_cfg["任務名稱"] = st.column_config.TextColumn("任務名稱", width=320)
                st.dataframe(disp, use_container_width=True, hide_index=True, column_config=col_cfg)
    elif df_lf_ans.empty:
        st.info("此時間範圍內無答題資料")

# ══════════════════════════════════════════════════════════════════════════════
# Tab2：全能英文學習報告
# ══════════════════════════════════════════════════════════════════════════════
with tab_report:
    st.subheader("📋 全能英文學習報告")
    st.caption("依任務分開列出各學生的答題狀況")

    if df_a.empty:
        st.info("尚無任務資料")
    else:
        # 任務選擇
        task_names_rpt = ["（全部）"] + _sort_task_names(df_a["任務名稱"].tolist() if "任務名稱" in df_a.columns else [])
        sel_tasks_rpt  = st.multiselect("選擇任務（空白=全部）", task_names_rpt[1:], key="rpt_tasks")
        sel_grp_rpt    = st.selectbox("班級", ["（全部）"] + [_group_label(g) for g in all_groups_t2], key="rpt_grp")

        if st.button("📋 產生報告", type="primary"):
            rpt_lines = []
            flt_a = df_a.copy()
            if sel_tasks_rpt:
                flt_a = flt_a[flt_a["任務名稱"].isin(sel_tasks_rpt)]
            grp_rpt = sel_grp_rpt if sel_grp_rpt != "（全部）" else None

            if not df_s.empty and "姓名" in df_s.columns:
                students_rpt = sorted(df_s[
                    df_s["分組"] == grp_rpt if grp_rpt else ~df_s["分組"].isin(["ADMIN","TEACHER"])
                ]["姓名"].tolist())
            else:
                students_rpt = []

            for stu in students_rpt:
                stu_l = df_l[df_l["姓名"] == stu] if not df_l.empty and "姓名" in df_l.columns else pd.DataFrame()
                if stu_l.empty:
                    continue
                stu_lines = [f"【{stu}】"]
                for _, arow in flt_a.iterrows():
                    tname  = str(arow.get("任務名稱",""))
                    tid    = str(arow.get("任務編號",""))
                    qids_s = str(arow.get("題目ID清單",""))
                    q_ids  = set([q.strip() for q in qids_s.split(",") if q.strip()])
                    t_logs = stu_l[stu_l["任務名稱"].fillna("") == tid] if tid else pd.DataFrame()
                    if t_logs.empty:
                        continue
                    t_ans  = t_logs[~t_logs["結果"].str.contains("📖", na=False)]
                    done   = len(set(t_ans["題目ID"].tolist()) & q_ids) if not t_ans.empty and "題目ID" in t_ans.columns else 0
                    wrong  = set(t_ans[t_ans["結果"]=="❌"]["題目ID"].tolist()) if not t_ans.empty else set()
                    ok     = set(t_ans[t_ans["結果"]=="✅"]["題目ID"].tolist()) if not t_ans.empty else set()
                    need   = wrong - ok
                    short  = re.sub(r'^\[T\d+\]\s*', '', tname)
                    stu_lines.append(f"  {short}：完成{done}/{len(q_ids)}　需加強{len(need)}題")
                if len(stu_lines) > 1:
                    rpt_lines.extend(stu_lines)
                    rpt_lines.append("")

            if rpt_lines:
                st.text_area("報告內容（可複製）", "\n".join(rpt_lines), height=400)
            else:
                st.info("無符合條件的資料")

st.divider()
st.caption(f"英文全能練習系統 數據監控儀表板 V{DASHBOARD_VERSION}　© 2026")
