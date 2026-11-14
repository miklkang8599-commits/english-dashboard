# ╔══════════════════════════════════════════════════════════╗
# ║  英文全能練習系統 — 全班學習報告 (獨立版)                ║
# ║  dashboard.py  V2.13                                     ║
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
DASHBOARD_VERSION = "2.13"

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

def load_logs_for_student(stu_name: str, date_from: str = None) -> pd.DataFrame:
    """只撈單一學生的 logs，不用 cache，每次即時取得
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

def _render_detail(tdf):
    """顯示詳細答題清單，格式同數據監控"""
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

def _session_summary(s: dict) -> str:
    stt = _session_stats(s["df"])
    txt = f"🕒 {_fmt_ts(s['start'], with_date=False)}　{s['mode']}｜{s['task']}"
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

# 老師點的學生連結：驗證簽章後直接以該生身分顯示學習報告
try:
    _qp = st.query_params
    _vs, _ve, _vg = _qp.get("view_stu"), _qp.get("exp"), _qp.get("sig")
    if _vs and _ve and _vg and st.session_state.get("dash_view_stu") != _vs:
        if int(_ve) >= int(_time_mod.time()) and _hmac.compare_digest(_view_sig(_vs, int(_ve)), str(_vg)):
            _grp_v = ""
            _df_sv = load_students()
            if not _df_sv.empty and "姓名" in _df_sv.columns and "分組" in _df_sv.columns:
                _m = _df_sv[_df_sv["姓名"].astype(str).str.strip() == _vs]
                if not _m.empty:
                    _grp_v = str(_m.iloc[0]["分組"])
            st.session_state.update({"dash_logged_in": True, "dash_role": "student", "dash_name": _vs,
                                     "dash_group": _grp_v, "dash_view_stu": _vs})
        else:
            st.warning("⚠️ 學生報告連結已過期或無效，請回老師的學生名單重新點選。")
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
    st.subheader(f"📋 {_name} 的學習紀錄")

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
        _auto_on = _auto_c1.toggle("⏱ 自動更新（每 30 秒）", value=True, key="stu_auto_refresh")
        if _auto_c2.button("🔄 立即更新", type="primary", key="stu_refresh_main", use_container_width=True):
            load_assignments.clear()
            st.rerun()

        @st.fragment(run_every=30 if _auto_on else None)
        def _stu_report_fragment():
            df_mine = load_logs_for_student(_name, date_from=_stu_from_str)
            if not df_mine.empty and "時間" in df_mine.columns:
                df_mine = df_mine[(df_mine["時間"].astype(str).str[:10] >= _stu_from_str) &
                                  (df_mine["時間"].astype(str).str[:10] <= _stu_to_str)]
            if not df_mine.empty and "結果" in df_mine.columns:
                df_mine = df_mine[~df_mine["結果"].astype(str).str.contains("📖", na=False)]

            st.caption(f"📅 {_stu_from_str} ～ {_stu_to_str}　｜　最後更新：{get_now().strftime('%H:%M:%S')}")
            if df_mine.empty:
                st.info("此時間範圍內無答題資料")
                return

            df_a_mine = load_assignments()
            _aj    = df_a_mine.to_json(orient="records") if not df_a_mine.empty else "[]"
            _qtask = _build_qid_task_map_all(_aj)
            df_mine = df_mine.copy()
            df_mine["_task"] = df_mine["題目ID"].apply(
                lambda x: _qtask.get(str(x).strip(), _qtask.get(re.sub(r'^[A-Za-z]_', '', str(x).strip()), "")))
            if "任務名稱" in df_mine.columns:
                _miss = df_mine["_task"] == ""
                df_mine.loc[_miss, "_task"] = df_mine.loc[_miss, "任務名稱"].fillna("").astype(str).apply(_strip_task_date)

            sessions = _build_sessions(df_mine)
            if not sessions:
                st.info("此時間範圍內無答題資料")
                return

            if st.session_state.get("_no_session_cols"):
                st.caption("ℹ️ 資料庫尚未新增「練習方式／開始時間」欄位，目前依作答時間自動分組，練習方式為推測。")

            # 歷次作答（依開始日期分組，新到舊）
            st.markdown("#### 📜 歷次作答")
            _cur_day = None
            for i, s in enumerate(sessions):
                _day = s["start"].strftime("%Y-%m-%d")
                if _day != _cur_day:
                    _cur_day = _day
                    _day_sess = [x for x in sessions if x["start"].strftime("%Y-%m-%d") == _day]
                    _day_el = _sum_elapsed(pd.concat([x["df"] for x in _day_sess], ignore_index=True))
                    _lbl = f"**📅 {_day}（{_WEEKDAY_CN[s['start'].weekday()]}）**　共 {len(_day_sess)} 次作答"
                    if _day_el:
                        _lbl += f"　⏱ {_day_el}"
                    st.markdown(_lbl)
                _summary = _session_summary(s)
                with st.expander(_summary, expanded=False):
                    _render_detail(s["df"])

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

# ── Tab（教師/Admin 視角：全班）──────────────────────────────────────────────
tab_report, tab_tasks = st.tabs(["👩‍🎓 學生學習報告", "📋 學生任務列表"])

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
        st.info("讀不到 students 工作表")
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
        _kw = _sl1.text_area("🔍 搜尋姓名或帳號（可一次貼上多位學生）", key="stu_list_kw", height=80,
                             placeholder="例：王小明 林阿明 0085（空白、逗號、頓號或換行分隔）\n只打一個時可輸入部分姓名或帳號")
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
            "學年": df_sl["_sy"].astype("Int64").reset_index(drop=True),
            "組別": df_sl["_gp"].tolist(),
            "姓名": df_sl["_nm"].tolist(),
            "帳號": df_sl["帳號"].tolist() if "帳號" in df_sl.columns else [""] * len(df_sl),
            "學習報告": [_base + _make_view_query(n) for n in df_sl["_nm"].tolist()],
        })
        if not _tbl.empty:
            st.caption(f"共 {len(_tbl)} 位學生　｜　點「📊 開啟報告」會在新分頁顯示該生的學習報告")
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
                _tbl, hide_index=True, use_container_width=False, width=520,
                height=min(35 * (len(_tbl) + 1) + 3, 720),
                column_config={
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
