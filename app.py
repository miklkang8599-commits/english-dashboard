# ╔══════════════════════════════════════════════════════════╗
# ║  英文全能練習系統 — 數據監控儀表板 (獨立版)              ║
# ║  dashboard.py  V1.35                                     ║
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
DASHBOARD_VERSION = "1.35"

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
def load_supabase_students():
    try:
        sb  = get_supabase()
        res = sb.table("students").select("name,group_id,account").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df = df[~df["group_id"].isin(["ADMIN","TEACHER"])]
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"載入學生資料失敗：{e}")
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_students():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df   = conn.read(worksheet="students", ttl=600).fillna("").astype(str)
        return df
    except:
        return pd.DataFrame()

# 題型工作表對應：content=題目欄, answer=答案欄
_QTYPE_SHEETS = {
    "單選":    {"sheet": "單選",    "key": ["版本","年度","冊編號","課編號","句編號"], "content": "單選題目",        "answer": "單選答案"},
    "文意文法":{"sheet": "單選",    "key": ["版本","年度","冊編號","課編號","句編號"], "content": "單選題目",        "answer": "單選答案"},
    "重組":    {"sheet": "重組",    "key": ["版本","年度","冊編號","課編號","句編號"], "content": "重組中文題目",     "answer": "重組英文答案"},
    "閱讀重組":{"sheet": "重組",    "key": ["版本","年度","冊編號","課編號","句編號"], "content": "重組中文題目",     "answer": "重組英文答案"},
    "閱讀單句":{"sheet": "閱讀單句","key": ["版本","年度","冊編號","課編號","句編號"], "content": "題目",            "answer": "答案"},
    "朗讀":    {"sheet": "朗讀",    "key": ["版本","年度","冊編號","課編號","句編號"], "content": "朗讀句子",        "answer": ""},
    "拼單字":  {"sheet": "拼單字",  "key": ["版本","年度","冊編號","課編號","句編號"], "content": "中文意思",        "answer": "英文單字"},
    "單字重組":{"sheet": "拼單字",  "key": ["版本","年度","冊編號","課編號","句編號"], "content": "中文意思",        "answer": "英文單字"},
    "聽力音標":{"sheet": "聽力音標","key": ["版本","單元編號","組編號","符號編號"],    "content": "",               "answer": "KK符號"},
    "聽力重組":{"sheet": "聽力重組","key": ["版本","年度","冊編號","課編號","句編號"], "content": "",               "answer": "聽力重組英文答案"},
    "聽力單字":{"sheet": "聽力單字","key": ["版本","單元編號","組編號","符號編號"],    "content": "",               "answer": "單字"},
}

@st.cache_data(ttl=600)
def load_question_sheet(sheet_name: str) -> pd.DataFrame:
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df   = conn.read(worksheet=sheet_name, ttl=600).fillna("").astype(str)
        return df
    except:
        return pd.DataFrame()

def _parse_qid(qid: str):
    """
    解析 question_id，例如 '南一_112_2_單選_1_13'
    回傳 (版本, 年度, 冊編號, 課編號, 句編號, 題型)
    """
    parts = str(qid).split("_")
    # 找題型位置
    for i, p in enumerate(parts):
        if p in _QTYPE_SHEETS:
            qtype = p
            # 版本=parts[0], 年度=parts[1], 冊=parts[2], 課=parts[i+1], 句=parts[i+2]
            version = parts[0] if len(parts) > 0 else ""
            nendo   = parts[1] if len(parts) > 1 else ""
            册号    = parts[2] if len(parts) > 2 else ""
            course  = parts[i+1] if len(parts) > i+1 else ""
            sent    = parts[i+2] if len(parts) > i+2 else ""
            return {"版本": version, "年度": nendo, "冊編號": 册号,
                    "課編號": course, "句編號": sent, "題型": qtype}
    return None

def _norm(x):
    s = str(x).strip()
    try: return str(int(float(s)))
    except: return s

