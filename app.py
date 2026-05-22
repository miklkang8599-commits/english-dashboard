# ╔══════════════════════════════════════════════════════════╗
# ║  英文全能練習系統 — 全班學習報告 (獨立版)                ║
# ║  dashboard.py  V1.90                                     ║
# ╚══════════════════════════════════════════════════════════╝

import streamlit as st
import pandas as pd
import re
from datetime import date, datetime, timedelta
from supabase import create_client, Client
from streamlit_gsheets import GSheetsConnection
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="英文全能 — 學習報告",
    page_icon="📋",
    layout="wide"
)

# 每4分鐘心跳一次，防止 session 閒置斷線
st_autorefresh(interval=240000, limit=None, key="keepalive")

# ── 常數 ──────────────────────────────────────────────────────────────────────
DASHBOARD_VERSION = "1.90"

LOGS_COLS = {
    "created_at": "時間", "name": "姓名", "group_id": "分組",
    "question_id": "題目ID", "result": "結果",
    "student_answer": "學生答案", "score": "分數", "task_name": "任務名稱",
    "elapsed_sec": "答題秒數"
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
                "created_at,name,group_id,question_id,result,student_answer,score,task_name,elapsed_sec"
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

def load_logs_for_student(stu_name: str) -> pd.DataFrame:
    """只撈單一學生的 logs，不用 cache，每次即時取得"""
    try:
        sb  = get_supabase()
        all_logs = []
        page = 0
        while True:
            res = sb.table("logs").select(
                "created_at,name,group_id,question_id,result,student_answer,score,task_name,elapsed_sec"
            ).eq("name", stu_name).order("created_at", desc=False).range(page*1000, (page+1)*1000-1).execute()
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
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_supabase_students():
    try:
        sb  = get_supabase()
        res = sb.table("students").select("name,group_id,account,school_year").execute()
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
    "單選":    {"sheet": "單選",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "單選題目",        "answer": "單選答案",        "prefix": ""},
    "文意文法":{"sheet": "單選",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "單選題目",        "answer": "單選答案",        "prefix": ""},
    "重組":    {"sheet": "重組",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "重組中文題目",     "answer": "重組英文答案",    "prefix": ""},
    "閱讀重組":{"sheet": "重組",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "重組中文題目",     "answer": "重組英文答案",    "prefix": ""},
    "對話重組":{"sheet": "重組",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "重組中文題目",     "answer": "重組英文答案",    "prefix": ""},
    "閱讀單句":{"sheet": "閱讀單句","key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "題目",            "answer": "答案",            "prefix": "RM"},
    "朗讀":    {"sheet": "朗讀",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "朗讀句子",        "answer": "",                "prefix": "R"},
    "拼單字":  {"sheet": "拼單字",  "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "中文意思",        "answer": "英文單字",        "prefix": "V"},
    "單字重組":{"sheet": "拼單字",  "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "中文意思",        "answer": "英文單字",        "prefix": "V"},
    "聽力音標":{"sheet": "聽力音標","key": ["版本","單元編號","組編號","符號編號"],           "content": "",               "answer": "KK符號",          "prefix": "LP"},
    "KK音選字":{"sheet": "聽力音標","key": ["版本","單元編號","組編號","符號編號"],           "content": "",               "answer": "KK符號",          "prefix": "LP"},
    "聽力重組":{"sheet": "聽力句子重組","key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "",            "answer": "聽力重組英文答案","prefix": "LS"},
    "聽力單字":{"sheet": "聽力單字","key": ["版本","單元編號","組編號","符號編號"],           "content": "",               "answer": "單字",            "prefix": "LP"},
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
    解析 question_id，格式來自 app.py：
      無前綴：版本_年度_冊編號_單元_課編號_句編號  (重組/單選/對話重組/閱讀重組等)
      R_    ：R_版本_年度_冊編號_單元_課編號_句編號 (朗讀)
      RM_   ：RM_版本_年度_冊編號_單元_課編號_句編號 (閱讀單句)
      V_    ：V_版本_年度_冊編號_單元_課編號_句編號  (拼單字/單字重組)
      LS_   ：LS_版本_年度_冊編號_單元_課編號_句編號 (聽力重組)
      LP_   ：LP_版本_單元編號_組編號_符號編號       (聽力音標)
    """
    s     = str(qid).strip()
    parts = s.split("_")

    # 前綴對應題型
    prefix_to_type = {
        "R":  "朗讀",
        "RM": "閱讀單句",
        "V":  "拼單字",
        "LS": "聽力重組",
        "LP": "聽力音標",
    }

    # 抽出前綴
    prefix = ""
    body   = parts
    if parts[0] in prefix_to_type:
        prefix = parts[0]
        body   = parts[1:]

    # LP 聽力音標：LP_版本_單元編號_組編號_符號編號
    if prefix == "LP":
        ver    = body[0] if len(body) > 0 else ""
        unit_n = body[1] if len(body) > 1 else ""
        grp_n  = body[2] if len(body) > 2 else ""
        sym_n  = body[3] if len(body) > 3 else ""
        return {"版本": ver, "單元編號": unit_n, "組編號": grp_n,
                "符號編號": sym_n, "題型": ver}  # 版本欄=題型名(如KK音選字)

    # 一般格式：版本_年度_冊編號_單元_課編號_句編號
    # body = [版本, 年度, 冊編號, 單元, 課編號, 句編號]
    # 版本可能含空格如 "wonder world" → 已被 _ 分割
    # 策略：從尾端取句編號、課編號（數字），往前找單元（非數字），再往前找冊（數字）、年度（3位數字）、其餘=版本

    # 從尾端開始拆
    rev = list(reversed(body))
    sent   = rev[0] if len(rev) > 0 and _try_int(rev[0]) else ""
    course = rev[1] if len(rev) > 1 and _try_int(rev[1]) else ""

    # 找單元：往後第一個非數字
    unit_val = ""
    unit_idx = -1
    for i in range(2, len(rev)):
        if not _try_int(rev[i]):
            unit_val = rev[i]
            unit_idx = i
            break

    # 找冊號：單元之後第一個數字
    册号 = ""
    nendo = ""
    ver_parts = []
    if unit_idx >= 0:
        after_unit = rev[unit_idx+1:]
        nums_after = [p for p in after_unit if _try_int(p)]
        non_nums   = [p for p in after_unit if not _try_int(p)]
        ver_parts  = list(reversed(non_nums))
        if len(nums_after) >= 2:
            nendo = nums_after[1]  # 年度（較大）
            册号  = nums_after[0]  # 冊號
        elif len(nums_after) == 1:
            n = nums_after[0]
            if len(n) >= 3:
                nendo = n
            else:
                册号 = n
    else:
        # 沒找到單元，用全部
        all_nums  = [p for p in body if _try_int(p)]
        ver_parts = [p for p in body if not _try_int(p)]
        nendo = all_nums[0] if len(all_nums) > 0 and len(all_nums[0]) >= 3 else ""
        册号  = all_nums[1] if len(all_nums) > 1 else ""

    version = "_".join(ver_parts)
    version = re.sub(r'^[A-Za-z]_', '', version)
    version = version.replace('ㄧ', '一')

    # 題型：有前綴用前綴對應，否則用單元名稱找
    if prefix:
        qtype = prefix_to_type[prefix]
        # 修正：若 qtype=拼單字 但單元是單字重組，維持單字重組題型
        if unit_val in _QTYPE_SHEETS:
            qtype = unit_val
    else:
        # 無前綴：單元名稱就是題型
        qtype = unit_val if unit_val in _QTYPE_SHEETS else None
        if not qtype:
            return None

    return {"版本": version, "年度": nendo, "冊編號": 册号,
            "單元": unit_val, "課編號": course, "句編號": sent, "題型": qtype}

def _norm(x):
    s = str(x).strip()
    try: return str(int(float(s)))
    except: return s

def _try_int(s):
    try: int(float(s)); return True
    except: return False

_WEEKDAY_CN = ["一","二","三","四","五","六","日"]

def _fmt_time_with_weekday(t_str):
    """把時間字串轉成 '04-16(三) 15:09:32'"""
    try:
        dt = pd.to_datetime(str(t_str)[:19])
        wd = _WEEKDAY_CN[dt.weekday()]
        return dt.strftime(f"%m-%d({wd}) %H:%M:%S")
    except:
        return str(t_str)[:19]

def _clean_task_name(name: str) -> str:
    """去掉任務名稱第一個全形空格後的所有內容"""
    s = str(name)
    idx = s.find('\u3000')
    if idx != -1:
        s = s[:idx]
    return s.strip()

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
                if col in p and col in df.columns and p[col] != "":
                    val = str(p[col]).strip()
                    mask &= df[col].apply(lambda x: _norm(x).replace('ㄧ','一')) == _norm(val).replace('ㄧ','一')
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
        with st.form("login_form"):
            pwd = st.text_input("密碼", type="password", key="dash_pwd")
            submitted = st.form_submit_button("登入", use_container_width=True, type="primary")
            if submitted:
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

st.divider()

# ── Tab ───────────────────────────────────────────────────────────────────────
tab_report, tab_tasks = st.tabs(["📋 全能英文學習報告", "📋 學生任務列表"])

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
    def _build_qid_task_map(df_a, stu_name=None):
        """建立 qid → 任務名稱，若指定 stu_name 只比對該學生被指派的任務"""
        qid_task = {}
        if df_a.empty or "題目ID清單" not in df_a.columns:
            return qid_task
        for _, row in df_a.iterrows():
            # 若指定學生，只用該學生的任務
            if stu_name:
                assigned = [s.strip() for s in str(row.get("指派學生","")).split(",") if s.strip()]
                if stu_name not in assigned:
                    continue
            tname = _short_task_name(str(row.get("任務名稱","")))
            for q in str(row.get("題目ID清單","")).split(","):
                q = q.strip()
                if q:
                    qid_task[q] = tname
                    qid_task[re.sub(r'^[A-Za-z]_','',q)] = tname
        return qid_task

    # ── 時間選擇（同數據監控）──────────────────────────────────────────────
    PERIODS_RPT = ["今日", "昨天", "前天", "三天", "七天", "30天"]
    if "rpt_period" not in st.session_state:
        st.session_state["rpt_period"] = "七天"

    rpt_cols = st.columns(len(PERIODS_RPT))
    for i, p in enumerate(PERIODS_RPT):
        if rpt_cols[i].button(p, key=f"rpt_p_{p}",
                              type="primary" if st.session_state["rpt_period"]==p else "secondary",
                              use_container_width=True):
            st.session_state["rpt_period"] = p
            st.rerun()

    # 自訂時間
    with st.expander("📅 自訂時間範圍"):
        rc1, rc2, rc3 = st.columns([2, 2, 1])
        rpt_from_custom = rc1.date_input("開始", value=date.today(), key="rpt_custom_from_inp")
        rpt_to_custom   = rc2.date_input("結束", value=date.today(), key="rpt_custom_to_inp")
        if rc3.button("套用", key="rpt_custom_apply", use_container_width=True):
            st.session_state["rpt_custom_from"] = rpt_from_custom
            st.session_state["rpt_custom_to"]   = rpt_to_custom
            st.session_state["rpt_period"]       = "自訂"
            st.rerun()

    period_rpt = st.session_state["rpt_period"]
    today = date.today()
    _rpt_d_map = {
        "今日": (today, today),
        "昨天": (today - timedelta(days=1), today - timedelta(days=1)),
        "前天": (today - timedelta(days=2), today - timedelta(days=2)),
        "三天": (today - timedelta(days=2), today),
        "七天": (today - timedelta(days=6), today),
        "30天": (today - timedelta(days=29), today),
        "自訂": (st.session_state.get("rpt_custom_from", today),
                 st.session_state.get("rpt_custom_to",   today)),
    }
    rpt_from, rpt_to = _rpt_d_map.get(period_rpt, (today, today))
    rpt_from_str = rpt_from.strftime("%Y-%m-%d")
    rpt_to_str   = rpt_to.strftime("%Y-%m-%d")
    st.caption(f"📅 {period_rpt}：{rpt_from_str} ～ {rpt_to_str}")

    st.divider()
    st.divider()

    # 預先建立所有學生的 qid→任務 對應（一次完成）
    @st.cache_data(ttl=600)
    def _build_all_stu_task_map(assign_json: str):
        import json
        rows = json.loads(assign_json)
        stu_map = {}
        for row in rows:
            tname    = row.get("任務名稱", "")
            m = re.search(r'-20\d{2}-\d{2}-\d{2}[_\-]', tname)
            if m: tname = tname[:m.start()].strip()
            assigned = [s.strip() for s in str(row.get("指派學生","")).split(",") if s.strip()]
            qids     = [q.strip() for q in str(row.get("題目ID清單","")).split(",") if q.strip()]
            for stu in assigned:
                if stu not in stu_map:
                    stu_map[stu] = {}
                for q in qids:
                    q2 = re.sub(r'^[A-Za-z]_', '', q)
                    stu_map[stu][q]  = tname
                    stu_map[stu][q2] = tname
        return stu_map

    def _get_task_for_stu(stu, qid, all_stu_task):
        m  = all_stu_task.get(stu, {})
        q  = str(qid).strip()
        q2 = re.sub(r'^[A-Za-z]_', '', q)
        return m.get(q, m.get(q2, ""))

    def _render_detail(tdf):
        """顯示詳細答題清單，格式同數據監控"""
        detail = tdf.copy().reset_index(drop=True)
        detail = detail.fillna("").astype(str)
        # 按時間降冪排列
        if "時間" in detail.columns:
            try:
                detail = detail.sort_values("時間", ascending=False).reset_index(drop=True)
            except:
                pass
        if "時間" in detail.columns:
            detail["時間"] = detail["時間"].apply(_fmt_time_with_weekday)
        if "學生答案" in detail.columns:
            detail["學生答案"] = detail["學生答案"].str.lower()
        if "題目ID" in detail.columns:
            orig_qids = detail["題目ID"].tolist()
            q_lookup  = build_question_lookup(tuple(set(orig_qids)))
            detail["正確答案"] = [q_lookup.get(q, {}).get("答案", "") for q in orig_qids]
            detail["題目ID"]   = [q_lookup.get(q, {}).get("題目", q) for q in orig_qids]
        if "答題秒數" in detail.columns:
            detail["答題時間"] = detail["答題秒數"].apply(_fmt_elapsed)
        ordered = [c for c in ["時間","題目ID","結果","學生答案","正確答案","答題時間"] if c in detail.columns]
        col_cfg_d = {}
        if "時間"     in detail.columns: col_cfg_d["時間"]     = st.column_config.TextColumn("時間",     width=70)
        if "結果"     in detail.columns: col_cfg_d["結果"]     = st.column_config.TextColumn("結果",     width=30)
        if "學生答案" in detail.columns: col_cfg_d["學生答案"] = st.column_config.TextColumn("學生答案", width=30)
        if "正確答案" in detail.columns: col_cfg_d["正確答案"] = st.column_config.TextColumn("正確答案", width=30)
        if "題目ID"   in detail.columns: col_cfg_d["題目ID"]   = st.column_config.TextColumn("題目",     width=None)
        if "答題時間" in detail.columns: col_cfg_d["答題時間"] = st.column_config.TextColumn("答題時間", width=60)
        st.dataframe(detail[ordered], use_container_width=True, hide_index=True, column_config=col_cfg_d)

    def _fmt_elapsed(sec_val):
        """把秒數格式化為 m:ss 或 ss秒"""
        try:
            s = int(float(str(sec_val)))
            if s <= 0: return ""
            if s >= 60:
                return f"{s//60}分{s%60:02d}秒"
            return f"{s}秒"
        except:
            return ""

    def _sum_elapsed(tdf):
        """計算一組答題的總秒數"""
        if "答題秒數" not in tdf.columns:
            return ""
        try:
            total = pd.to_numeric(tdf["答題秒數"], errors="coerce").fillna(0).sum()
            return _fmt_elapsed(total)
        except:
            return ""
        """產生單一學生的報告行"""
        stu_ans = stu_ans.copy()
        stu_ans["_task"] = stu_ans["題目ID"].apply(lambda x: _get_task_for_stu(stu, x, all_stu_task))
        stu_ans = stu_ans[stu_ans["_task"] != ""]
        if stu_ans.empty:
            return []
        stu_ans["_date"] = stu_ans["時間"].str[:10]
        sy = stu_sy_map.get(stu, "")
        lines = [f"【{stu}】{sy}", f"{from_str} ～ {to_str}"]
        for day in sorted(stu_ans["_date"].unique(), reverse=True):
            day_df = stu_ans[stu_ans["_date"] == day]
            try:
                dt = pd.to_datetime(day)
                wd = ["一","二","三","四","五","六","日"][dt.weekday()]
                day_label = f"{day}（{wd}）"
            except:
                day_label = day
            lines.append(f"\n📅 {day_label}")
            for tname, tdf in day_df.groupby("_task"):
                prac_tot  = len(tdf[tdf["結果"] == "練習"])
                test_df   = tdf[tdf["結果"].isin(["✅","❌"])]
                test_ok   = len(test_df[test_df["結果"]=="✅"])
                test_err  = len(test_df[test_df["結果"]=="❌"])
                test_tot  = len(test_df)
                elapsed   = _sum_elapsed(tdf)
                lines.append(f"{tname}")
                if test_tot > 0:
                    lines.append(f"  測驗：{test_tot}題　✅{test_ok}　❌{test_err}")
                if prac_tot > 0:
                    lines.append(f"  練習：{prac_tot}題")
                if elapsed:
                    lines.append(f"  作答時間：{elapsed}")
        lines.append("")
        return lines

    # ════════════════════════════════════════════
    # 統一學生報告（全班+個別更新）
    # ════════════════════════════════════════════
    st.caption("依學生列出各任務答題統計，可展開查看詳細清單，每個學生可個別即時更新")

    # 取得學生清單（含無資料的也列出）
    df_stu_rpt = load_supabase_students()
    stu_sy_map = {}
    students_all = []
    if not df_stu_rpt.empty and "name" in df_stu_rpt.columns:
        stu_sy_map = {str(r["name"]): str(r.get("school_year","")) for _, r in df_stu_rpt.iterrows()}
        df_stu_rpt["_sy"] = pd.to_numeric(df_stu_rpt.get("school_year", pd.Series()), errors="coerce")
        df_stu_rpt = df_stu_rpt[~df_stu_rpt["group_id"].isin(["ADMIN","TEACHER"])].sort_values("_sy", ascending=True)
        students_all = df_stu_rpt["name"].tolist()

    # 全班更新按鈕 + 全部折疊按鈕
    _auto_gen = "rpt_stu_data" not in st.session_state
    _btn_c1, _btn_c2 = st.columns([3, 1])
    if _btn_c1.button("🔄 產生全班報告-即時更新", type="primary", key="gen_all", use_container_width=True) or _auto_gen:
        load_assignments.clear()
        df_a_fresh = load_assignments()
        _assign_json = df_a_fresh.to_json(orient="records") if not df_a_fresh.empty else "[]"
        _all_stu_task = _build_all_stu_task_map(_assign_json)
        st.session_state["rpt_assign_json"] = _assign_json

        # 全班一次撈
        load_logs.clear()
        df_l_fresh = load_logs()
        df_rpt = df_l_fresh.copy() if not df_l_fresh.empty else pd.DataFrame()
        if not df_rpt.empty and "時間" in df_rpt.columns:
            df_rpt = df_rpt[(df_rpt["時間"].str[:10] >= rpt_from_str) & (df_rpt["時間"].str[:10] <= rpt_to_str)]
        df_rpt_ans = df_rpt[~df_rpt["結果"].str.contains("📖", na=False)] if not df_rpt.empty and "結果" in df_rpt.columns else pd.DataFrame()

        stu_data = {}
        for stu in students_all:
            stu_ans = df_rpt_ans[df_rpt_ans["姓名"] == stu].copy() if not df_rpt_ans.empty else pd.DataFrame()
            if not stu_ans.empty:
                stu_ans["_task"] = stu_ans["題目ID"].apply(lambda x: _get_task_for_stu(stu, x, _all_stu_task))
                stu_ans = stu_ans[stu_ans["_task"] != ""]
                stu_ans["_date"] = stu_ans["時間"].str[:10]
            stu_data[stu] = stu_ans.to_dict("records") if not stu_ans.empty else []
        st.session_state["rpt_stu_data"]  = stu_data
        st.session_state["rpt_all_range"] = (rpt_from_str, rpt_to_str)

    # 折疊按鈕
    if _btn_c2.button("⬆️ 全部折疊", key="collapse_all", use_container_width=True):
        st.session_state["rpt_collapse_ver"] = st.session_state.get("rpt_collapse_ver", 0) + 1
        st.rerun()

    # 顯示學生清單
    if "rpt_stu_data" in st.session_state:
        _from, _to = st.session_state.get("rpt_all_range", (rpt_from_str, rpt_to_str))
        _assign_json = st.session_state.get("rpt_assign_json", "[]")
        _all_stu_task = _build_all_stu_task_map(_assign_json)
        _cv = st.session_state.get("rpt_collapse_ver", 0)

        for stu in students_all:
            sy = stu_sy_map.get(stu, "")
            stu_records = st.session_state["rpt_stu_data"].get(stu, [])
            stu_df = pd.DataFrame(stu_records)
            has_data = not stu_df.empty
            if has_data and "_date" in stu_df.columns:
                latest_date = stu_df["_date"].max()
                try:
                    dt = pd.to_datetime(latest_date)
                    wd = _WEEKDAY_CN[dt.weekday()]
                    latest_str = f"　最新：{latest_date[5:]}（{wd}）"
                except:
                    latest_str = f"　最新：{latest_date}"
            else:
                latest_str = ""
            _invis = "\u200b" * _cv
            label = f"【{stu}】{sy}{_invis}" + (f"　📝{len(stu_df)}筆{latest_str}" if has_data else "　（本期無資料）")

            with st.expander(label, expanded=False):
                # 個別更新按鈕
                _rc1, _rc2 = st.columns([5, 1])
                _rc1.caption(f"{_from} ～ {_to}")
                if _rc2.button("🔄 更新", key=f"stu_refresh_{stu}", use_container_width=True):
                    # 只撈這位學生
                    df_stu_fresh = load_logs_for_student(stu)
                    df_stu_r = df_stu_fresh.copy() if not df_stu_fresh.empty else pd.DataFrame()
                    if not df_stu_r.empty and "時間" in df_stu_r.columns:
                        df_stu_r = df_stu_r[(df_stu_r["時間"].str[:10] >= rpt_from_str) & (df_stu_r["時間"].str[:10] <= rpt_to_str)]
                    df_stu_ans = df_stu_r[~df_stu_r["結果"].str.contains("📖", na=False)] if not df_stu_r.empty and "結果" in df_stu_r.columns else pd.DataFrame()
                    if not df_stu_ans.empty:
                        df_stu_ans["_task"] = df_stu_ans["題目ID"].apply(lambda x: _get_task_for_stu(stu, x, _all_stu_task))
                        df_stu_ans = df_stu_ans[df_stu_ans["_task"] != ""]
                        df_stu_ans["_date"] = df_stu_ans["時間"].str[:10]
                    st.session_state["rpt_stu_data"][stu] = df_stu_ans.to_dict("records") if not df_stu_ans.empty else []
                    st.rerun()

                if not has_data:
                    st.info("本期無答題資料")
                else:
                    for day in sorted(stu_df["_date"].unique(), reverse=True):
                        day_df = stu_df[stu_df["_date"] == day]
                        # 該日所有任務作答時間總和
                        day_elapsed = _sum_elapsed(pd.DataFrame(day_df))
                        try:
                            dt = pd.to_datetime(day)
                            wd = ["一","二","三","四","五","六","日"][dt.weekday()]
                            day_label = f"**📅 {day}（{wd}）**"
                        except:
                            day_label = f"**📅 {day}**"
                        if day_elapsed:
                            day_label += f"　⏱ {day_elapsed}"
                        st.markdown(day_label)
                        for tname, tdf in day_df.groupby("_task"):
                            prac_tot = len(tdf[tdf["結果"] == "練習"])
                            test_df  = tdf[tdf["結果"].isin(["✅","❌"])]
                            test_ok  = len(test_df[test_df["結果"]=="✅"])
                            test_err = len(test_df[test_df["結果"]=="❌"])
                            test_tot = len(test_df)
                            elapsed  = _sum_elapsed(pd.DataFrame(tdf))
                            summary  = f"{tname}"
                            if test_tot > 0: summary += f"　測驗{test_tot}題 ✅{test_ok} ❌{test_err}"
                            if prac_tot > 0: summary += f"　練習{prac_tot}題"
                            if elapsed:      summary += f"　⏱{elapsed}"
                            with st.expander(summary, expanded=False):
                                _render_detail(pd.DataFrame(tdf) if isinstance(tdf, dict) else tdf)




# ══════════════════════════════════════════════════════════════════════════════
# Tab2：學生任務列表
# ══════════════════════════════════════════════════════════════════════════════
with tab_tasks:
    t3c1, t3c2, t3c3 = st.columns([4, 1, 1])
    if t3c3.button("🔄 更新", key="t3_refresh", use_container_width=True):
        load_assignments.clear()
        load_supabase_students.clear()
        st.rerun()

    df_a_t3   = load_assignments()
    df_stu_t3 = load_supabase_students()
    t3c2.caption(f"任務: {len(df_a_t3)} 個")

    df_active = df_a_t3[df_a_t3["狀態"] == "進行中"].copy() if not df_a_t3.empty and "狀態" in df_a_t3.columns else pd.DataFrame()

    if df_stu_t3.empty:
        st.info("無學生資料")
    elif df_active.empty:
        st.info("目前沒有進行中的任務")
    else:
        def _get_active_tasks_for_student(stu_name):
            tasks = []
            for _, row in df_active.iterrows():
                assigned = [s.strip() for s in str(row.get("指派學生","")).split(",") if s.strip()]
                if stu_name in assigned:
                    tname    = _clean_task_name(str(row.get("任務名稱","")))
                    end_date = str(row.get("結束日期",""))[:10]
                    task_type= str(row.get("類型",""))
                    tasks.append({"任務名稱": tname, "類型": task_type, "結束日期": end_date})
            return tasks

        groups = sorted(df_stu_t3["group_id"].unique().tolist())
        for grp in groups:
            stu_in_grp = df_stu_t3[df_stu_t3["group_id"] == grp]["name"].tolist()
            grp_has_tasks = any(_get_active_tasks_for_student(n) for n in stu_in_grp)
            if not grp_has_tasks:
                continue
            st.markdown(f"#### 班級：{grp}")
            for stu_name in stu_in_grp:
                tasks = _get_active_tasks_for_student(stu_name)
                if not tasks:
                    continue
                stu_row = df_stu_t3[df_stu_t3["name"] == stu_name].iloc[0] if not df_stu_t3[df_stu_t3["name"] == stu_name].empty else None
                account = str(stu_row["account"]) if stu_row is not None and "account" in df_stu_t3.columns else ""
                label   = f"{stu_name}（{account}）　📋 {len(tasks)} 個進行中任務"
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
st.caption(f"英文全能練習系統 學習報告 V{DASHBOARD_VERSION}　© 2026")
