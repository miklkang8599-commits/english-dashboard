# ╔══════════════════════════════════════════════════════════╗
# ║  英文全能練習系統 — 全班學習報告 (獨立版)                ║
# ║  dashboard.py  V2.47                                     ║
# ╚══════════════════════════════════════════════════════════╝

import streamlit as st
import pandas as pd
import re
from datetime import date, datetime, timedelta
from supabase import create_client, Client
from streamlit_gsheets import GSheetsConnection

st.set_page_config(
    page_title="英文全能 — 學習報告",
    page_icon="📋",
    layout="wide"
)

# 每30秒心跳，防止 Streamlit session 閒置過期
@st.fragment(run_every=30)
def _keepalive():
    # 更新心跳時間戳，確保 session 保持活躍
    st.session_state["_heartbeat"] = datetime.now().isoformat()

_keepalive()

# ── 常數 ──────────────────────────────────────────────────────────────────────
DASHBOARD_VERSION = "2.47"

LOGS_COLS = {
    "created_at": "時間", "name": "姓名", "group_id": "分組",
    "question_id": "題目ID", "result": "結果",
    "student_answer": "學生答案", "score": "分數", "task_name": "任務名稱",
    "elapsed_sec": "答題秒數",
    "practice_mode": "練習方式", "session_start": "開始時間",   # V2.04（app V2.9.540 起寫入）
}
_LOG_BASE_FIELDS  = "created_at,name,group_id,question_id,result,student_answer,score,task_name,elapsed_sec"
_LOG_EXTRA_FIELDS = "practice_mode,session_start"
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
@st.cache_data(ttl=180)  # V2.38：30 秒 → 3 分鐘（按「立即更新」會清掉）
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

def load_logs_for_student(stu_name: str, date_from: str = None) -> pd.DataFrame:
    """V2.38：30 天內的查詢共用同一份（同一學生暫存 45 秒），8 天總覽和歷次作答只查一次 Supabase"""
    try:
        _base = (get_now().date() - timedelta(days=29)).strftime("%Y-%m-%d")
    except Exception:
        _base = None
    if _base and date_from and date_from >= _base:
        df = _load_logs_for_student_raw(stu_name, _base)
        if not df.empty and "時間" in df.columns:
            df = df[df["時間"].astype(str).str[:10] >= date_from]
        return df
    return _load_logs_for_student_raw(stu_name, date_from)

@st.cache_data(ttl=45, show_spinner=False)
def _load_logs_for_student_raw(stu_name: str, date_from: str = None) -> pd.DataFrame:
    """只撈單一學生的 logs（V2.38 起暫存 45 秒）
    date_from：'YYYY-MM-DD'，只撈這天以後的紀錄（None = 全部）
    若 Supabase 已新增 practice_mode / session_start 欄位，一併取回"""
    def _fetch(fields):
        sb  = get_supabase()
        rows = []
        page = 0
        while True:
            q = sb.table("logs").select(fields).eq("name", stu_name)
            if date_from:
                q = q.gte("created_at", date_from)
            res = q.order("created_at", desc=False).range(page*1000, (page+1)*1000-1).execute()
            if not res.data:
                break
            rows.extend(res.data)
            if len(res.data) < 1000:
                break
            page += 1
        return rows
    try:
        # V2.06：每次都先試新欄位（不再一直記住「沒有欄位」，避免 SQL 執行後仍顯示推測）
        try:
            all_logs = _fetch(_LOG_BASE_FIELDS + "," + _LOG_EXTRA_FIELDS)
            st.session_state["_no_session_cols"] = False
        except Exception as e:
            if "practice_mode" in str(e) or "session_start" in str(e):
                st.session_state["_no_session_cols"] = True
                all_logs = _fetch(_LOG_BASE_FIELDS)
            else:
                raise
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

# V2.22：讀取失敗時不再把「空名單」快取 10 分鐘；會自動重試一次，並記下錯誤原因
@st.cache_data(ttl=600, show_spinner=False)
def _load_students_cached():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df   = conn.read(worksheet="students", ttl=600).fillna("").astype(str)
    if df.empty:
        raise RuntimeError("students 工作表沒有資料")
    return df

def load_students():
    for _try in range(2):
        try:
            df = _load_students_cached()
            st.session_state.pop("_students_err", None)
            return df
        except Exception as e:
            st.session_state["_students_err"] = f"{type(e).__name__}: {e}"[:300]
            _load_students_cached.clear()
            if _try == 0:
                import time as _t_retry
                _t_retry.sleep(1.5)
    return pd.DataFrame()

load_students.clear = _load_students_cached.clear

def _students_load_failed(key: str):
    _err = st.session_state.get("_students_err", "")
    st.warning("讀不到 students 工作表" + (f"（{_err}）" if _err else "（工作表沒有「姓名」欄）"))
    if st.button("🔄 重新讀取學生名單", key=f"stu_reload_{key}"):
        load_students.clear()
        st.rerun()