def _try_int(s):
    try: int(float(s)); return True
    except: return False

@st.cache_data(ttl=600)
def build_question_lookup(qids: tuple) -> dict:
    """給定一組 question_id，回傳 {qid: {'題目': ..., '答案': ...}} 字典"""
    by_type = {}
    parsed  = {}
    unmatched = []
    for qid in qids:
        p = _parse_qid(qid)
        if p:
            parsed[qid] = p
            by_type.setdefault(p["題型"], []).append(qid)
        else:
            unmatched.append(qid)

    result = {}

    # 已知題型處理
    for qtype, ids in by_type.items():
        cfg = _QTYPE_SHEETS.get(qtype)
        if not cfg:
            unmatched.extend(ids)
            continue
        df = load_question_sheet(cfg["sheet"])
        if df.empty:
            continue
        content_col = cfg["content"]
        answer_col  = cfg.get("answer", "")
        key_cols    = cfg["key"]
        check_cols  = [c for c in key_cols + ([content_col] if content_col else []) if c]
        missing     = [c for c in check_cols if c not in df.columns]
        if missing:
            continue
        for qid in ids:
            p = parsed[qid]
            mask = pd.Series([True] * len(df), index=df.index)
            for col in key_cols:
                if col in p and col in df.columns:
                    val = str(p[col]).strip()
                    mask &= df[col].apply(_norm) == _norm(val)
            rows = df[mask]
            if not rows.empty:
                row = rows.iloc[0]
                content = str(row[content_col]) if content_col and content_col in df.columns else ""
                answer  = str(row[answer_col])  if answer_col  and answer_col  in df.columns else ""
                result[qid] = {"題目": content if content else answer, "答案": answer}

    # 未比對到的：多重判斷嘗試單選工作表
    if unmatched:
        df_mcq = load_question_sheet("單選")
        df_read = load_question_sheet("閱讀單句")
        for qid in unmatched:
            parts = str(qid).split("_")
            # 判斷是否為單選：_type==mcq、欄位有單選答案/選項A-D、名稱含單選
            is_mcq = (
                "mcq" in parts or
                "單選" in str(qid) or
                (not df_mcq.empty and "單選答案" in df_mcq.columns) or
                (not df_mcq.empty and "選項A" in df_mcq.columns)
            )
            # 嘗試從 parts 取出數字欄位（版本_年度_冊_課_句）
            nums = [p for p in parts if p.isdigit() or _try_int(p)]
            version = parts[0] if parts else ""
            year    = nums[0] if len(nums) > 0 else ""
            vol     = nums[1] if len(nums) > 1 else ""
            course  = nums[2] if len(nums) > 2 else ""
            sent    = nums[3] if len(nums) > 3 else ""

            for df_try, content_col, answer_col in [
                (df_mcq,  "單選題目", "單選答案"),
                (df_read, "題目",     "答案"),
            ]:
                if df_try.empty:
                    continue
                key_cols = ["版本","年度","冊編號","課編號","句編號"]
                vals     = {"版本": version, "年度": year, "冊編號": vol, "課編號": course, "句編號": sent}
                mask = pd.Series([True] * len(df_try), index=df_try.index)
                for col in key_cols:
                    if col in df_try.columns and vals.get(col):
                        mask &= df_try[col].apply(_norm) == _norm(vals[col])
                rows = df_try[mask]
                if not rows.empty:
                    row = rows.iloc[0]
                    content = str(row[content_col]) if content_col in df_try.columns else ""
                    answer  = str(row[answer_col])  if answer_col  in df_try.columns else ""
                    result[qid] = {"題目": content if content else answer, "答案": answer}
                    break
    return result

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
tab_monitor, tab_report, tab_tasks = st.tabs(["📊 數據監控", "📋 全能英文學習報告", "📋 學生任務列表"])

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
        """把 '2026-04-16 15:09:32' 轉成 '04-16(三) 15:09:32'"""
        try:
            dt = pd.to_datetime(str(t_str)[:19])
            wd = _WEEKDAY_CN[dt.weekday()]
            return dt.strftime(f"%m-%d({wd}) %H:%M:%S")
        except:
            return str(t_str)[:19]

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
                disp = stu_df[show_cols].sort_values("時間", ascending=False).reset_index(drop=True).copy() if "時間" in stu_df.columns else stu_df[show_cols].reset_index(drop=True).copy()
                disp = disp.fillna("").astype(str)
                # 時間加星期
                if "時間" in disp.columns:
                    disp["時間"] = disp["時間"].apply(_fmt_time_with_weekday)
                # 任務名稱：用任務編號對應 assignments 完整名稱，再截掉全形空格後綴
                if "任務名稱" in disp.columns:
                    # 從 assignments 題目ID清單反查任務名稱
                    if not df_a.empty and "題目ID清單" in df_a.columns and "任務名稱" in df_a.columns:
                        # 建立 qid → 任務名稱 對應表
                        qid_to_task = {}
                        for _, row in df_a.iterrows():
                            task_name = _clean_task_name(str(row.get("任務名稱","")))
                            qids_str  = str(row.get("題目ID清單",""))
                            # 清單格式可能是逗號分隔字串或 list
                            if qids_str.startswith("["):
                                import ast
                                try: items = ast.literal_eval(qids_str)
                                except: items = []
                            else:
                                items = [q.strip() for q in qids_str.split(",") if q.strip()]
                            for q in items:
                                # 去掉前綴 R_ 或其他前綴
                                clean_q = re.sub(r'^[A-Za-z]_', '', q.strip())
                                qid_to_task[q.strip()]   = task_name
                                qid_to_task[clean_q]     = task_name
                        # 套用到每一列
                        def _find_task(raw_qid):
                            q = str(raw_qid).strip()
                            if q in qid_to_task:
                                return qid_to_task[q]
                            # 嘗試去掉前綴比對
                            q2 = re.sub(r'^[A-Za-z]_', '', q)
                            return qid_to_task.get(q2, "")
                        # disp["題目ID"] 此時已被替換成題目內容，需用原始 stu_df
                        orig_qids = stu_df[show_cols].sort_values("時間", ascending=False)["題目ID"].fillna("").astype(str).reset_index(drop=True) if "時間" in stu_df.columns else stu_df[show_cols]["題目ID"].fillna("").astype(str).reset_index(drop=True)
                        disp["任務名稱"] = orig_qids.apply(_find_task)
                    else:
                        disp["任務名稱"] = disp["任務名稱"].apply(_clean_task_name)
                # 題目ID → 題目內容，並新增正確答案欄
                if "題目ID" in disp.columns:
                    qids = tuple(disp["題目ID"].astype(str).str.strip().unique())
                    q_lookup = build_question_lookup(qids)
                    disp["正確答案"] = disp["題目ID"].apply(
                        lambda x: q_lookup.get(str(x).strip(), {}).get("答案", "")
                    )
                    disp["題目ID"] = disp["題目ID"].apply(
                        lambda x: q_lookup.get(str(x).strip(), {}).get("題目", re.sub(r'^\[T\d+\]\s*', '', str(x)).strip())
                    )
                # 欄位寬度設定
                col_cfg = {}
                if "時間"     in disp.columns: col_cfg["時間"]     = st.column_config.TextColumn("時間",     width=70)
                if "分組"     in disp.columns: col_cfg["分組"]     = st.column_config.TextColumn("班級",     width=30)
                if "題目ID"   in disp.columns: col_cfg["題目ID"]   = st.column_config.TextColumn("題目",     width=None, help=None)
                if "結果"     in disp.columns: col_cfg["結果"]     = st.column_config.TextColumn("結果",     width=30)
                if "學生答案" in disp.columns: col_cfg["學生答案"] = st.column_config.TextColumn("學生答案", width=30)
                if "正確答案" in disp.columns: col_cfg["正確答案"] = st.column_config.TextColumn("正確答案", width=30)
                if "任務名稱" in disp.columns: col_cfg["任務名稱"] = st.column_config.TextColumn("任務名稱", width=50)
                # 調整欄位順序：時間、班級、題目、結果、學生答案、正確答案、任務名稱
                ordered_cols = [c for c in ["時間","分組","題目ID","結果","學生答案","正確答案","任務名稱"] if c in disp.columns]
                st.dataframe(disp[ordered_cols], use_container_width=True, hide_index=True, column_config=col_cfg, height=40*35+38)
    elif df_lf_ans.empty:
        st.info("此時間範圍內無答題資料")

# ══════════════════════════════════════════════════════════════════════════════
# Tab2：全能英文學習報告
# ══════════════════════════════════════════════════════════════════════════════
with tab_report:
    st.subheader("📋 全能英文學習報告")

    # ── 任務名稱精簡：去掉日期部分，保留到人名 ──────────────────────────────
    def _short_task_name(name: str) -> str:
        """
        '[T260427003] 聽力音標-母音-KK音選字-年-冊-課-17題-AA-小康-2026-04-27_15:09-...'
        → '[T260427003] 聽力音標-母音-KK音選字-年-冊-課-17題-AA-小康'
        去掉第一個 '-20xx-' 之後的所有內容
        """
        s = str(name)
        m = re.search(r'-20\d{2}-\d{2}-\d{2}[_\-]', s)
        if m:
            s = s[:m.start()]
        return s.strip()

    # ── 建立 qid → 任務名稱 對應（精簡版）──────────────────────────────────
    def _build_qid_task_map(df_a):
        qid_task = {}
        if df_a.empty or "題目ID清單" not in df_a.columns:
            return qid_task
        for _, row in df_a.iterrows():
            tname = _short_task_name(str(row.get("任務名稱","")))
            for q in str(row.get("題目ID清單","")).split(","):
                q = q.strip()
                if q:
                    qid_task[q] = tname
                    qid_task[re.sub(r'^[A-Za-z]_','',q)] = tname
        return qid_task

    # ── 時間選擇（同數據監控）──────────────────────────────────────────────
    PERIODS_RPT = ["今日","三天","一週","兩週","本月","自訂"]
    if "rpt_period" not in st.session_state:
        st.session_state["rpt_period"] = "三天"

    rpt_cols = st.columns(len(PERIODS_RPT))
    for i, p in enumerate(PERIODS_RPT):
        if rpt_cols[i].button(p, key=f"rpt_p_{p}",
                              type="primary" if st.session_state["rpt_period"]==p else "secondary",
                              use_container_width=True):
            st.session_state["rpt_period"] = p
            st.rerun()

    period_rpt = st.session_state["rpt_period"]
    today = date.today()
    if period_rpt == "今日":
        rpt_from, rpt_to = today, today
    elif period_rpt == "三天":
        rpt_from, rpt_to = today - timedelta(days=2), today
    elif period_rpt == "一週":
        rpt_from, rpt_to = today - timedelta(days=6), today
    elif period_rpt == "兩週":
        rpt_from, rpt_to = today - timedelta(days=13), today
    elif period_rpt == "本月":
        rpt_from, rpt_to = today.replace(day=1), today
    else:
        c1, c2 = st.columns(2)
        rpt_from = c1.date_input("開始日期", today - timedelta(days=6), key="rpt_from")
        rpt_to   = c2.date_input("結束日期", today, key="rpt_to")

    rpt_from_str = rpt_from.strftime("%Y-%m-%d")
    rpt_to_str   = rpt_to.strftime("%Y-%m-%d")
    st.caption(f"📅 {period_rpt}：{rpt_from_str} ～ {rpt_to_str}")

    # ── 篩選 logs ──────────────────────────────────────────────────────────
    df_rpt = df_l.copy() if not df_l.empty else pd.DataFrame()
    if not df_rpt.empty and "時間" in df_rpt.columns:
        df_rpt = df_rpt[
            (df_rpt["時間"].str[:10] >= rpt_from_str) &
            (df_rpt["時間"].str[:10] <= rpt_to_str)
        ]
    df_rpt_ans = df_rpt[~df_rpt["結果"].str.contains("📖", na=False)] if not df_rpt.empty and "結果" in df_rpt.columns else pd.DataFrame()

    qid_task_map = _build_qid_task_map(df_a)

    st.divider()
    sec1, sec2 = st.tabs(["📊 全班統計報告", "👤 個別學生報告"])

    # ════════════════════════════════════════════
    # 區塊1：全班統計報告
    # ════════════════════════════════════════════
    with sec1:
        st.caption("依學生列出各任務答題統計，方便複製貼上")
        if st.button("📋 產生全班報告", type="primary", key="gen_all"):
            if df_rpt_ans.empty:
                st.info("此時間範圍內無答題資料")
            else:
                # 學生清單依 note1 排序
                if not df_s.empty and "姓名" in df_s.columns:
                    if "note1" in df_s.columns:
                        df_s_ord = df_s[["姓名","note1"]].copy()
                        df_s_ord["_n"] = pd.to_numeric(df_s_ord["note1"], errors="coerce")
                        students_all = df_s_ord.sort_values("_n")["姓名"].tolist()
                    else:
                        students_all = sorted(df_s["姓名"].unique().tolist())
                    students_all = [s for s in students_all if s in df_rpt_ans["姓名"].unique()]
                else:
                    students_all = sorted(df_rpt_ans["姓名"].unique().tolist())

                lines = []
                for stu in students_all:
                    stu_ans = df_rpt_ans[df_rpt_ans["姓名"] == stu]
                    if stu_ans.empty:
                        continue
                    # 依任務分組統計
                    stu_ans = stu_ans.copy()
                    stu_ans["_task"] = stu_ans["題目ID"].apply(
                        lambda x: qid_task_map.get(str(x).strip(), qid_task_map.get(re.sub(r'^[A-Za-z]_','',str(x).strip()), "未知任務"))
                    )
                    task_stats = []
                    for tname, tdf in stu_ans.groupby("_task"):
                        total = len(tdf)
                        ok    = len(tdf[tdf["結果"]=="✅"])
                        err   = len(tdf[tdf["結果"]=="❌"])
                        task_stats.append(f"{tname}\n答題{total}題　✅{ok}　❌{err}")

                    lines.append(f"【{stu}】")
                    lines.append(f"{rpt_from_str} ～ {rpt_to_str}")
                    lines.extend(task_stats)
                    lines.append("")

                if lines:
                    st.text_area("全班報告（可複製）", "\n".join(lines), height=500, key="all_rpt_text")
                else:
                    st.info("無符合條件的資料")

    # ════════════════════════════════════════════
    # 區塊2：個別學生報告
    # ════════════════════════════════════════════
    with sec2:
        st.caption("選擇學生，列出每日任務答題明細")

        # 學生選擇
        if not df_rpt_ans.empty and "姓名" in df_rpt_ans.columns:
            stu_opts = sorted(df_rpt_ans["姓名"].unique().tolist())
        elif not df_s.empty and "姓名" in df_s.columns:
            stu_opts = sorted(df_s[~df_s["分組"].isin(["ADMIN","TEACHER"])]["姓名"].tolist())
        else:
            stu_opts = []

        sel_stu = st.selectbox("選擇學生", stu_opts, key="rpt2_stu") if stu_opts else None

        if sel_stu and st.button("📋 產生個人報告", type="primary", key="gen_one"):
            stu_ans = df_rpt_ans[df_rpt_ans["姓名"] == sel_stu].copy() if not df_rpt_ans.empty else pd.DataFrame()
            if stu_ans.empty:
                st.info("此時間範圍內無答題資料")
            else:
                stu_ans["_date"] = stu_ans["時間"].str[:10]
                stu_ans["_task"] = stu_ans["題目ID"].apply(
                    lambda x: qid_task_map.get(str(x).strip(), qid_task_map.get(re.sub(r'^[A-Za-z]_','',str(x).strip()), "未知任務"))
                )
                lines = [f"【{sel_stu}】"]
                for day in sorted(stu_ans["_date"].unique()):
                    day_df = stu_ans[stu_ans["_date"] == day]
                    try:
                        dt  = pd.to_datetime(day)
                        wd  = ["一","二","三","四","五","六","日"][dt.weekday()]
                        day_label = f"{day}（{wd}）"
                    except:
                        day_label = day
                    lines.append(f"\n📅 {day_label}")
                    for tname, tdf in day_df.groupby("_task"):
                        total = len(tdf)
                        ok    = len(tdf[tdf["結果"]=="✅"])
                        err   = len(tdf[tdf["結果"]=="❌"])
                        lines.append(f"{tname}\n答題{total}題　✅{ok}　❌{err}")
                lines.append("")
                st.text_area("個人報告（可複製）", "\n".join(lines), height=500, key="one_rpt_text")