# 題型工作表對應：content=題目欄, answer=答案欄
_QTYPE_SHEETS = {
    "單選":    {"sheet": "單選",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "單選題目",        "answer": "單選答案",        "prefix": ""},
    "文意文法":{"sheet": "單選",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "單選題目",        "answer": "單選答案",        "prefix": ""},
    "重組":    {"sheet": "重組",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "重組中文題目",     "answer": "重組英文答案",    "prefix": ""},
    "閱讀重組":{"sheet": "重組",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "重組中文題目",     "answer": "重組英文答案",    "prefix": ""},
    "對話重組":{"sheet": "重組",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "重組中文題目",     "answer": "重組英文答案",    "prefix": ""},
    "閱讀單句":{"sheet": "閱讀單句","key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "題目",            "answer": "答案",            "prefix": "RM"},
    "朗讀":    {"sheet": "朗讀",    "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "朗讀句子",        "answer": "",                "prefix": "R"},
    "拼單字":  {"sheet": "拼單字",  "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "英文單字",        "answer": "中文意思",        "prefix": "V"},
    "單字重組":{"sheet": "拼單字",  "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "中文意思",        "answer": "英文單字",        "prefix": "V"},
    "歷屆大學":{"sheet": "拼單字",  "key": ["版本","年度","冊編號","單元","課編號","句編號"], "content": "中文意思",        "answer": "英文單字",        "prefix": "V"},
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
    解析 question_id，格式來自 app.py，固定結構（版本不含底線）：
      無前綴：版本_年度_冊編號_單元_課編號_句編號  (重組/單選/對話重組/閱讀重組等)
      R_    ：R_版本_年度_冊編號_單元_課編號_句編號 (朗讀)
      RM_   ：RM_版本_年度_冊編號_單元_課編號_句編號 (閱讀單句)
      V_    ：V_版本_年度_冊編號_單元_課編號_句編號  (拼單字/單字重組/歷屆大學等)
      LS_   ：LS_版本_年度_冊編號_單元_課編號_句編號 (聽力重組)
      LP_   ：LP_版本_單元編號_組編號_符號編號       (聽力音標)
    注意：版本欄位可能含空格（如 'wonder world'），但不含底線；
          冊編號可能是字母（如 'A'）；課編號可能是日期格式（如 '01-10'）。
    採固定位置拆解，不依賴猜測數字/文字。
    """
    s     = str(qid).strip()
    parts = s.split("_")

    prefix_to_type = {
        "R":  "朗讀",
        "RM": "閱讀單句",
        "V":  "拼單字",
        "LS": "聽力重組",
        "LP": "聽力音標",
    }

    prefix = ""
    body   = parts
    if parts and parts[0] in prefix_to_type:
        prefix = parts[0]
        body   = parts[1:]

    # LP 聽力音標：[版本, 單元編號, 組編號, 符號編號]
    if prefix == "LP":
        ver    = body[0] if len(body) > 0 else ""
        unit_n = body[1] if len(body) > 1 else ""
        grp_n  = body[2] if len(body) > 2 else ""
        sym_n  = body[3] if len(body) > 3 else ""
        return {"版本": ver, "單元編號": unit_n, "組編號": grp_n,
                "符號編號": sym_n, "題型": ver}

    # 一般格式固定 6 個位置：[版本, 年度, 冊編號, 單元, 課編號, 句編號]
    if len(body) < 6:
        # 容錯：位置不足時退回舊邏輯（極少數情況）
        if len(body) == 0:
            return None
        version, nendo, vol, unit_val, course, sent = (body + [""]*6)[:6]
    else:
        # 若超過6個位置，代表版本內含底線，最前面多出的都算版本一部分
        extra = len(body) - 6
        version = "_".join(body[:1+extra])
        nendo, vol, unit_val, course, sent = body[1+extra:6+extra]

    version = re.sub(r'^[A-Za-z]_', '', version)
    version = version.replace('ㄧ', '一')

    if prefix:
        qtype = prefix_to_type[prefix]
        if unit_val in _QTYPE_SHEETS:
            qtype = unit_val
    else:
        qtype = unit_val if unit_val in _QTYPE_SHEETS else None
        if not qtype:
            return None

    return {"版本": version, "年度": nendo, "冊編號": vol,
            "單元": unit_val, "課編號": course, "句編號": sent, "題型": qtype}


def _norm(x):
    s = str(x).strip()
    try:
        return str(int(float(s)))
    except:
        pass
    # 處理日期格式：把完整日期正規化為 MM-DD 以便和 question_id 比對
    m = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})', s)
    if m:
        return f"{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s

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

def _render_detail(tdf, key=None):
    """顯示詳細答題清單，格式同數據監控（V2.41：給 key 時可點一題跳出題目內容）"""
    detail = tdf.copy().reset_index(drop=True)
    detail = detail.fillna("").astype(str)
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
        # V2.29：英選中＝看英文、選中文 → 題目顯示英文，正確答案顯示中文
        _cjk = r'[\u4e00-\u9fff]'
        _ec = (detail["題目ID"].str.contains(_cjk, regex=True, na=False)
               & (detail["正確答案"] != "")
               & ~detail["正確答案"].str.contains(_cjk, regex=True, na=False))
        _hint = pd.Series(False, index=detail.index)
        if "練習方式" in detail.columns:
            _hint |= detail["練習方式"].str.contains("英選中", na=False)
        if "學生答案" in detail.columns:
            _hint |= detail["學生答案"].str.contains(_cjk, regex=True, na=False)
        _ec &= _hint
        # V2.42：只有單字題才會「英選中」對調（單選題目有中文、學生答案「原始(b)→顯示(b)」也有中文，不能對調）
        _ec &= pd.Series([_qcat(q) == "單字" for q in orig_qids], index=detail.index)
        if _ec.any():
            _q_en = detail.loc[_ec, "正確答案"].copy()
            detail.loc[_ec, "正確答案"] = detail.loc[_ec, "題目ID"]
            detail.loc[_ec, "題目ID"] = _q_en
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
    if key and "題目ID" in tdf.columns:
        # V2.47：點一題只重畫這張表（不會整份報告、8 天總覽一起變灰重跑），選另一題直接換過去
        try:
            _detail_sel_frag(detail[ordered], col_cfg_d, orig_qids, _qv_ans_map(tdf), key)
        except Exception as _e:
            if type(_e).__name__ in ("StopException", "RerunException", "RerunData"):
                raise
            _detail_sel(detail[ordered], col_cfg_d, orig_qids, _qv_ans_map(tdf), key)   # 舊版不能巢狀 fragment
        return
    st.dataframe(detail[ordered], use_container_width=True, hide_index=True, column_config=col_cfg_d)

def _detail_sel(view, cfg, qids, ans_map, key):
    """V2.47：作答明細表（一次選一題）→ 選的題目換了才跳出視窗"""
    st.caption("👆 點表格最左邊的小方框選一題，會跳出英文題目、選項、中文翻譯和解析（閱讀題整篇一起看）；選另一題會直接換過去")
    try:
        ev = st.dataframe(view, use_container_width=True, hide_index=True, column_config=cfg,
                          on_select="rerun", selection_mode="single-row", key=f"qv_{key}")
    except TypeError:
        st.dataframe(view, use_container_width=True, hide_index=True, column_config=cfg)
        return
    try:
        _sel = [int(i) for i in ev.selection.rows]
    except Exception:
        _sel = []
    cur = _sel[0] if _sel and 0 <= _sel[0] < len(qids) else None
    if cur != st.session_state.get(f"_qv_last_{key}"):
        st.session_state[f"_qv_last_{key}"] = cur
        if cur is not None:
            _qv_open(qids[cur], ans_map)


@st.fragment
def _detail_sel_frag(view, cfg, qids, ans_map, key):
    _detail_sel(view, cfg, qids, ans_map, key)

# ── V2.41：作答明細點一題 → 跳出視窗看英文題目、選項、中文翻譯、解析（閱讀題整個題組一起）──
_QV_CSS = """<style>
.qv-en, .qv-zh { font-size:1.02rem; line-height:1.6; }
.qv-en p, .qv-zh p { margin:0 0 .6em; }
.qv-en .rm-tbl { overflow-x:auto; }
.qv-en table { border-collapse:collapse; font-size:.85rem; width:100%; max-width:520px; }
.qv-en th, .qv-en td { border:1px solid rgba(128,128,128,.45); padding:3px 5px; text-align:center; }
.qv-en .rm-chat { display:flex; flex-direction:column; gap:6px; }
.qv-en .rm-msg { max-width:82%; padding:5px 11px; border-radius:12px; border:1px solid rgba(128,128,128,.35); line-height:1.4; }
.qv-en .rm-msg.l { align-self:flex-start; }
.qv-en .rm-msg.r { align-self:flex-end; background:rgba(13,106,110,.12); }
.qv-en .rm-who { display:block; font-size:.7rem; opacity:.7; }
.qv-psg { padding-bottom:8px; margin-bottom:4px; border-bottom:1px dashed rgba(128,128,128,.45); }
.qv-item { margin-top:8px; padding:6px 9px; border-radius:8px; border:1px solid rgba(128,128,128,.3); }
.qv-cur { border:2px solid #f59e0b; }
.qv-opt { padding:1px 0 1px 8px; }
.qv-ok { color:#30a46c; font-weight:600; }
.qv-bad { color:#e5484d; font-weight:600; }
</style>"""

def _qv_key(sheet, vals) -> str:
    return sheet + "#" + "|".join(_norm(v).replace("ㄧ", "一") for v in vals)

def _qv_num(x):
    try:
        return float(str(x).strip())
    except Exception:
        return 0.0

def _qv_txt(s) -> str:
    """純文字 → HTML（跳脫、換行變 <br>）"""
    import html as _h
    return _h.escape(str(s or "").strip()).replace("\n", "<br>")

def _qv_rich(s) -> str:
    """題庫本來就有 HTML（文章表格、<u> 底線）→ 保留標籤，只處理換行"""
    s = str(s or "").strip()
    if not re.search(r"<(table|div|p|ul|ol)\b", s, re.I):
        s = s.replace("\n", "<br>")
    return s.replace("\r", "").replace("\n", " ")

def _qv_html(s: str) -> str:
    return s.replace("$", "&#36;")

@st.cache_resource(ttl=3600, show_spinner=False)
def _qv_index(sheet_name: str, key_cols: tuple) -> dict:
    """題庫索引（全 App 共用、1 小時更新）：key → 列號；題組 → 列號清單"""
    out = {"df": None, "rows": {}, "groups": {}}
    try:
        df = load_question_sheet(sheet_name)
    except Exception:
        return out
    if df is None or df.empty or any(c not in df.columns for c in key_cols):
        return out
    df = df.reset_index(drop=True)
    out["df"] = df
    for i, vals in enumerate(df[list(key_cols)].itertuples(index=False)):
        out["rows"].setdefault(_qv_key(sheet_name, vals), i)
    if "題組" in df.columns:
        for i, g in enumerate(df["題組"].tolist()):
            g = str(g).strip()
            if g:
                out["groups"].setdefault(g, []).append(i)
    return out

def _qv_cfg(qid):
    p = _parse_qid(qid)
    if not p:
        return None, None
    cfg = _QTYPE_SHEETS.get(p.get("題型"))
    return p, cfg

def _qv_ans_map(tdf) -> dict:
    """這次作答每一題的（學生答案, 結果），用題庫 key 對應"""
    out = {}
    try:
        qs = tdf["題目ID"].astype(str).tolist()
        ans = tdf["學生答案"].fillna("").astype(str).tolist() if "學生答案" in tdf.columns else [""] * len(qs)
        res = tdf["結果"].fillna("").astype(str).tolist() if "結果" in tdf.columns else [""] * len(qs)
        for q, a, r in zip(qs, ans, res):
            p, cfg = _qv_cfg(q)
            if p and cfg:
                out[_qv_key(cfg["sheet"], [p.get(c, "") for c in cfg["key"]])] = (a, r)
    except Exception:
        pass
    return out

def _qv_show(qid, ans_map: dict):
    st.markdown(_QV_CSS, unsafe_allow_html=True)
    p, cfg = _qv_cfg(qid)
    idx = _qv_index(cfg["sheet"], tuple(cfg["key"])) if cfg else None
    df = idx["df"] if idx else None
    i = idx["rows"].get(_qv_key(cfg["sheet"], [p.get(c, "") for c in cfg["key"]])) if df is not None else None
    if i is None:
        st.warning("題庫裡找不到這一題（可能題目已修改或刪除）")
        st.caption(str(qid))
        return
    sheet = cfg["sheet"]
    r = df.iloc[i]

    def g(row, c):
        return str(row.get(c, "") or "").strip()

    src = "・".join(v for v in [g(r, "考卷年度"), g(r, "學校"), (g(r, "卷別") + "卷") if g(r, "卷別") else "", g(r, "文法")] if v)
    en, zh, ex, imgs = [], [], [], []
    n_head = 0
    if sheet == "閱讀單句":
        grp = g(r, "題組")
        rows_i = sorted(idx["groups"].get(grp, [i]) if grp else [i], key=lambda k: _qv_num(df.iloc[k]["句編號"]))
        st.caption(("📖 閱讀題組" if len(rows_i) > 1 else "📖 閱讀") + (f"（{src}）" if src else "") + f"　這篇共 {len(rows_i)} 題")
        passage = next((g(df.iloc[k], "答案") for k in rows_i if g(df.iloc[k], "答案")), "")
        full_zh = next((g(df.iloc[k], "全文翻譯") for k in rows_i if g(df.iloc[k], "全文翻譯")), "")
        if passage:
            en.append(f"<div class='qv-psg'>{_qv_rich(passage)}</div>")
        n_head = len(en)
        for k in rows_i:
            v = g(df.iloc[k], "圖片")
            if v and v not in imgs:
                imgs.append(v)
        if full_zh:
            zh.append(f"<div class='qv-psg'>{_qv_txt(full_zh)}</div>")
        for n, k in enumerate(rows_i, 1):
            rr = df.iloc[k]
            cor = g(rr, "正確選項列出").upper()
            sa, res = ans_map.get(_qv_key(sheet, [rr.get(c, "") for c in cfg["key"]]), ("", ""))
            sa = str(sa).strip().upper()
            cur = k == i
            ccls = " qv-cur" if cur else ""
            opts = []
            for o in "ABCD":
                t = g(rr, f"選項{o}")
                if not t:
                    continue
                if o == cor:
                    opts.append(f"<div class='qv-opt qv-ok'>✅ ({o}) {_qv_rich(t)}</div>")
                elif sa and o == sa:
                    opts.append(f"<div class='qv-opt qv-bad'>❌ ({o}) {_qv_rich(t)}</div>")
                else:
                    opts.append(f"<div class='qv-opt'>({o}) {_qv_rich(t)}</div>")
            en.append(f"<div class='qv-item{ccls}'><b>{'👉 ' if cur else ''}{n}. {_qv_rich(g(rr, '題目'))}</b>{''.join(opts)}</div>")
            if g(rr, "翻譯"):
                zh.append(f"<div class='qv-item{ccls}'><b>{n}.</b> {_qv_txt(g(rr, '翻譯'))}</div>")
            ex.append((n, cor, sa, res, g(rr, "解析"), cur))
        box_h = 380
    else:
        st.caption(f"📝 {p.get('題型') or sheet}" + (f"（{src}）" if src else ""))
        content = g(r, cfg["content"]) if cfg.get("content") else ""
        answer = g(r, cfg["answer"]) if cfg.get("answer") else ""
        sa, res = ans_map.get(_qv_key(sheet, [r.get(c, "") for c in cfg["key"]]), ("", ""))
        if content:
            en.append(f"<div class='qv-item qv-cur'>{_qv_txt(content)}</div>")
        if sheet != "單選" and answer:
            en.append(f"<div class='qv-opt qv-ok'>✅ 正確答案：{_qv_txt(answer)}</div>")
        if g(r, "中文翻譯"):
            zh.append(f"<div class='qv-item'>{_qv_txt(g(r, '中文翻譯'))}</div>")
        ex.append((0, answer if sheet == "單選" else "", str(sa).strip(), res, g(r, "解析"), True))
        box_h = 220

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🇬🇧 英文**")
        with st.container(height=box_h):
            if n_head:
                st.markdown(_qv_html("<div class='qv-en'>" + "".join(en[:n_head]) + "</div>"), unsafe_allow_html=True)
            for v in imgs:  # 文章圖片（Drive「0000-閱讀圖片」）
                _b = _qv_image(v)
                if _b:
                    try:
                        st.image(_b, use_container_width=True)
                    except TypeError:
                        st.image(_b)
                else:
                    st.caption(f"⚠️ 圖片讀取失敗：{v}")
            st.markdown(_qv_html("<div class='qv-en'>" + "".join(en[n_head:]) + "</div>"), unsafe_allow_html=True)
    with c2:
        st.markdown("**🈶 中文翻譯**")
        with st.container(height=box_h):
            st.markdown(_qv_html("<div class='qv-zh'>" + ("".join(zh) or "（這題沒有中文翻譯）") + "</div>"), unsafe_allow_html=True)
    st.markdown("**📝 解析**")
    for n, cor, sa, res, an, cur in ex:
        head = ("👉 " if cur and n else "") + (f"第 {n} 題　" if n else "")
        if cor:
            head += f"正確答案 {_qv_txt(cor)}"
        if sa:
            ok = (res == "✅") if res in ("✅", "❌") else (sa.upper() == cor.upper())
            head += f"　學生答 {_qv_txt(sa)} {'✅' if ok else '❌'}"
        elif n:
            head += "　（這次沒有作答這題）"
        st.markdown(_qv_html(f"<div class='qv-item{' qv-cur' if cur and n else ''}'><b>{head}</b><br>{_qv_txt(an) or '（沒有解析）'}</div>"),
                    unsafe_allow_html=True)

@st.cache_resource(show_spinner=False)
def _qv_drive():
    """用 gsheets 的服務帳號讀 Drive（唯讀），和練習系統讀閱讀圖片同一種方式"""
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import AuthorizedSession
    s = st.secrets["connections"]["gsheets"]
    info = {k: s.get(k, "") for k in ("project_id", "private_key_id", "private_key", "client_email", "client_id", "client_x509_cert_url")}
    info.update({"type": "service_account", "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                 "token_uri": "https://oauth2.googleapis.com/token",
                 "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"})
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return AuthorizedSession(creds)

_QV_IMG_FOLDER = "1m75ySBx_Q1li6Ke3MKg-qdL1_0a7J56g"  # Drive「0000-閱讀圖片」

@st.cache_data(ttl=600, show_spinner=False)
def _qv_img_index() -> dict:
    """{檔名小寫: file_id}"""
    out = {}
    try:
        ses, tok = _qv_drive(), None
        while True:
            prm = {"q": f"'{_QV_IMG_FOLDER}' in parents and trashed=false",
                   "fields": "nextPageToken,files(id,name)", "pageSize": 1000}
            if tok:
                prm["pageToken"] = tok
            j = ses.get("https://www.googleapis.com/drive/v3/files", params=prm, timeout=15).json()
            for f in j.get("files", []):
                out[str(f["name"]).strip().lower()] = f["id"]
            tok = j.get("nextPageToken")
            if not tok:
                break
    except Exception:
        pass
    return out

@st.cache_data(ttl=3600, show_spinner=False)
def _qv_img_bytes(fid: str):
    try:
        r = _qv_drive().get(f"https://www.googleapis.com/drive/v3/files/{fid}", params={"alt": "media"}, timeout=20)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        pass
    try:
        import requests as _rq
        r = _rq.get(f"https://drive.google.com/uc?export=download&id={fid}", timeout=10)
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/"):
            return r.content
    except Exception:
        pass
    return None

def _qv_image(v):
    """「圖片」欄：檔名、Drive 連結/ID 或 http 網址 → 圖片 bytes 或網址"""
    v = str(v or "").strip()
    if not v:
        return None
    if re.search(r"\.(png|jpe?g|gif|webp)$", v, re.I) and not v.startswith("http"):
        fid = _qv_img_index().get(v.lower())
        return _qv_img_bytes(fid) if fid else None
    m = re.search(r"(?:/d/|[?&]id=)([A-Za-z0-9_-]{20,})", v)
    fid = m.group(1) if m else (v if re.fullmatch(r"[A-Za-z0-9_-]{20,}", v) else "")
    if fid:
        return _qv_img_bytes(fid)
    return v if v.startswith("http") else None

def _qv_open(qid, ans_map: dict):
    try:
        @st.dialog("📖 題目內容", width="large")
        def _qv_dlg():
            _qv_show(qid, ans_map)
        _qv_dlg()
    except Exception:
        with st.container(border=True):
            _qv_show(qid, ans_map)

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

# ── V2.04：依「每次作答」分組（開始時間＋練習方式）────────────────────────────
_SESSION_GAP_MIN = 10   # 舊紀錄（沒有開始時間欄位）：同任務相隔超過 10 分鐘視為新的一次

def _strip_task_date(name: str) -> str:
    """'[T...] xxx-AA-小康-2026-04-27_15:09-...' → '[T...] xxx-AA-小康'"""
    s = str(name)
    m = re.search(r'-20\d{2}-\d{2}-\d{2}[_\-]', s)
    if m:
        s = s[:m.start()]
    return s.strip()

@st.cache_data(ttl=60)
def _build_qid_task_map_all(assign_json: str) -> dict:
    """qid → 任務名稱（精簡）"""
    import json
    m = {}
    for row in json.loads(assign_json):
        tname = _strip_task_date(row.get("任務名稱", ""))
        for q in str(row.get("題目ID清單", "")).split(","):
            q = q.strip()
            if q:
                m[q] = tname
                m[re.sub(r'^[A-Za-z]_', '', q)] = tname
    return m

def _to_ts(v):
    s = str(v or "").strip()
    if not s or s in ("None", "nan", "NaT"):
        return pd.NaT
    return pd.to_datetime(s[:19].replace("T", " "), errors="coerce")

def _fmt_ts(ts, with_date=True):
    if ts is None or pd.isna(ts):
        return "—"
    wd = _WEEKDAY_CN[ts.weekday()]
    return ts.strftime(f"%m-%d({wd}) %H:%M:%S") if with_date else ts.strftime("%H:%M:%S")

def _infer_mode(results) -> str:
    """舊紀錄沒有練習方式欄位時，由作答結果推測"""
    rs = [str(r) for r in results]
    if any(r == "練習" for r in rs):     return "🏋️ 練習模式（推測）"
    if any("跟著唸" in r for r in rs):   return "🎤 跟著唸和錄音（推測）"
    if any("朗讀" in r for r in rs):     return "🎤 朗讀（推測）"
    return "⚡ 快速答題（推測）"

def _build_sessions(df: pd.DataFrame) -> list:
    """
    把答題紀錄分成一次一次的作答：
      有『開始時間』欄位（app V2.9.540 起）→ 同一個開始時間＋練習方式 = 同一次
      沒有（舊紀錄）→ 同任務、相鄰兩題相隔不超過 _SESSION_GAP_MIN 分鐘 = 同一次
    回傳依開始時間由新到舊排序的 list。
    """
    if df is None or df.empty or "時間" not in df.columns:
        return []
    d = df.copy()
    for c in ("開始時間", "練習方式", "_task", "答題秒數"):
        if c not in d.columns:
            d[c] = ""
    d["開始時間"] = d["開始時間"].fillna("").astype(str).replace({"None": "", "nan": ""})
    d["練習方式"] = d["練習方式"].fillna("").astype(str).replace({"None": "", "nan": ""})
    d["_t"] = d["時間"].apply(_to_ts)
    d = d.dropna(subset=["_t"]).sort_values("_t").reset_index(drop=True)
    if d.empty:
        return []

    sids, last, n = [], {}, 0
    for _, r in d.iterrows():
        if r["開始時間"]:
            sids.append(f"S|{r['開始時間']}|{r['練習方式']}")
            continue
        prev = last.get(r["_task"])
        if prev and (r["_t"] - prev[1]).total_seconds() <= _SESSION_GAP_MIN * 60:
            sid = prev[0]
        else:
            n += 1
            sid = f"G|{n}"
        last[r["_task"]] = (sid, r["_t"])
        sids.append(sid)
    d["_sid"] = sids

    sessions = []
    for sid, g in d.groupby("_sid", sort=False):
        first = g.iloc[0]
        if sid.startswith("S|"):
            start = _to_ts(first["開始時間"])
            mode  = first["練習方式"] or "—"
        else:
            el = pd.to_numeric(first.get("答題秒數"), errors="coerce")
            start = first["_t"] - timedelta(seconds=float(el) if pd.notna(el) else 0)
            mode  = _infer_mode(g["結果"].tolist())
        if pd.isna(start):
            start = first["_t"]
        tasks = g["_task"].astype(str)
        tasks = tasks[tasks != ""]
        task  = tasks.mode().iloc[0] if not tasks.empty else "（未對應任務）"
        sessions.append({
            "start": start, "end": g["_t"].max(), "mode": mode, "task": task,
            "df": g.drop(columns=["_t", "_sid"]),
        })
    sessions.sort(key=lambda s: s["start"], reverse=True)
    return sessions

def _session_stats(g: pd.DataFrame) -> dict:
    res  = g["結果"].astype(str) if "結果" in g.columns else pd.Series(dtype=str)
    ok   = int((res == "✅").sum())
    err  = int((res == "❌").sum())
    prac = int((res == "練習").sum())
    test = ok + err
    return {
        "total": len(g), "ok": ok, "err": err, "prac": prac, "test": test,
        "rate": f"{ok / test * 100:.0f}%" if test else "—",
        "elapsed": _sum_elapsed(g),
    }

def _session_articles(g) -> int:
    """V2.37：這次作答讀了幾篇文章（閱讀題依題組算，同一篇只算一次）"""
    try:
        if "_art" in g.columns:
            a = g.loc[g["_art"].astype(str) != "", "_art"]
        else:
            q = g["題目ID"].astype(str)
            q = q[q.apply(_qcat) == "閱讀"]
            if q.empty:
                return 0
            _gm = _rm_group_map()
            a = q.apply(lambda x: _article_id(x, _gm))
        return int(a.nunique())
    except Exception:
        return 0

def _session_summary(s: dict) -> str:
    stt = _session_stats(s["df"])
    txt = f"🕒 {_fmt_ts(s['start'], with_date=False)}　{s['mode']}｜{s['task']}"
    _na = _session_articles(s["df"])
    if _na: txt += f"　{_na}篇"
    if stt["test"]: txt += f"　測驗{stt['test']}題 ✅{stt['ok']} ❌{stt['err']}（{stt['rate']}）"
    if stt["prac"]: txt += f"　練習{stt['prac']}題"
    other = stt["total"] - stt["test"] - stt["prac"]
    if other > 0:   txt += f"　其他{other}筆"
    if stt["elapsed"]: txt += f"　⏱{stt['elapsed']}"
    return txt

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

def _login_check(account: str, password: str):
    """
    回傳 (role, name, group_id) 或 None
    role: 'admin' | 'teacher' | 'student'
    """
    # 先檢查 Admin 密碼
    admin_pwd = st.secrets.get("ADMIN_PASSWORD", "admin123")
    if password == admin_pwd:
        return ("admin", "管理員", "ADMIN")
    # 再查 Supabase students 表
    try:
        sb  = get_supabase()
        res = sb.table("students").select("name,account,password,group_id").eq("account", account).execute()
        if res.data:
            row = res.data[0]
            if str(row.get("password","")) == str(password):
                grp = str(row.get("group_id",""))
                role = "teacher" if grp in ["ADMIN","TEACHER"] else "student"
                return (role, str(row.get("name","")), grp)
    except:
        pass
    return None

# ── V2.17：依學年分顏色，瀏覽器分頁標題＝學生姓名、分頁小圖示＝學年顏色＋姓名末字 ──
_YEAR_COLORS = [("#e5484d", "🔴"), ("#f76b15", "🟠"), ("#d4a700", "🟡"),
                ("#30a46c", "🟢"), ("#0090ff", "🔵"), ("#8e4ec6", "🟣")]

def _year_color(sy):
    try:
        return _YEAR_COLORS[int(float(str(sy).strip())) % len(_YEAR_COLORS)]
    except Exception:
        return ("#6b7280", "⚪")

def _year_fg(color: str) -> str:
    """V2.25：黃色底用深色字，其餘用白字（名字比較好讀）"""
    return "#1f2937" if color in ("#d4a700",) else "#ffffff"

def _student_year(name: str) -> str:
    try:
        df = load_students()
        if df.empty or "姓名" not in df.columns or "學年" not in df.columns:
            return ""
        m = df[df["姓名"].astype(str).str.strip() == str(name).strip()]
        if m.empty:
            return ""
        v = pd.to_numeric(str(m.iloc[0]["學年"]).strip(), errors="coerce")
        return "" if pd.isna(v) else str(int(round(v)))
    except Exception:
        return ""

def _set_browser_tab(name: str, sy: str):
    """把瀏覽器分頁標題改成學生姓名，小圖示改成學年顏色＋姓名最後一個字"""
    import json as _json
    import streamlit.components.v1 as _components
    color, _ = _year_color(sy)
    title = f"{name}｜{sy}學年" if sy else name
    ch = (str(name).strip() or "？")[-1]
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
           f"<rect width='64' height='64' rx='14' fill='{color}'/>"
           f"<text x='32' y='47' font-size='42' text-anchor='middle' fill='#fff' "
           f"font-family='sans-serif' font-weight='bold'>{ch}</text></svg>")
    _components.html(f"""<script>
const T = {_json.dumps(title)};
const ICON = "data:image/svg+xml," + encodeURIComponent({_json.dumps(svg)});
function apply(doc) {{
  try {{
    if (doc.title !== T) doc.title = T;
    let links = doc.querySelectorAll("link[rel~='icon']");
    if (!links.length) {{ const l = doc.createElement('link'); l.rel = 'icon'; doc.head.appendChild(l); links = [l]; }}
    links.forEach(l => {{ if (l.href !== ICON) {{ l.type = 'image/svg+xml'; l.href = ICON; }} }});
  }} catch (e) {{}}
}}
function run() {{
  try {{ apply(window.parent.document); }} catch (e) {{}}
  try {{ if (window.top !== window.parent) apply(window.top.document); }} catch (e) {{}}
}}
run(); setInterval(run, 1000);
</script>""", height=0)

# ── V2.07：老師從學生名單開啟學生報告的免密碼連結（簽章、12 小時有效）──────────
import hmac as _hmac, hashlib as _hashlib, time as _time_mod
from urllib.parse import quote as _url_quote
_VIEW_TTL_SEC = 12 * 3600

def _view_sig(name: str, exp: int) -> str:
    key = str(st.secrets.get("ADMIN_PASSWORD", "")) + "|" + str(st.secrets.get("SUPABASE_KEY", ""))
    return _hmac.new(key.encode(), f"{name}|{exp}".encode(), _hashlib.sha256).hexdigest()[:32]

def _make_view_query(name: str) -> str:
    exp = int(_time_mod.time()) + _VIEW_TTL_SEC
    return f"?view_stu={_url_quote(name)}&exp={exp}&sig={_view_sig(name, exp)}"

def _secret_any(k: str, _node=None, _depth: int = 0) -> str:
    """V2.28：先找最上層，再往 [區段] 裡找（金鑰被貼在某個 [區段] 底下也讀得到），前後空白去掉"""
    node = st.secrets if _node is None else _node
    try:
        if k in node and not hasattr(node[k], "keys"):
            v = str(node[k] or "").strip()
            if v:
                return v
        if _depth < 3:
            for _kk in list(node.keys()):
                _sub = node[_kk]
                if hasattr(_sub, "keys"):
                    v = _secret_any(k, _sub, _depth + 1)
                    if v:
                        return v
    except Exception:
        pass
    return ""

def _parent_sig(name: str, exp: int) -> str:
    """V2.27：家長連結（進度表 Apps Script 產生）用的簽章，金鑰＝secrets 的 PARENT_LINK_KEY"""
    k = _secret_any("PARENT_LINK_KEY")
    if not k:
        return ""
    return _hmac.new(k.encode(), f"P|{name}|{exp}".encode(), _hashlib.sha256).hexdigest()[:32]

def _dash_base_url() -> str:
    u = str(st.secrets.get("DASHBOARD_URL", "") or "")
    if not u:
        try:
            host = st.context.headers.get("Host", "")
            if host:
                u = f"https://{host}/"
        except Exception:
            u = ""
    if not u:
        try:
            u = str(st.context.url or "")
        except Exception:
            u = ""
    return u.split("?")[0] if u else "./"

# V2.19：題目分類（單字／文法／閱讀），總覽每一行前加標記、名字下加 30 天小計
_OV_CATS = ["單字", "文法", "閱讀"]
_OV_CAT_ICON = {"單字": "🔤", "文法": "📝", "閱讀": "📖", "朗讀": "🎤", "聽力": "🎧", "其他": "❔"}

def _qcat(qid) -> str:
    s = str(qid).strip()
    pre = s.split("_")[0] if s else ""
    if pre == "V":
        return "單字"
    if pre == "RM":
        return "閱讀"
    if pre == "R":
        return "朗讀"
    if pre in ("LS", "LP"):
        return "聽力"
    try:
        t = (_parse_qid(s) or {}).get("題型") or ""
    except Exception:
        t = ""
    if t in ("閱讀重組", "閱讀單句"):
        return "閱讀"
    if t in ("拼單字", "單字重組", "歷屆大學"):
        return "單字"
    if t in ("單選", "文意文法", "重組", "對話重組"):
        return "文法"
    return "其他"

def _cat_tag(g: pd.DataFrame) -> str:
    if "_cat" not in g.columns:
        return ""
    have = set(g["_cat"].tolist())
    cs = [c for c in _OV_CAT_ICON if c in have]
    return ("【" + "＋".join(_OV_CAT_ICON[c] + c for c in cs) + "】") if cs else ""

# V2.36：閱讀題對應到哪一篇文章（閱讀單句工作表的「題組」欄），統計顯示「幾篇」
_ART_KEYS = ["版本", "年度", "冊編號", "單元", "課編號", "句編號"]

@st.cache_resource(ttl=3600, show_spinner=False)  # V2.38：全 App 共用一份、不複製，1 小時更新
def _rm_group_map() -> dict:
    out = {}
    try:
        df = load_question_sheet("閱讀單句")
    except Exception:
        return out
    if df is None or df.empty or "題組" not in df.columns or any(c not in df.columns for c in _ART_KEYS):
        return out
    for r in df[_ART_KEYS + ["題組"]].itertuples(index=False):
        g = str(r[-1]).strip()
        if g:
            out["|".join(_norm(x).replace("ㄧ", "一") for x in r[:-1])] = g
    return out

def _article_id(qid, gm: dict) -> str:
    s = str(qid).strip()
    g = ""
    try:
        p = _parse_qid(s) or {}
        g = gm.get("|".join(_norm(p.get(c, "")).replace("ㄧ", "一") for c in _ART_KEYS), "")
    except Exception:
        g = ""
    return g or s

def _add_art(df: pd.DataFrame) -> pd.DataFrame:
    df["_art"] = ""
    try:
        _isr = df["_cat"] == "閱讀"
        if _isr.any():
            _gm = _rm_group_map()
            df.loc[_isr, "_art"] = df.loc[_isr, "題目ID"].apply(lambda x: _article_id(x, _gm))
    except Exception:
        pass
    return df

# ── V2.43：🗣️ 對話練習紀錄（練習系統 dialog_practice.py 寫在 Supabase dialog_logs）──────────
_DLG_CHECK = {"✅": "說對了", "🔁": "再練", "🎙️": "錄音", "⏭": "略過（沒錄音）", "🎬": "看完示範"}  # V2.45：⏭／🎬


@st.cache_data(ttl=45, show_spinner=False)
def _load_dialog_logs(stu_name: str, date_from: str) -> pd.DataFrame:
    """單一學生的對話練習紀錄（時間轉成台灣時間；資料表不存在就回傳空表）"""
    try:
        d0 = (datetime.strptime(date_from, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        res = (get_supabase().table("dialog_logs").select("*").eq("name", stu_name)
               .gte("created_at", d0).order("created_at", desc=False).limit(3000).execute())
        st.session_state.pop("_dlg_err", None)
        return _dlg_prep(res.data)
    except Exception as e:
        st.session_state["_dlg_err"] = f"{type(e).__name__}: {e}"[:200]   # V2.45：讀取失敗要看得到
        return pd.DataFrame()


@st.cache_data(ttl=180, show_spinner=False)
def _load_dialog_titles() -> dict:
    """指派編號 → 任務名稱"""
    try:
        res = get_supabase().table("dialog_assignments").select("id,title,dialog_id").execute()
        return {int(r["id"]): (r.get("title") or "", r.get("dialog_id") or "") for r in (res.data or [])}
    except Exception:
        return {}


def _dialog_turns() -> dict:
    """試算表「對話範本」→ {(對話ID, 回合): (英文, 中文)}，另外 {對話ID: 標題}"""
    df = load_question_sheet("對話範本")
    turns, titles = {}, {}
    if df.empty or "對話ID" not in df.columns:
        return {"turns": turns, "titles": titles}
    for _, r in df.iterrows():
        did = str(r.get("對話ID", "")).strip()
        if not did:
            continue
        if str(r.get("標題", "")).strip() and did not in titles:
            titles[did] = str(r.get("標題", "")).strip()
        try:
            n = int(float(str(r.get("回合", "")).strip()))
        except ValueError:
            continue
        turns[(did, n)] = (str(r.get("英文", "")), str(r.get("中文", "")))
    zh = {}   # 試算表「替換字」：(對話ID, 英文小寫) → 中文
    dc = load_question_sheet("替換字")
    if not dc.empty and "英文" in dc.columns and "中文" in dc.columns:
        for _, r in dc.iterrows():
            if str(r.get("英文", "")).strip() and str(r.get("中文", "")).strip():
                zh[(str(r.get("對話ID", "")).strip(), str(r["英文"]).strip().lower())] = str(r["中文"]).strip()
    return {"turns": turns, "titles": titles, "zh": zh}


def _dlg_fill(tpl: str, words: str, zh_map: dict = None) -> str:
    """句子裡的 {欄位} 換成這一輪抽到的字；是非題「是 || 不是」依抽到的字選一邊
    zh_map：{英文小寫: 中文}，有給就是填中文句（不做句首大寫）"""
    w = {}
    for kv in str(words or "").split(";"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            w[k.strip()] = v.strip()
    tpl = str(tpl or "")
    if "||" in tpl:
        yes = all(v == w.get(k[1:]) for k, v in w.items() if k.startswith("?"))
        a, b = tpl.split("||", 1)
        tpl = a if yes else b

    def _rep(m):
        k = m.group(1).strip()
        v = w.get(k) or w.get(k.lstrip("?")) or m.group(0)
        if zh_map is not None:
            return zh_map.get(v.lower(), v)
        if v and re.search(r"(^|[.?!]\s*)$", tpl[:m.start()].strip()):
            v = v[0].upper() + v[1:]
        return v
    return re.sub(r"\{\s*(\??\w+)\s*\}", _rep, tpl).strip()


def _dlg_prep(rows) -> pd.DataFrame:
    """dialog_logs 原始資料 → DataFrame（_t＝台灣時間、不帶時區，和作答紀錄的時間可以比較；_day＝日期）"""
    df = pd.DataFrame(rows or [])
    if df.empty or "created_at" not in df.columns:
        return pd.DataFrame()
    df["_t"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce", format="ISO8601").dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
    df = df[df["_t"].notna()].copy()
    df["_day"] = df["_t"].dt.strftime("%Y-%m-%d")
    df["name"] = df["name"].fillna("").astype(str).str.strip()
    # V2.46：words 最後的「@=代號」（同一次練習代號相同）拆到 _code，其他地方就不會看到它
    _w = df["words"].fillna("").astype(str) if "words" in df.columns else pd.Series("", index=df.index)
    df["_code"] = _w.str.extract(r"(?:^|;)@=([^;]*)", expand=False).fillna("").str.strip()
    df["words"] = _w.str.replace(r"(?:^|;)@=[^;]*", "", regex=True)
    return df


# V2.46：關卡名稱（去掉前面的 ①②③；舊名稱換成現在的）
_DLG_STAGE_OLD = {"跟讀": "全文示範", "看圖說": "看圖練習說", "角色對話": "測驗"}
_DLG_STAGE_ICON = {"測驗": "📝", "全文示範": "🎬", "看圖練習說": "🖼️"}

def _dlg_stage(s) -> str:
    s = re.sub(r"^[①②③④⑤\s]+", "", str(s or "")).strip()
    return _DLG_STAGE_OLD.get(s, s) or "對話練習"


def _dlg_attempts(df: pd.DataFrame) -> pd.Series:
    """V2.46：一位學生的對話紀錄 → 每一筆屬於第幾次練習（每次按「測驗」「看圖練習說」「全文示範」各算一次）
    新紀錄：練習系統寫在 words 的「@=代號」，代號相同就是同一次。
    舊紀錄（沒有代號）：換日／換任務／換對話／換關卡、同一輪的單字變了、或回到第一輪第一句，就算新的一次。"""
    out, no, prev, seen, first, last, code2no = {}, 0, None, {}, None, None, {}
    for ix, r in df.sort_values(["_t", "id"] if "id" in df.columns else "_t", kind="stable").iterrows():
        words = str(r.get("words") or "")
        code = str(r.get("_code") or "")
        base = (r["_day"], r["_aid"], str(r.get("dialog_id") or ""), _dlg_stage(r.get("stage")))
        if code:
            k = base + (code,)
            if k not in code2no:
                no += 1
                code2no[k] = no
            out[ix] = code2no[k]
            prev = None
            continue
        rno = int(pd.to_numeric(r.get("round_no"), errors="coerce") or 0)
        pos = (rno, int(pd.to_numeric(r.get("turn_no"), errors="coerce") or 0))
        if (prev != base or seen.get(rno, words) != words or (pos == first and last != first)
                or (pos[1] == 0 and pos <= last)):
            no += 1
            seen, first = {}, pos
        seen[rno] = words
        prev, last = base, pos
        out[ix] = no
    return pd.Series(out).reindex(df.index)


def _dlg_groups(df: pd.DataFrame) -> list:
    """對話紀錄 → 每一次練習一組（新的在前），附統計；V2.46 起測驗、看圖練習說、全文示範各自分開"""
    if df is None or df.empty:
        return []
    titles = _load_dialog_titles()
    ref = _dialog_turns()
    df = df.copy()
    df["_aid"] = df["assign_id"].apply(lambda x: "" if pd.isna(x) else str(int(x)))
    out = []
    df["_att"] = _dlg_attempts(df)
    for (day, aid, did, _att), g in df.groupby(["_day", "_aid", "dialog_id", "_att"]):
        name = titles.get(int(aid), ("", ""))[0] if aid else "（自己試練）"
        name = re.sub(r"^\s*🗣️?\s*", "", name or ref["titles"].get(did, did))
        sc = g["self_check"].astype(str)
        tn = pd.to_numeric(g["turn_no"], errors="coerce").fillna(0)
        out.append({"day": day, "aid": aid, "did": did, "g": g, "name": name, "stage": _dlg_stage(g["stage"].iloc[0]),
                    "start": g["_t"].min(), "end": g["_t"].max(), "rounds": int(g["round_no"].nunique()),
                    "n": int((tn > 0).sum()), "ok": int((sc == "✅").sum()), "again": int((sc == "🔁").sum()),
                    "skip": int((sc == "⏭").sum()), "demo": int((sc == "🎬").sum()),
                    "audio": int((g["audio_path"].fillna("").astype(str) != "").sum())})
    out.sort(key=lambda x: x["end"], reverse=True)
    return out


def _dlg_summary(x: dict, tag: bool = False) -> str:
    """一組對話練習的一行標題（格式同「歷次作答」）"""
    s = (("【🗣️對話】" if tag else "") + f"🕒 {x['start'].strftime('%H:%M:%S')}　{_DLG_STAGE_ICON.get(x['stage'], '🗣️')} {x['stage']}｜{x['name']}　{x['rounds']}輪")
    if x.get("demo"):
        s += f" 🎬看示範{x['demo']}輪"
    if x["n"]:
        s += f" {x['n']}句"
        if x["ok"] or x["again"]:
            s += f" ✅{x['ok']} 🔁{x['again']}"
        if x["audio"]:
            s += f" 🎙️{x['audio']}"
        if x.get("skip"):
            s += f" ⏭{x['skip']}"
    return s


def _dlg_daycat(groups: list) -> dict:
    """{日期: (說對了, 再練, 句數)}，給總覽小表格用"""
    out = {}
    for x in groups:
        a = out.get(x["day"], (0, 0, 0))
        out[x["day"]] = (a[0] + x["ok"], a[1] + x["again"], a[2] + x["n"])
    return out


def _dlg_mini_cell(daycat: dict, days: set):
    """總覽小表格「🗣️對話」一格：句數＋說對了比例（✅／(✅+🔁)）→ (html, csv 文字)"""
    ok = again = n = 0
    for d, v in daycat.items():
        if d in days:
            ok += v[0]; again += v[1]; n += v[2]
    if ok + again:
        rate = ok / (ok + again) * 100
        col = "#30a46c" if rate >= 80 else ("#d4a700" if rate >= 60 else "#e5484d")
        return f"<span style='color:{col};font-weight:600'>{n}句 {rate:.0f}%</span>", f"{n}句 說對{rate:.0f}%"
    if n:
        return f"<span class='ovpr'>{n}句</span>", f"{n}句"
    return "<span class='ovpr'>—</span>", ""


def _dlg_for_student(stu_name: str, d_from: str, d_to: str) -> list:
    df = _load_dialog_logs(stu_name, d_from)
    if df.empty:
        return []
    return _dlg_groups(df[(df["_day"] >= d_from) & (df["_day"] <= d_to)])


@st.cache_data(ttl=300, show_spinner=False)
def _dialog_overview(date_from: str, date_to: str) -> dict:
    """全班對話練習 → {"lines": {姓名: {日期: [標題]}}, "cat": {姓名: {日期: (對, 再練, 句數)}}}"""
    rows = []
    try:
        sb = get_supabase()
        page = 0
        while True:
            res = (sb.table("dialog_logs").select("*").gte("created_at", date_from)
                   .order("created_at", desc=False).range(page * 1000, (page + 1) * 1000 - 1).execute())
            if not res.data:
                break
            rows.extend(res.data)
            if len(res.data) < 1000:
                break
            page += 1
    except Exception:
        return {}
    df = _dlg_prep(rows)
    if df.empty:
        return {}
    df = df[(df["_day"] >= date_from) & (df["_day"] <= date_to)]
    lines, cat = {}, {}
    for nm, g in df.groupby("name"):
        grp = _dlg_groups(g)
        for x in grp:
            lines.setdefault(nm, {}).setdefault(x["day"], []).append(_dlg_summary(x, True))
        cat[nm] = _dlg_daycat(grp)
    return {"lines": lines, "cat": cat}


def _render_dlg_detail(x: dict, key: str):
    """點開一組對話練習：每一句（英文／中文）、自評、錄音"""
    ref = _dialog_turns()
    did = x["did"]
    zmap = {e: z for (d, e), z in ref["zh"].items() if d == did}
    rows = []
    for _, r in x["g"].iterrows():
        tno = int(pd.to_numeric(r["turn_no"], errors="coerce") or 0)
        en, zh = ref["turns"].get((did, tno), ("", ""))
        if tno == 0:  # V2.45：② 全文示範看完一輪
            _w = "、".join(kv.split("=", 1)[1] for kv in str(r.get("words") or "").split(";") if "=" in kv and not kv.startswith("?"))
            en, zh = "🎬 看完整段示範" + (f"（單字：{_w}）" if _w else ""), ""
        rows.append({"時間": r["_t"].strftime("%H:%M:%S"), "階段": str(r.get("stage") or ""),
                     "輪": int(r["round_no"]), "句": str(tno) if tno else "—",
                     "句子": (en if tno == 0 else _dlg_fill(en, r.get("words"))) or str(r.get("words") or ""),
                     "中文": "" if tno == 0 else _dlg_fill(zh, r.get("words"), zmap),
                     "自評": str(r["self_check"]) + " " + _DLG_CHECK.get(str(r["self_check"]), ""),
                     "_audio": str(r.get("audio_path") or "")})
    tdf = pd.DataFrame(rows)
    st.dataframe(tdf.drop(columns=["_audio"]), use_container_width=True, hide_index=True,
                 column_config={"句子": st.column_config.TextColumn("句子", width="large")})
    aud = tdf[tdf["_audio"] != ""]
    if aud.empty:
        return
    if st.button(f"🎧 聽錄音（{len(aud)} 段）", key=key):
        st.session_state[key + "_on"] = True
    if st.session_state.get(key + "_on"):
        store = get_supabase().storage.from_("dialog_audio")
        for _, r in aud.iterrows():
            try:
                u = store.create_signed_url(r["_audio"], 3600)
                u = (u.get("signedURL") or u.get("signedUrl") or u.get("signed_url")) if isinstance(u, dict) \
                    else getattr(u, "signed_url", "")
            except Exception:
                u = ""
            st.caption(f"第 {r['輪']} 輪 第 {r['句']} 句　{r['自評']}　{r['句子']}")
            if u:
                st.audio(u)
            else:
                st.caption("（錄音讀取失敗）")


# V2.31：學生報告「歷次作答」上方的 8 天總覽（今天＋前 7 天；格式同學習總覽，名字下是 7／14／30 天小計）
_WEEK_DAYS = 8

def _render_student_week(stu_name: str):
    import html as _html
    _today_d = get_now().date()
    _dates30 = [_today_d - timedelta(days=i) for i in range(30)]
    _dates8 = _dates30[:_WEEK_DAYS]
    _d_from = _dates30[-1].strftime("%Y-%m-%d")
    _d_to = _today_d.strftime("%Y-%m-%d")
    try:
        df = load_logs_for_student(stu_name, date_from=_d_from)
    except Exception:
        df = pd.DataFrame()
    cells, cat = {}, {}
    if df is not None and not df.empty and "時間" in df.columns and "題目ID" in df.columns:
        df = df[df["時間"].astype(str).str[:10] <= _d_to]
        if "結果" in df.columns:
            df = df[~df["結果"].astype(str).str.contains("📖", na=False)]
        if not df.empty:
            df = df.copy()
            df["_cat"] = df["題目ID"].apply(_qcat)
            df = _add_art(df)  # V2.36
            df_a = load_assignments()
            _aj = df_a.to_json(orient="records") if not df_a.empty else "[]"
            _qt = _build_qid_task_map_all(_aj)
            df["_task"] = df["題目ID"].apply(
                lambda x: _qt.get(str(x).strip(), _qt.get(re.sub(r'^[A-Za-z]_', '', str(x).strip()), "")))
            if "任務名稱" in df.columns:
                _miss = df["_task"] == ""
                df.loc[_miss, "_task"] = df.loc[_miss, "任務名稱"].fillna("").astype(str).apply(_strip_task_date)
            res = df["結果"].astype(str) if "結果" in df.columns else pd.Series("", index=df.index)
            _dser = df["時間"].astype(str).str[:10]
            for (_dd, _cc), _gg in df.groupby([_dser, df["_cat"]]):
                if _cc in _OV_CATS:
                    _r2 = res.loc[_gg.index]
                    cat.setdefault(_dd, {})[_cc] = (int((_r2 == "✅").sum()), int((_r2 == "❌").sum()), int((_r2 == "練習").sum()), set(_gg["_art"].tolist()) - {""})
            for s in _build_sessions(df):  # V2.39：同一天內新的在上（降冪）
                cells.setdefault(s["start"].strftime("%Y-%m-%d"), []).append(_cat_tag(s["df"]) + _session_summary(s))
    # V2.44：對話練習放在當天其他作答的後面；小表格多一列「🗣️對話」
    _dgrp = _dlg_for_student(stu_name, _d_from, _d_to)
    for x in _dgrp:
        cells.setdefault(x["day"], []).append(_dlg_summary(x, True))
    _dcat = _dlg_daycat(_dgrp)

    try:
        _dark = str(st.context.theme.type) == "dark"
    except Exception:
        _dark = False
    _bg = "#0e1117" if _dark else "#ffffff"
    _hbg = "#262730" if _dark else "#f0f2f6"
    _nm_fg = "#ffffff" if _dark else "#000000"
    sy = _student_year(stu_name)
    color, _ = _year_color(sy)
    _gp = str(st.session_state.get("dash_group", "") or "")
    _PERS = (7, 14, 30)
    _per_ds = {k: {d.strftime("%Y-%m-%d") for d in _dates30[:k]} for k in _PERS}
    _nd = {k: sum(1 for d in _dates30[:k] if cells.get(d.strftime("%Y-%m-%d"))) for k in _PERS}
    _mini = ["<table class='ovmini'><tr><th></th>" + "".join(f"<th>{k}天</th>" for k in _PERS) + "</tr>",
             "<tr><td>📆天數</td>" + "".join(f"<td>{_nd[k]}</td>" for k in _PERS) + "</tr>"]
    for c in _OV_CATS:
        _row = f"<tr><td>{_OV_CAT_ICON[c]}{c}</td>"
        for k in _PERS:
            ok = err = pr = 0; _arts = set()
            for _dd, _dv in cat.items():
                if _dd in _per_ds[k] and c in _dv:
                    ok += _dv[c][0]; err += _dv[c][1]; pr += _dv[c][2]; _arts |= (set(_dv[c][3]) if len(_dv[c]) > 3 else set())
            tst = ok + err
            if tst:
                rate = ok / tst * 100
                col = "#30a46c" if rate >= 80 else ("#d4a700" if rate >= 60 else "#e5484d")
                _cell = f"<span style='color:{col};font-weight:600'>{(str(len(_arts)) + '篇 ') if _arts else ''}{tst}題 {rate:.0f}%</span>" + (f"<span class='ovpr'>＋練{pr}</span>" if pr else "")
            elif pr:
                _cell = f"<span class='ovpr'>{(str(len(_arts)) + '篇 ') if _arts else ''}練{pr}</span>"
            else:
                _cell = "<span class='ovpr'>—</span>"
            _row += f"<td>{_cell}</td>"
        _mini.append(_row + "</tr>")
    if _dcat:  # V2.44
        _mini.append("<tr><td>🗣️對話</td>" + "".join(f"<td>{_dlg_mini_cell(_dcat, _per_ds[k])[0]}</td>" for k in _PERS) + "</tr>")
    _st_html = "".join(_mini) + "</table>"

    _css = f"""<style>
.ovwrap {{ overflow:auto; border:1px solid rgba(128,128,128,.35); border-radius:8px; margin-bottom:10px; }}
.ovtbl {{ border-collapse:separate; border-spacing:0; font-size:12.5px; }}
.ovtbl th, .ovtbl td {{ border-right:1px solid rgba(128,128,128,.25); border-bottom:1px solid rgba(128,128,128,.25);
  padding:4px 6px; vertical-align:top; text-align:left; }}
.ovtbl thead th {{ background:{_hbg}; white-space:nowrap; min-width:64px; }}
.ovtbl th.ovtoday {{ background:#ff4b4b; color:#fff; }}
.ovtbl td.ovname, .ovtbl th.ovname {{ position:sticky; left:0; z-index:1; background:{_bg}; white-space:nowrap; min-width:110px; }}
.ovtbl thead th.ovname {{ z-index:3; background:{_hbg}; }}
.ovtbl td.ovhas {{ background:rgba(48,164,108,.10); min-width:250px; max-width:330px; }}
.ovtbl td.ovnone {{ background:transparent; }}
.ovl {{ padding:2px 0; border-bottom:1px dashed rgba(128,128,128,.3); line-height:1.35; }}
.ovl:last-child {{ border-bottom:none; }}
.ovbadge {{ padding:2px 9px; border-radius:6px; font-weight:700; font-size:14px; }}
.ovsub {{ font-size:11px; opacity:.7; }}
.ovtbl table.ovmini {{ border-collapse:collapse; margin-top:3px; }}
.ovtbl .ovmini td, .ovtbl .ovmini th {{ position:static; border:none; background:transparent; padding:1px 5px 1px 0;
  min-width:0; font-size:11px; white-space:nowrap; text-align:left; font-weight:normal; }}
.ovtbl .ovmini th {{ opacity:.65; }}
.ovpr {{ color:#6b7280; font-weight:normal; }}
.ovmob {{ display:none; }}
.ovmcard {{ padding:6px 8px; border:1px solid rgba(128,128,128,.35); border-radius:8px; margin-bottom:6px; }}
.ovmday {{ border:1px solid rgba(128,128,128,.3); border-radius:8px; margin-bottom:6px; overflow:hidden; }}
.ovmh {{ background:{_hbg}; padding:3px 8px; font-weight:600; font-size:13px; }}
.ovmtoday .ovmh {{ background:#ff4b4b; color:#fff; }}
.ovmb {{ padding:3px 8px; background:rgba(48,164,108,.10); }}
.ovmempty .ovmh {{ font-weight:normal; }}
@media (max-width: 640px) {{
  .ovwrap.ovwk {{ display:none; }}
  .ovmob {{ display:block; }}
}}
</style>"""
    _h = ["<div class='ovwrap ovwk'><table class='ovtbl'><thead><tr><th class='ovname'>學生</th>"]
    for i, d in enumerate(_dates8):
        lbl = f"{d.strftime('%m-%d')}（{_WEEKDAY_CN[d.weekday()]}）"
        _h.append(f"<th>今天 {lbl}</th>" if i == 0 else f"<th>{lbl}</th>")  # V2.34：今天不用紅底
    _h.append("</tr></thead><tbody><tr>")
    _h.append(f"<td class='ovname'><span class='ovbadge' style='background:{color}33;border:2px solid {color};color:{_nm_fg}'>"
              f"{_html.escape(stu_name)}</span><div class='ovsub'>{sy}學年 {_html.escape(_gp)}</div>{_st_html}</td>")
    for d in _dates8:
        lines = cells.get(d.strftime("%Y-%m-%d"), [])
        if lines:
            _h.append("<td class='ovhas'>" + "".join(f"<div class='ovl'>{_html.escape(x)}</div>" for x in lines) + "</td>")
        else:
            _h.append("<td class='ovnone'><span class='ovpr'>沒有作答</span></td>")  # V2.33
    _h.append("</tr></tbody></table></div>")
    # V2.32：手機（窄螢幕）改直式：名字卡在上，下面每天一格由上往下，不用左右滑
    _v = [f"<div class='ovmob ovtbl'><div class='ovmcard'><span class='ovbadge' style='background:{color}33;border:2px solid {color};color:{_nm_fg}'>"
          f"{_html.escape(stu_name)}</span><div class='ovsub'>{sy}學年 {_html.escape(_gp)}</div>{_st_html}</div>"]
    for i, d in enumerate(_dates8):
        _lb = f"{d.strftime('%m-%d')}（{_WEEKDAY_CN[d.weekday()]}）"
        _hd = ("今天 " + _lb) if i == 0 else _lb
        _cls = "ovmday"  # V2.34：今天不用紅底
        lines = cells.get(d.strftime("%Y-%m-%d"), [])
        if lines:
            _v.append(f"<div class='{_cls}'><div class='ovmh'>{_hd}</div><div class='ovmb'>"
                      + "".join(f"<div class='ovl'>{_html.escape(x)}</div>" for x in lines) + "</div></div>")
        else:
            _v.append(f"<div class='{_cls} ovmempty'><div class='ovmh'>{_hd}　<span class='ovpr'>沒有作答</span></div></div>")
    _v.append("</div>")
    st.markdown(f"#### 🗓️ 最近 {_WEEK_DAYS} 天總覽（{_dates8[-1].strftime('%m-%d')} ～ {_dates8[0].strftime('%m-%d')}）")
    st.caption("每一格是當天每一次練習／測驗的報告標題（🗣️ 對話練習接在當天最後）　｜　名字下面是最近 7／14／30 天的作答天數、測驗題數和正確率（＋練＝練習題數）：綠≥80%、黃60–79%、紅<60%")
    st.markdown(_css + "".join(_h) + "".join(_v), unsafe_allow_html=True)

# 老師點的學生連結：驗證簽章後直接以該生身分顯示學習報告
try:
    _qp = st.query_params
    _vs, _ve, _vg = _qp.get("view_stu"), _qp.get("exp"), _qp.get("sig")
    if _vs and _ve and _vg and st.session_state.get("dash_view_stu") != _vs:
        _ps = _parent_sig(_vs, int(_ve))
        if int(_ve) >= int(_time_mod.time()) and (_hmac.compare_digest(_view_sig(_vs, int(_ve)), str(_vg))
                                                  or (_ps and _hmac.compare_digest(_ps, str(_vg)))):
            _grp_v = ""
            _df_sv = load_students()
            if not _df_sv.empty and "姓名" in _df_sv.columns and "分組" in _df_sv.columns:
                _m = _df_sv[_df_sv["姓名"].astype(str).str.strip() == _vs]
                if not _m.empty:
                    _grp_v = str(_m.iloc[0]["分組"])
            st.session_state.update({"dash_logged_in": True, "dash_role": "student", "dash_name": _vs,
                                     "dash_group": _grp_v, "dash_view_stu": _vs})
        else:
            # V2.28：分開顯示原因，方便排查
            if int(_ve) < int(_time_mod.time()):
                st.warning("⚠️ 學生報告連結已過期，請向老師索取新的連結。")
            elif not _secret_any("PARENT_LINK_KEY"):
                st.warning("⚠️ 學生報告連結無效（dashboard 的 Secrets 讀不到 PARENT_LINK_KEY）。")
            else:
                st.warning("⚠️ 學生報告連結無效（簽章不符：請確認 Streamlit 和 Apps Script 的 PARENT_LINK_KEY 一模一樣）。")
except Exception:
    pass

# V2.12：老師登入狀態保留在網址（簽章、30 天），按「登出」才清除
_TEACHER_TTL_SEC = 30 * 86400
try:
    if not st.session_state.get("dash_logged_in"):
        _qp2 = st.query_params
        _tr, _tn, _tg, _te, _ts = (_qp2.get(k) for k in ("tk_role", "tk_name", "tk_grp", "tk_exp", "tk_sig"))
        if _tr in ("admin", "teacher") and _te and _ts and int(_te) >= int(_time_mod.time()) \
                and _hmac.compare_digest(_view_sig(f"T|{_tr}|{_tn or ''}|{_tg or ''}", int(_te)), str(_ts)):
            st.session_state.update({"dash_logged_in": True, "dash_role": _tr,
                                     "dash_name": _tn or "", "dash_group": _tg or ""})
except Exception:
    pass

if not st.session_state.get('dash_logged_in'):
    st.title("📚 英文全能練習系統")
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("### 🔐 請登入")
        with st.form("login_form"):
            account = st.text_input("帳號", key="dash_account")
            pwd     = st.text_input("密碼", type="password", key="dash_pwd")
            submitted = st.form_submit_button("登入", use_container_width=True, type="primary")
            if submitted:
                result = _login_check(account.strip(), pwd.strip())
                if result:
                    role, name, grp = result
                    st.session_state['dash_logged_in'] = True
                    st.session_state['dash_role']      = role
                    st.session_state['dash_name']      = name
                    st.session_state['dash_group']     = grp
                    # V2.12：老師／管理員登入後，網址帶簽章，重新整理或重開網頁仍維持登入（30 天）
                    if role in ("admin", "teacher"):
                        _exp = int(_time_mod.time()) + _TEACHER_TTL_SEC
                        st.query_params.update({
                            "tk_role": role, "tk_name": name, "tk_grp": grp, "tk_exp": str(_exp),
                            "tk_sig": _view_sig(f"T|{role}|{name}|{grp}", _exp),
                        })
                    st.rerun()
                else:
                    st.error("帳號或密碼錯誤")
    st.stop()

# ── 主介面 ────────────────────────────────────────────────────────────────────
_role  = st.session_state.get('dash_role', 'admin')
_name  = st.session_state.get('dash_name', '')
_group = st.session_state.get('dash_group', '')

_hc1, _hc2 = st.columns([5, 1])
_hc1.title("📚 英文全能練習系統")
_hc1.caption(f"V{DASHBOARD_VERSION}　{'👤 ' + _name if _name else ''}" + ("　👩‍🏫 老師檢視" if st.session_state.get("dash_view_stu") else ""))
if _hc2.button("登出", key="logout_btn"):
    st.query_params.clear()
    for k in ['dash_logged_in','dash_role','dash_name','dash_group','dash_view_stu',
              'rpt_stu_data','rpt_assign_json','rpt_all_range','rpt_collapse_ver']:
        st.session_state.pop(k, None)
    st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 學生視角：只看自己
# ══════════════════════════════════════════════════════════════════════════════
if _role == "student":
    # V2.17：分頁標題＝姓名、圖示＝學年顏色；頁面上的姓名也用學年顏色標示
    _sy_me = _student_year(_name)
    _set_browser_tab(_name, _sy_me)
    _c_me, _e_me = _year_color(_sy_me)
    st.markdown(f"<h3>📋 <span style='background:{_c_me};color:{_year_fg(_c_me)};padding:2px 12px;border-radius:8px'>{_name}</span>"
                f"{('　' + _e_me + ' ' + _sy_me + ' 學年') if _sy_me else ''}　的學習紀錄</h3>", unsafe_allow_html=True)

    tab_stu_rpt, tab_stu_task = st.tabs(["📊 我的學習報告", "📋 我的任務列表"])

    with tab_stu_rpt:
        # 時間選擇
        PERIODS_STU = ["今日", "昨天", "前天", "三天", "七天", "30天"]
        if "stu_period" not in st.session_state:
            st.session_state["stu_period"] = "七天"
        _sp_cols = st.columns(len(PERIODS_STU))
        for _i, _p in enumerate(PERIODS_STU):
            if _sp_cols[_i].button(_p, key=f"stu_p_{_p}",
                                   type="primary" if st.session_state["stu_period"]==_p else "secondary",
                                   use_container_width=True):
                st.session_state["stu_period"] = _p
                st.rerun()
        _today = date.today()
        _stu_d_map = {
            "今日": (_today, _today),
            "昨天": (_today-timedelta(days=1), _today-timedelta(days=1)),
            "前天": (_today-timedelta(days=2), _today-timedelta(days=2)),
            "三天": (_today-timedelta(days=2), _today),
            "七天": (_today-timedelta(days=6), _today),
            "30天": (_today-timedelta(days=29), _today),
        }
        _stu_from, _stu_to = _stu_d_map.get(st.session_state["stu_period"], (_today, _today))
        _stu_from_str = _stu_from.strftime("%Y-%m-%d")
        _stu_to_str   = _stu_to.strftime("%Y-%m-%d")

        # V2.04：學生在練習系統選好「練習方式」按下開始後，這裡自動重新統計本次作答
        _auto_c1, _auto_c2 = st.columns([3, 1])
        # V2.38：自動更新預設關閉，需要時再選 2 分鐘／5 分鐘
        _auto_iv = _auto_c1.radio("⏱ 自動更新", ["每 2 分鐘", "每 5 分鐘", "關閉"], index=2, horizontal=True, key="stu_auto_iv")
        _auto_sec = {"每 2 分鐘": 120, "每 5 分鐘": 300}.get(_auto_iv)
        if _auto_c2.button("🔄 立即更新", type="primary", key="stu_refresh_main", use_container_width=True):
            load_assignments.clear()
            _load_logs_for_student_raw.clear()
            _load_dialog_logs.clear()  # V2.43
            st.rerun()

        @st.fragment(run_every=_auto_sec)  # V2.38：依上面的選擇
        def _stu_report_fragment():
            df_mine = load_logs_for_student(_name, date_from=_stu_from_str)
            if not df_mine.empty and "時間" in df_mine.columns:
                df_mine = df_mine[(df_mine["時間"].astype(str).str[:10] >= _stu_from_str) &
                                  (df_mine["時間"].astype(str).str[:10] <= _stu_to_str)]
            if not df_mine.empty and "結果" in df_mine.columns:
                df_mine = df_mine[~df_mine["結果"].astype(str).str.contains("📖", na=False)]

            _render_student_week(_name)  # V2.31：歷次作答上方的 8 天總覽
            st.caption(f"📅 {_stu_from_str} ～ {_stu_to_str}　｜　最後更新：{get_now().strftime('%H:%M:%S')}")
            _dgrp = _dlg_for_student(_name, _stu_from_str, _stu_to_str)  # V2.44 對話練習
            if not _dgrp:  # V2.45
                _de = st.session_state.get("_dlg_err")
                st.caption("🗣️ 這段期間沒有對話練習紀錄" + (f"（讀取失敗：{_de}）" if _de else
                           "（練習系統在錄音、按 ✅／🔁、略過一句或看完一輪示範時才會記錄）"))
            if df_mine.empty and not _dgrp:
                st.info("此時間範圍內無答題資料")
                return

            if not df_mine.empty:
                df_a_mine = load_assignments()
                _aj    = df_a_mine.to_json(orient="records") if not df_a_mine.empty else "[]"
                _qtask = _build_qid_task_map_all(_aj)
                df_mine = df_mine.copy()
                df_mine["_task"] = df_mine["題目ID"].apply(
                    lambda x: _qtask.get(str(x).strip(), _qtask.get(re.sub(r'^[A-Za-z]_', '', str(x).strip()), "")))
                if "任務名稱" in df_mine.columns:
                    _miss = df_mine["_task"] == ""
                    df_mine.loc[_miss, "_task"] = df_mine.loc[_miss, "任務名稱"].fillna("").astype(str).apply(_strip_task_date)

            sessions = _build_sessions(df_mine) if not df_mine.empty else []
            if not sessions and not _dgrp:
                st.info("此時間範圍內無答題資料")
                return

            if sessions and st.session_state.get("_no_session_cols"):
                st.caption("ℹ️ 資料庫尚未新增「練習方式／開始時間」欄位，目前依作答時間自動分組，練習方式為推測。")

            # 歷次作答（依開始日期分組，新到舊）；V2.44：每天的對話練習接在當天其他作答後面
            st.markdown(f"#### 📜 歷次作答　{_year_color(_sy_me)[1]} {_name}")  # V2.16：標題旁加學生姓名（V2.17：學年顏色）
            _days = sorted({s["start"].strftime("%Y-%m-%d") for s in sessions} | {x["day"] for x in _dgrp}, reverse=True)
            for _day in _days:
                _day_sess = [x for x in sessions if x["start"].strftime("%Y-%m-%d") == _day]
                _day_dlg = [x for x in _dgrp if x["day"] == _day]
                _wd = _WEEKDAY_CN[datetime.strptime(_day, "%Y-%m-%d").weekday()]
                _lbl = f"**📅 {_day}（{_wd}）**　共 {len(_day_sess) + len(_day_dlg)} 次作答"
                if _day_dlg:
                    _lbl += f"（🗣️ 對話練習 {len(_day_dlg)} 次）"
                if _day_sess:
                    _day_el = _sum_elapsed(pd.concat([x["df"] for x in _day_sess], ignore_index=True))
                    if _day_el:
                        _lbl += f"　⏱ {_day_el}"
                st.markdown(_lbl)
                for s in _day_sess:
                    with st.expander(_session_summary(s), expanded=False):
                        _render_detail(s["df"], key=f"{sessions.index(s)}_{s['start'].strftime('%Y%m%d%H%M%S')}")  # V2.41
                for j, x in enumerate(_day_dlg):
                    with st.expander(_dlg_summary(x), expanded=False):
                        _render_dlg_detail(x, key=f"dlg_aud_{_day}_{x['aid']}_{x['did']}_{x['start'].strftime('%H%M%S')}_{j}")

        _stu_report_fragment()

    with tab_stu_task:
        df_a_task = load_assignments()
        df_active_stu = df_a_task[df_a_task["狀態"] == "進行中"].copy() if not df_a_task.empty and "狀態" in df_a_task.columns else pd.DataFrame()
        if df_active_stu.empty:
            st.info("目前沒有進行中的任務")
        else:
            tasks_mine = []
            for _, row in df_active_stu.iterrows():
                assigned = [s.strip() for s in str(row.get("指派學生","")).split(",") if s.strip()]
                if _name in assigned:
                    tasks_mine.append({
                        "任務名稱": _clean_task_name(str(row.get("任務名稱",""))),
                        "類型":     str(row.get("類型","")),
                        "結束日期": str(row.get("結束日期",""))[:10],
                    })
            if tasks_mine:
                st.dataframe(pd.DataFrame(tasks_mine), use_container_width=True, hide_index=True,
                             column_config={
                                 "任務名稱": st.column_config.TextColumn("任務名稱", width=None),
                                 "類型":     st.column_config.TextColumn("類型",     width=60),
                                 "結束日期": st.column_config.TextColumn("結束日期", width=80),
                             })
            else:
                st.info("目前沒有指派給你的進行中任務")
    st.stop()

# ── V2.18：學習總覽（左邊學生、上面日期，最近 30 天，第一欄＝今天）─────────────────
_OV_DAYS   = 30
_OV_FIELDS = "created_at,name,question_id,result,task_name,elapsed_sec"

# V2.31：_OV_CATS／_OV_CAT_ICON／_qcat／_cat_tag 已移到前面（學生報告的 8 天總覽也要用）

@st.cache_data(ttl=300, show_spinner=False)
def _load_logs_range(date_from: str) -> pd.DataFrame:
    """全班 date_from 以後的作答紀錄（只取總覽需要的欄位）"""
    sb = get_supabase()
    def _fetch(fields):
        rows, page = [], 0
        while True:
            res = (sb.table("logs").select(fields).gte("created_at", date_from)
                   .order("created_at", desc=False).range(page * 1000, (page + 1) * 1000 - 1).execute())
            if not res.data:
                break
            rows.extend(res.data)
            if len(res.data) < 1000:
                break
            page += 1
        return rows
    try:
        rows = _fetch(_OV_FIELDS + "," + _LOG_EXTRA_FIELDS)
    except Exception:
        rows = _fetch(_OV_FIELDS)
    return _to_cn(pd.DataFrame(rows), LOGS_COLS) if rows else pd.DataFrame()

@st.cache_data(ttl=300, show_spinner=False)
def _overview_cells(date_from: str, date_to: str) -> dict:
    """{"cells": {姓名: {'YYYY-MM-DD': [報告標題, ...]}}, "cat": {姓名: {分類: (對, 錯, 練習)}}}
    同一天依時間由早到晚"""
    df = _load_logs_range(date_from)
    if df.empty or "時間" not in df.columns or "姓名" not in df.columns:
        return {}
    df = df[df["時間"].astype(str).str[:10] <= date_to]
    if "結果" in df.columns:
        df = df[~df["結果"].astype(str).str.contains("📖", na=False)]
    if df.empty:
        return {}
    df = df.copy()
    df["_cat"] = df["題目ID"].apply(_qcat)
    df = _add_art(df)  # V2.36
    df_a = load_assignments()
    _aj = df_a.to_json(orient="records") if not df_a.empty else "[]"
    _qt = _build_qid_task_map_all(_aj)
    df = df.copy()
    df["_task"] = df["題目ID"].apply(
        lambda x: _qt.get(str(x).strip(), _qt.get(re.sub(r'^[A-Za-z]_', '', str(x).strip()), "")))
    if "任務名稱" in df.columns:
        _miss = df["_task"] == ""
        df.loc[_miss, "_task"] = df.loc[_miss, "任務名稱"].fillna("").astype(str).apply(_strip_task_date)
    out, cat = {}, {}
    for nm, g in df.groupby(df["姓名"].astype(str).str.strip()):
        res = g["結果"].astype(str) if "結果" in g.columns else pd.Series("", index=g.index)
        # V2.23：分類小計改成「每天」記錄，畫面上可選 7／14／30 天加總
        cat[nm] = {}
        _dser = g["時間"].astype(str).str[:10]
        for (_dd, _cc), _gg in g.groupby([_dser, g["_cat"]]):
            if _cc not in _OV_CATS:
                continue
            _r2 = res.loc[_gg.index]
            cat[nm].setdefault(_dd, {})[_cc] = (int((_r2 == "✅").sum()), int((_r2 == "❌").sum()), int((_r2 == "練習").sum()), set(_gg["_art"].tolist()) - {""})
        for s in _build_sessions(g):  # V2.40：學習總覽同一天內也新的在上（降冪）
            d = s["start"].strftime("%Y-%m-%d")
            out.setdefault(nm, {}).setdefault(d, []).append(_cat_tag(s["df"]) + _session_summary(s))
    return {"cells": out, "cat": cat}

# V2.30：今天有上課的學生（00C-英文出席管理表 → 02-今天上課人數計算；狀態＝固定／補課／調課，請假不算）
_ATT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1qc9B70E-t9cBxkb4NG7uHoKwffY9_KEQM_-eUOGJWyQ/edit"
_ATT_WS = "02-今天上課人數計算"
_ATT_OK = ("固定", "補課", "調課")

@st.cache_data(ttl=300, show_spinner=False)
def _today_class_names() -> list:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(spreadsheet=_ATT_SHEET_URL, worksheet=_ATT_WS, ttl=300)
    rows = [list(df.columns)] + df.fillna("").astype(str).values.tolist()
    out = []
    for r in rows:
        r = [str(x).strip() for x in r]
        for i in range(len(r) - 1):
            if r[i] in _ATT_OK and r[i + 1]:
                out.append(r[i + 1])
                break
    return list(dict.fromkeys(out))

def _render_overview_tab():
    import html as _html
    _now = get_now()
    _today_d = _now.date()
    _dates = [_today_d - timedelta(days=i) for i in range(_OV_DAYS)]
    _d_from = _dates[-1].strftime("%Y-%m-%d")
    _d_to = _today_d.strftime("%Y-%m-%d")

    st.subheader("📅 學習總覽（最近 30 天）")
    st.caption("左邊是學生、上面是日期（第一欄是今天，往右越早）。每一格列出當天每一次練習／測驗的報告標題；點學生名字會在新分頁開啟他的學習報告。")

    df_s = load_students()
    if df_s.empty or "姓名" not in df_s.columns:
        _students_load_failed("ov")
        return
    df_s = df_s[df_s["姓名"].astype(str).str.strip() != ""].copy()
    if "分組" not in df_s.columns:
        df_s["分組"] = ""
    if "學年" not in df_s.columns:
        df_s["學年"] = ""
    df_s = df_s[~df_s["分組"].astype(str).str.strip().str.upper().isin(["ADMIN", "TEACHER"])]
    df_s["_sy"] = pd.to_numeric(df_s["學年"].astype(str).str.strip(), errors="coerce").round().astype("Int64")
    df_s["_gp"] = df_s["分組"].astype(str).str.strip()
    df_s["_nm"] = df_s["姓名"].astype(str).str.strip()
    df_s = df_s.sort_values(["_sy", "_gp", "_nm"])
    _all_nm = set(df_s["_nm"].tolist())

    _f1, _f2, _f5, _f3, _f4 = st.columns([1.4, 1.4, 3, 1.4, 1])
    _yrs = [int(v) for v in df_s["_sy"].dropna().unique().tolist()]
    _sel_y = _f1.multiselect("學年", sorted(_yrs), key="ov_years", placeholder="全部學年")
    _gps = sorted([g for g in df_s["_gp"].unique().tolist() if g])
    # V2.21：組別選項後面列出該組學生名字
    _gp_names = df_s.groupby("_gp")["_nm"].apply(lambda s: "、".join(dict.fromkeys(s.tolist()))).to_dict()
    _sel_g = _f2.multiselect("組別", _gps, key="ov_groups", placeholder="全部組別",
                             format_func=lambda g: f"{g}（{_gp_names.get(g, '')}）" if _gp_names.get(g) else g)
    _today_cls = _f3.toggle("只看今天有上課的", value=False, key="ov_only_today")
    _only = _f3.toggle("只看有作答的", value=False, key="ov_only_active")
    if _f4.button("🔄 重新讀取", key="ov_refresh", use_container_width=True):
        _today_class_names.clear()
        _load_logs_range.clear()
        _overview_cells.clear()
        _dialog_overview.clear()  # V2.44
        st.session_state["ov_loaded"] = True
    if _sel_y:
        df_s = df_s[df_s["_sy"].isin(_sel_y)]
    if _sel_g:
        df_s = df_s[df_s["_gp"].isin(_sel_g)]
    if _today_cls:
        try:
            _tc = _today_class_names()
        except Exception as _e_tc:
            _tc = None
            st.warning((f"讀不到出席管理表「{_ATT_WS}」：{type(_e_tc).__name__}: {_e_tc}")[:300]
                       + "　→ 請把 dashboard 的服務帳號（client_email）加入「00C-英文出席管理表」的共用名單（檢視者即可）")
        if _tc is not None:
            df_s = df_s[df_s["_nm"].isin(_tc)]
            _miss = [n for n in _tc if n not in _all_nm]
            st.caption(f"📌 今天有上課（出席管理表，固定／補課／調課）：{len(_tc)} 人"
                       + (f"　｜　學生名單找不到：{'、'.join(_miss)}" if _miss else ""))
    # V2.20：可再挑選學生（選項依學年、組別縮小；可打字搜尋名字）
    _nm_opts = list(dict.fromkeys(df_s["_nm"].tolist()))
    if st.session_state.get("ov_names"):
        st.session_state["ov_names"] = [n for n in st.session_state["ov_names"] if n in _nm_opts]
    _sel_n = _f5.multiselect("學生", _nm_opts, key="ov_names", placeholder="全部學生（可打字搜尋名字）")
    if _sel_n:
        df_s = df_s[df_s["_nm"].isin(_sel_n)]

    if not st.session_state.get("ov_loaded"):
        st.info("要讀取全班最近 30 天的作答紀錄，第一次需要幾秒鐘。")
        if st.button("📥 產生學習總覽表", type="primary", key="ov_load_btn"):
            st.session_state["ov_loaded"] = True
            st.rerun()
        return

    with st.spinner("讀取全班最近 30 天的作答紀錄…"):
        _ovd = _overview_cells(_d_from, _d_to)
    cells = _ovd.get("cells", {})
    cats  = _ovd.get("cat", {})
    # V2.44：對話練習接在當天其他作答後面；小表格多一列「🗣️對話」
    _dov = _dialog_overview(_d_from, _d_to)
    _dcats = _dov.get("cat", {})
    if _dov.get("lines"):
        cells = {nm: {d: list(v) for d, v in dd.items()} for nm, dd in cells.items()}
        for nm, dd in _dov["lines"].items():
            for d, ls in dd.items():
                cells.setdefault(nm, {}).setdefault(d, []).extend(ls)

    if _only:
        df_s = df_s[df_s["_nm"].isin(list(cells.keys()))]
    if df_s.empty:
        st.info("沒有符合條件的學生")
        return

    try:
        _dark = str(st.context.theme.type) == "dark"
    except Exception:
        _dark = False
    _bg = "#0e1117" if _dark else "#ffffff"
    _hbg = "#262730" if _dark else "#f0f2f6"
    _nm_fg = "#ffffff" if _dark else "#000000"   # V2.26：名字用黑字（深色主題用白字）
    _base = _dash_base_url()
    # V2.24：作答天數和單字／文法／閱讀都同時列出 7／14／30 天
    _PERS = (7, 14, 30)
    _per_ds = {k: {d.strftime("%Y-%m-%d") for d in _dates[:k]} for k in _PERS}

    _css = f"""<style>
.ovwrap {{ overflow:auto; max-height:78vh; border:1px solid rgba(128,128,128,.35); border-radius:8px; }}
.ovtbl {{ border-collapse:separate; border-spacing:0; font-size:12.5px; }}
.ovtbl th, .ovtbl td {{ border-right:1px solid rgba(128,128,128,.25); border-bottom:1px solid rgba(128,128,128,.25);
  padding:4px 6px; vertical-align:top; text-align:left; }}
.ovtbl thead th {{ position:sticky; top:0; z-index:2; background:{_hbg}; white-space:nowrap; min-width:64px; }}
.ovtbl th.ovtoday {{ background:#ff4b4b; color:#fff; }}
.ovtbl td.ovname, .ovtbl th.ovname {{ position:sticky; left:0; z-index:1; background:{_bg}; white-space:nowrap; min-width:110px; }}
.ovtbl thead th.ovname {{ z-index:3; background:{_hbg}; }}
.ovtbl td.ovhas {{ background:rgba(48,164,108,.10); min-width:250px; max-width:330px; }}
.ovtbl td.ovnone {{ background:transparent; }}
.ovl {{ padding:2px 0; border-bottom:1px dashed rgba(128,128,128,.3); line-height:1.35; }}
.ovl:last-child {{ border-bottom:none; }}
.ovbadge, .ovbadge:link, .ovbadge:visited, .ovbadge:hover {{ padding:2px 9px; border-radius:6px; text-decoration:none !important; font-weight:700; font-size:14px; }}
.ovsub {{ font-size:11px; opacity:.7; }}
.ovst {{ font-size:11.5px; line-height:1.4; }}
.ovtbl table.ovmini {{ border-collapse:collapse; margin-top:3px; }}
.ovtbl .ovmini td, .ovtbl .ovmini th {{ position:static; border:none; background:transparent; padding:1px 5px 1px 0;
  min-width:0; font-size:11px; white-space:nowrap; text-align:left; font-weight:normal; }}
.ovtbl .ovmini th {{ opacity:.65; }}
.ovpr {{ color:#6b7280; font-weight:normal; }}
</style>"""

    _h = ["<div class='ovwrap'><table class='ovtbl'><thead><tr><th class='ovname'>學生</th>"]
    for i, d in enumerate(_dates):
        lbl = f"{d.strftime('%m-%d')}（{_WEEKDAY_CN[d.weekday()]}）"
        if i == 0:
            _h.append(f"<th>今天 {lbl}</th>")  # V2.35：今天不用紅底
        else:
            _h.append(f"<th>{lbl}</th>")
    _h.append("</tr></thead><tbody>")
    _csv_rows = []
    for _, r in df_s.iterrows():
        nm = r["_nm"]
        sy = "" if pd.isna(r["_sy"]) else str(int(r["_sy"]))
        color, _ = _year_color(sy)
        my = cells.get(nm, {})
        # V2.23：7／14／30 天內有作答的天數
        _nd = {k: sum(1 for d in _dates[:k] if my.get(d.strftime("%Y-%m-%d"))) for k in _PERS}
        n7, n14, n30 = _nd[7], _nd[14], _nd[30]
        url = _html.escape(_base + _make_view_query(nm), quote=True)
        # V2.24：小表格＝列：作答天數／單字／文法／閱讀，欄：7／14／30 天（測驗題數＋正確率；綠≥80%、黃60–79%、紅<60%）
        _st_csv = {}
        _mini = ["<table class='ovmini'><tr><th></th>" + "".join(f"<th>{k}天</th>" for k in _PERS) + "</tr>",
                 "<tr><td>📆天數</td>" + "".join(f"<td>{_nd[k]}</td>" for k in _PERS) + "</tr>"]
        for c in _OV_CATS:
            _row = f"<tr><td>{_OV_CAT_ICON[c]}{c}</td>"
            for k in _PERS:
                ok = err = pr = 0; _arts = set()
                for _dd, _dv in cats.get(nm, {}).items():
                    if _dd in _per_ds[k] and c in _dv:
                        ok += _dv[c][0]; err += _dv[c][1]; pr += _dv[c][2]; _arts |= (set(_dv[c][3]) if len(_dv[c]) > 3 else set())
                tst = ok + err
                if tst:
                    rate = ok / tst * 100
                    col = "#30a46c" if rate >= 80 else ("#d4a700" if rate >= 60 else "#e5484d")
                    _cell = f"<span style='color:{col};font-weight:600'>{(str(len(_arts)) + '篇 ') if _arts else ''}{tst}題 {rate:.0f}%</span>" + (f"<span class='ovpr'>＋練{pr}</span>" if pr else "")
                    txt = f"{(str(len(_arts)) + '篇 ') if _arts else ''}{tst}題 {rate:.0f}%" + (f"＋練習{pr}" if pr else "")
                elif pr:
                    _cell = f"<span class='ovpr'>{(str(len(_arts)) + '篇 ') if _arts else ''}練{pr}</span>"
                    txt = f"{(str(len(_arts)) + '篇 ') if _arts else ''}練習{pr}題"
                else:
                    _cell, txt = "<span class='ovpr'>—</span>", ""
                _row += f"<td>{_cell}</td>"
                _st_csv[f"{c}（{k}天）"] = txt
            _mini.append(_row + "</tr>")
        _dc = _dcats.get(nm, {})  # V2.44
        _row = "<tr><td>🗣️對話</td>"
        for k in _PERS:
            _hc, _tc = _dlg_mini_cell(_dc, _per_ds[k])
            _row += f"<td>{_hc}</td>"
            _st_csv[f"對話（{k}天）"] = _tc
        if _dc:
            _mini.append(_row + "</tr>")
        _st_html = "".join(_mini) + "</table>"
        _h.append(
            f"<tr><td class='ovname'><a class='ovbadge' style='background:{color}33;border:2px solid {color};color:{_nm_fg} !important' href='{url}' target='_blank'>"
            f"{_html.escape(nm)}</a><div class='ovsub'>{sy}學年 {_html.escape(r['_gp'])}</div>"
            f"{_st_html}</td>")
        _csv = {"學年": sy, "組別": r["_gp"], "姓名": nm, "7天作答天數": n7, "14天作答天數": n14, "30天作答天數": n30,
                **_st_csv}
        for d in _dates:
            ds = d.strftime("%Y-%m-%d")
            lines = my.get(ds, [])
            _csv[ds] = "\n".join(lines)
            if lines:
                _h.append("<td class='ovhas'>" + "".join(f"<div class='ovl'>{_html.escape(x)}</div>" for x in lines) + "</td>")
            else:
                _h.append("<td class='ovnone'></td>")
        _h.append("</tr>")
        _csv_rows.append(_csv)
    _h.append("</tbody></table></div>")

    _active = sum(1 for nm in df_s["_nm"] if cells.get(nm))
    st.caption(f"輸出時間：{_now.strftime('%Y-%m-%d %H:%M')}　｜　{_d_from} ～ {_d_to}　｜　學生 {len(df_s)} 位，其中 {_active} 位這 30 天有作答")
    st.caption("🔤單字＝單字題　📝文法＝單選、重組　📖閱讀＝閱讀單句、閱讀重組　🗣️對話＝對話練習（句數＋自評說對了的比例）　｜　名字下面的小表格是最近 7／14／30 天的作答天數、測驗題數和正確率（＋練＝練習題數）：綠≥80%、黃60–79%、紅<60%")
    st.markdown(_css + "".join(_h), unsafe_allow_html=True)
    st.download_button("⬇️ 下載這張表（CSV，可用 Excel 開）",
                       pd.DataFrame(_csv_rows).to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"學習總覽_{_d_to}.csv", mime="text/csv", key="ov_csv")

# ── Tab（教師/Admin 視角：全班）──────────────────────────────────────────────
tab_report, tab_tasks, tab_overview = st.tabs(["👩‍🎓 學生學習報告", "📋 學生任務列表", "📅 學習總覽"])  # V2.20：學習總覽放最後

with tab_overview:
    _render_overview_tab()

# ══════════════════════════════════════════════════════════════════════════════
# Tab2：全能英文學習報告
# ══════════════════════════════════════════════════════════════════════════════
with tab_report:
    # V2.07：不再載入全班答題列表（很慢）；改為學生名單，點名字在新分頁開啟該生的學習報告
    st.subheader("👩‍🎓 學生學習報告")
    st.caption("點學生名字，會在新分頁開啟該生的「我的學習報告」（和學生自己登入看到的一樣，不必輸入帳號密碼），可同時開好幾位學生。連結 12 小時內有效。")
    _sl1, _sl2 = st.columns([4, 1])
    if _sl2.button("🔄 更新名單", key="stu_list_refresh", use_container_width=True):
        load_students.clear()
        st.rerun()
    df_sl = load_students()
    if df_sl.empty or "姓名" not in df_sl.columns:
        _students_load_failed("sl")
    else:
        df_sl = df_sl[df_sl["姓名"].astype(str).str.strip() != ""].copy()
        # V2.11：帳號是 4 位數（試算表可能讀成 85.0 → 補回 0085）
        if "帳號" in df_sl.columns:
            df_sl["帳號"] = df_sl["帳號"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).apply(
                lambda a: a.zfill(4) if a.isdigit() else a)
        if "分組" not in df_sl.columns:
            df_sl["分組"] = ""
        df_sl = df_sl[~df_sl["分組"].astype(str).str.strip().str.upper().isin(["ADMIN", "TEACHER"])]
        # V2.13：可一次貼上一串學生名單（姓名或帳號，用空白、逗號、頓號或換行分隔）
        # V2.14：加「送出」「清除」按鈕
        def _stu_search_clear():
            st.session_state["stu_list_kw_in"] = ""
            st.session_state["stu_list_q"] = ""
        with _sl1.form("stu_search_form", clear_on_submit=False, border=False):
            _kw_in = st.text_area("🔍 搜尋姓名或帳號（可一次貼上多位學生）", key="stu_list_kw_in", height=80,
                                  placeholder="例：王小明 林阿明 0085（空白、逗號、頓號或換行分隔）\n只打一個時可輸入部分姓名或帳號")
            _fb1, _fb2, _fb3 = st.columns([1, 1, 4])
            _do_search = _fb1.form_submit_button("🔍 送出", type="primary", use_container_width=True)
            _fb2.form_submit_button("🧹 清除", use_container_width=True, on_click=_stu_search_clear)
        if _do_search:
            st.session_state["stu_list_q"] = _kw_in
        _kw = st.session_state.get("stu_list_q", "") or ""
        _tokens = [x for x in re.split(r"[\s,，、;；/]+", _kw.strip()) if x] if _kw.strip() else []
        _not_found = []
        if _tokens:
            _acc = df_sl["帳號"].astype(str) if "帳號" in df_sl.columns else pd.Series("", index=df_sl.index)
            _nm_s = df_sl["姓名"].astype(str).str.strip()
            if len(_tokens) > 1:
                _mask = pd.Series(False, index=df_sl.index)
                for _tk in _tokens:
                    _tk4 = _tk.zfill(4) if _tk.isdigit() else _tk
                    _hit = (_nm_s == _tk) | (_acc == _tk4)
                    if not _hit.any():
                        _hit = _nm_s.str.contains(_tk, regex=False)   # 名字不完整時改用部分比對
                    if not _hit.any():
                        _not_found.append(_tk)
                    _mask = _mask | _hit
                df_sl = df_sl[_mask]
            else:
                _k = _tokens[0]
                df_sl = df_sl[_nm_s.str.contains(_k, regex=False) | _acc.str.contains(_k, regex=False)]
        if _not_found:
            st.warning("找不到：" + "、".join(_not_found))
        if df_sl.empty:
            st.info("找不到符合的學生")
        _base = _dash_base_url()
        _ncol = 6
        # V2.08：依 學年 → 組別 → 姓名 排列
        if "學年" not in df_sl.columns:
            df_sl["學年"] = ""
        # V2.10：學年用整數（試算表讀進來可能是 114.0）
        df_sl["_sy"] = pd.to_numeric(df_sl["學年"].astype(str).str.strip(), errors="coerce").round().astype("Int64")
        df_sl["_gp"] = df_sl["分組"].astype(str).str.strip()
        df_sl["_nm"] = df_sl["姓名"].astype(str).str.strip()
        df_sl = df_sl.sort_values(["_sy", "_gp", "_nm"])
        # V2.09：表格化顯示，最後一欄點連結在新分頁開啟學習報告
        _tbl = pd.DataFrame({
            "色": [_year_color(v)[1] if pd.notna(v) else "" for v in df_sl["_sy"].tolist()],
            "學年": df_sl["_sy"].astype("Int64").reset_index(drop=True),
            "組別": df_sl["_gp"].tolist(),
            "姓名": df_sl["_nm"].tolist(),
            "帳號": df_sl["帳號"].tolist() if "帳號" in df_sl.columns else [""] * len(df_sl),
            "學習報告": [_base + _make_view_query(n) for n in df_sl["_nm"].tolist()],
        })
        if not _tbl.empty:
            st.caption(f"共 {len(_tbl)} 位學生　｜　點「📊 開啟報告」會在新分頁顯示該生的學習報告　｜　分頁標題是學生姓名，小圖示顏色＝學年、字＝姓名最後一字")
            # V2.13：搜尋後可一次在新分頁開啟列出的所有學生報告
            if _tokens and len(_tbl) <= 40:
                import json as _json
                import streamlit.components.v1 as _components
                _urls = _json.dumps(_tbl["學習報告"].tolist())
                _components.html(f"""
<button id="openall" style="padding:8px 16px;font-size:15px;border-radius:8px;border:1px solid #ff4b4b;
  background:#ff4b4b;color:#fff;cursor:pointer;">🚀 一次開啟這 {len(_tbl)} 位學生的報告</button>
<span id="msg" style="margin-left:10px;font-size:13px;color:#888;font-family:sans-serif;"></span>
<script>
const urls = {_urls};
document.getElementById('openall').onclick = () => {{
  let ok = 0;
  for (const u of urls) {{ const w = window.open(u, '_blank'); if (w) ok++; }}
  document.getElementById('msg').textContent = ok < urls.length
    ? `只開了 ${{ok}} 個分頁：請在網址列右側允許此網站的「彈出式視窗」後再按一次`
    : `已開啟 ${{ok}} 個分頁`;
}};
</script>""", height=52)
            elif _tokens:
                st.caption("⚠️ 一次最多開 40 位學生，請縮小名單後再使用「一次開啟」。")
            # V2.11：表格不佔滿整頁，欄寬依內容
            st.dataframe(
                _tbl, hide_index=True, use_container_width=False, width=560,
                height=min(35 * (len(_tbl) + 1) + 3, 720),
                column_config={
                    "色":       st.column_config.TextColumn("色", width="small", help="學年顏色，和學生報告分頁的小圖示顏色相同"),
                    "學年":     st.column_config.NumberColumn("學年", format="%d", width="small"),
                    "組別":     st.column_config.TextColumn("組別", width="small"),
                    "姓名":     st.column_config.TextColumn("姓名", width="small"),
                    "帳號":     st.column_config.TextColumn("帳號", width="small"),
                    "學習報告": st.column_config.LinkColumn("學習報告", display_text="📊 開啟報告", width="small"),
                },
            )



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