# ══════════════════════════════════════════════════════════════════════════════
# Tab3：學生任務列表
# ══════════════════════════════════════════════════════════════════════════════
with tab_tasks:
    df_stu_sb = load_supabase_students()

    # 篩出進行中任務
    df_active = df_a[df_a["狀態"] == "進行中"].copy() if not df_a.empty and "狀態" in df_a.columns else pd.DataFrame()

    if df_stu_sb.empty:
        st.info("無學生資料")
    elif df_active.empty:
        st.info("目前沒有進行中的任務")
    else:
        # 建立 任務名稱清單（已清理）
        def _get_active_tasks_for_student(stu_name):
            tasks = []
            for _, row in df_active.iterrows():
                assigned = [s.strip() for s in str(row.get("指派學生","")).split(",") if s.strip()]
                if stu_name in assigned:
                    tname     = _clean_task_name(str(row.get("任務名稱","")))
                    end_date  = str(row.get("結束日期",""))[:10]
                    task_type = str(row.get("類型",""))
                    tasks.append({"任務名稱": tname, "類型": task_type, "結束日期": end_date})
            return tasks

        # 依班級分組顯示
        groups = sorted(df_stu_sb["group_id"].unique().tolist())
        for grp in groups:
            stu_in_grp = df_stu_sb[df_stu_sb["group_id"] == grp]["name"].tolist()
            # 只顯示有進行中任務的班級
            grp_has_tasks = any(_get_active_tasks_for_student(n) for n in stu_in_grp)
            if not grp_has_tasks:
                continue
            st.markdown(f"#### 班級：{grp}")
            for stu_name in stu_in_grp:
                tasks = _get_active_tasks_for_student(stu_name)
                if not tasks:
                    continue
                stu_row  = df_stu_sb[df_stu_sb["name"] == stu_name].iloc[0] if not df_stu_sb[df_stu_sb["name"] == stu_name].empty else None
                account  = str(stu_row["account"]) if stu_row is not None and "account" in df_stu_sb.columns else ""
                label = f"{stu_name}（{account}）　📋 {len(tasks)} 個進行中任務"
                with st.expander(label, expanded=False):
                    df_t = pd.DataFrame(tasks)
                    st.dataframe(
                        df_t,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "任務名稱": st.column_config.TextColumn("任務名稱", width=None),
                            "類型":     st.column_config.TextColumn("類型",     width=60),
                            "結束日期": st.column_config.TextColumn("結束日期", width=80),
                        }
                    )

st.divider()
st.caption(f"英文全能練習系統 數據監控儀表板 V{DASHBOARD_VERSION}　© 2026")
