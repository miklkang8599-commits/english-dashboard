# ==============================================================================
# 🧩 英文全能練習系統 (V2.9.481 - 跟著唸AI評分logs版)
# ==============================================================================
# 📌 版本編號 (VERSION): 2.9.481
# 📅 更新日期: 2026-03-14
# 🛠️ 修復重點：
#    1. [核心] set_page_config 移至最頂部，避免潛在初始化錯誤。
#    2. [資料] conn.create() → append 邏輯，logs/assignments 不再被覆蓋。
#    3. [功能] 單選題補上選項文字 (選項A/B/C/D 欄位)。
#    4. [穩定] 句編號 int() 轉換改用 pd.to_numeric 加保護。
#    5. [效能] load_dynamic_data 加上 @st.cache_data(ttl=10)。
#    6. [穩定] 資料載入失敗時提早 st.stop()，避免後續 None 崩潰。
# 🆕 新增功能：
#    7. [Box B] 新增「📖 題目講解」tab：篩選學生與題目範圍、顯示各學生
#              最近答案、老師可輸入講解備註、點選完成後寫入 logs (結果='📖 講解')。
# ==============================================================================

import streamlit as st
import pandas as pd
import random
import re
import requests
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection
from supabase import create_client, Client

VERSION = "2.9.481"

# ==============================================================================
# ✅ 修復 1：set_page_config 必須是第一個 Streamlit 呼叫
# ==============================================================================
st.set_page_config(page_title=f"英文練習系統 V{VERSION}", layout="wide")

# ------------------------------------------------------------------------------
# 📦 【盒子 A：系統核心 (時區與基礎邏輯)】
# ------------------------------------------------------------------------------
def get_now():
    """物理鎖定台灣時間 (GMT+8)"""
    return datetime.utcnow() + timedelta(hours=8)

def standardize(v):
    """ID 標準化"""
    val = str(v).split('.')[0].strip()
    return val.zfill(4) if val.isdigit() else val

def clean_string_for_compare(s):
    """標點忽略比對邏輯 (含括號相容)"""
    s = str(s)
    s = s.replace("\u2018", "'").replace("\u2019", "'")  # 彎引號→直引號
    s = re.sub(r'\s+', '', s)          # 去除所有空白（含全形空格、換行、Tab）
    s = re.sub(r'[.,?!:;()\-]', '', s) # 去除標點
    return s.lower().strip()

def show_version_caption():
    """全域版號顯示組件"""
    st.caption(f"🚀 系統版本：Ver {VERSION} | 🌍 台灣時間鎖定 (GMT+8)")

def is_admin(group_id):
    """ADMIN 和 TEACHER 都有管理後台權限"""
    return group_id in ("ADMIN", "TEACHER")

# 初始化 Session State
st.session_state.setdefault('range_confirmed', False)
st.session_state.setdefault('quiz_loaded', False)
st.session_state.setdefault('ans', [])
st.session_state.setdefault('used_history', [])
st.session_state.setdefault('show_analysis', False)

# 建立 GSheets 連線
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)  # 靜態資料快取 10 分鐘（題庫/學生帳號不常變動）
@st.cache_data(ttl=600)
def load_students_only():
    """只載入學生帳號（登入驗證用），速度快"""
    try:
        return conn.read(worksheet="students", ttl=600).fillna("").astype(str).replace(r'\.0$', '', regex=True)
    except:
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_core_data():
    """高優先級：重組 + 單選（答題最常用）"""
    try:
        df_q = conn.read(worksheet="重組", ttl=600).fillna("").astype(str).replace(r'\.0$', '', regex=True)
    except:
        df_q = pd.DataFrame()
    try:
        df_mcq = conn.read(worksheet="單選", ttl=600).fillna("").astype(str).replace(r'\.0$', '', regex=True)
    except:
        df_mcq = pd.DataFrame()
    df_s = load_students_only()
    return df_q, df_s, df_mcq

@st.cache_data(ttl=600)
def load_extended_data():
    """中優先級：朗讀 + 拼單字 + 閱讀單句"""
    try:
        df_r = conn.read(worksheet="朗讀", ttl=600).fillna("").astype(str).replace(r'\.0$', '', regex=True)
    except:
        df_r = pd.DataFrame()
    try:
        df_v = conn.read(worksheet="拼單字", ttl=600).fillna("").astype(str).replace(r'\.0$', '', regex=True)
    except:
        df_v = pd.DataFrame()
    try:
        df_rm = conn.read(worksheet="閱讀單句", ttl=600).fillna("").astype(str).replace(r'\.0$', '', regex=True)
        df_rm['_type'] = 'reading_mcq'
    except:
        df_rm = pd.DataFrame()
    return df_r, df_v, df_rm

@st.cache_data(ttl=600)
def load_listening_data():
    """低優先級：聽力音標 + 聽力句子重組"""
    try:
        df_lp = conn.read(worksheet="聽力音標", ttl=600).fillna("").astype(str).replace(r'\.0$', '', regex=True)
        if 'KK符號' in df_lp.columns:
            df_lp['KK符號'] = df_lp['KK符號'].str.strip().str.strip('[]').str.strip()
    except:
        df_lp = pd.DataFrame()
    try:
        df_ls = conn.read(worksheet="聽力句子重組", ttl=600).fillna("").astype(str).replace(r'\.0$', '', regex=True)
    except:
        df_ls = pd.DataFrame()
    return df_lp, df_ls

def load_static_data():
    """整合全部（相容舊版呼叫）"""
    df_q, df_s, df_mcq      = load_core_data()
    df_r, df_v, df_rm        = load_extended_data()
    df_lp, df_ls             = load_listening_data()
    return df_q, df_s, df_r, df_v, df_rm, df_mcq, df_lp, df_ls

# ==============================================================================
# Supabase 客戶端
# ==============================================================================
@st.cache_resource
def get_supabase() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

# 欄位對應：Supabase英文 ↔ 程式中文
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


def _sort_task_names(names):
    """依序號後的名稱排序任務清單（移除 [Txxxxxxxx] 前綴後排列）"""
    def _key(n):
        return re.sub(r'^\[T\d+\]\s*', '', str(n)).strip().lower()
    return sorted(names, key=_key)

def _get_ls_qid(row):
    """產生聽力句子重組題目ID：LS_版本_年度_冊編號_單元_課編號_句編號"""
    return f"LS_{row.get('版本','')}_{row.get('年度','')}_{row.get('冊編號','')}_{row.get('單元','')}_{row.get('課編號','')}_{row.get('句編號','')}"

def _ls_split_words(sentence):
    """將英文句子拆成單字清單（保留數字、字母、縮寫）"""
    import re as _re_ls
    words = _re_ls.findall(r"[A-Za-z0-9]+(?:['\u2018\u2019][A-Za-z0-9]+)*", sentence)
    return words

def _get_lp_qid(row):
    """產生聽力音標題目ID：LP_{版本}_{單元編號}_{組編號}_{符號編號}"""
    return f"LP_{row.get('版本','')}_{row.get('單元編號','')}_{row.get('組編號','')}_{row.get('符號編號','')}"

def _get_lp_distractors(df_lp, correct_row, n=3):
    """依編號相近原則取 n 個干擾選項"""
    correct_num = int(str(correct_row.get('總編號', '0')).split('-')[0]) if str(correct_row.get('總編號','')).split('-')[0].isdigit() else 0
    correct_sym = str(correct_row.get('KK符號', ''))
    others = df_lp[df_lp['KK符號'] != correct_sym].copy()
    if others.empty:
        return []
    # 計算與正確答案的編號距離
    def _num(r):
        try:
            return int(str(r.get('總編號', '0')).split('-')[0])
        except:
            return 999
    others['_dist'] = others.apply(lambda r: abs(_num(r) - correct_num), axis=1)
    others = others.sort_values('_dist').drop_duplicates('KK符號')
    return others.head(n).to_dict('records')


    """依序號後的名稱排序任務清單（移除 [Txxxxxxxx] 前綴後排列）"""
    import re as _re_sort
    def _sort_key(n):
        return _re_sort.sub(r'^\[T\d+\]\s*', '', str(n)).strip().lower()
    return sorted(names, key=_sort_key)


def _clean_vocab(w):
    """去除空格、標點、統一大寫，只保留字母，用於拼單字比對"""
    import re as _re_v
    return _re_v.sub(r'[^A-Za-z]', '', str(w)).upper()

def _to_cn(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """把 Supabase 英文欄位名轉回程式用的中文欄位名"""
    return df.rename(columns=col_map)

def _to_en_logs(row: dict) -> dict:
    """把中文欄位的 log 資料轉成英文欄位"""
    return {
        "created_at":     str(row.get("時間", "")),
        "name":           str(row.get("姓名", "")),
        "group_id":       str(row.get("分組", "")),
        "question_id":    str(row.get("題目ID", "")),
        "result":         str(row.get("結果", "")),
        "student_answer": str(row.get("學生答案", "") or ""),
        "score":          str(row.get("分數", "") or ""),
        "task_name":      str(row.get("任務名稱", "") or ""),
        "elapsed_sec":    row.get("作答秒數", None),
    }

def _to_en_assign(row: dict) -> dict:
    """把中文欄位的 assignment 資料轉成英文欄位"""
    return {
        "created_at":        str(row.get("建立時間", "")),
        "task_name":         str(row.get("任務名稱", "")),
        "task_id":           str(row.get("任務編號", "") or ""),
        "target_group":      str(row.get("對象班級", "")),
        "assigned_students": str(row.get("指派學生", "")),
        "student_count":     str(row.get("指派人數", "")),
        "content":           str(row.get("內容", "")),
        "description":       str(row.get("任務說明", "")),
        "question_count":    str(row.get("題目數", "")),
        "question_ids":      str(row.get("題目ID清單", "")),
        "start_date":        str(row.get("開始日期", "")),
        "end_date":          str(row.get("結束日期", "")),
        "ref_students":      str(row.get("參考學生", "")),
        "status":            str(row.get("狀態", "")),
        "task_type":         str(row.get("類型", "")),
        "vocab_cfg":         str(row.get("單字設定", "") or ""),
    }

# ==============================================================================
# 動態資料讀取（Supabase）- 移除快取，每次 rerun 直接讀最新
# ==============================================================================
@st.cache_data(ttl=30)
def load_assignments():
    """只載入 assignments，ttl=30 秒"""
    try:
        sb  = get_supabase()
        res = sb.table("assignments").select("*").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df = _to_cn(df, ASSIGN_COLS)
            df = df.drop(columns=["id"], errors="ignore")
            return df
        return pd.DataFrame()
    except Exception as e:
        st.session_state['_load_error'] = str(e)
        return pd.DataFrame()

@st.cache_data(ttl=60)
def _load_logs_cached():
    """logs 資料，60秒快取，只撈必要欄位"""
    try:
        sb       = get_supabase()
        all_logs = []
        page     = 0
        while True:
            res = sb.table("logs").select(
                "created_at,name,group_id,question_id,result,student_answer,score,task_name"
            ).order("created_at", desc=False) \
             .range(page * 1000, (page + 1) * 1000 - 1) \
             .execute()
            if not res.data:
                break
            all_logs.extend(res.data)
            if len(res.data) < 1000:
                break
            page += 1
        if all_logs:
            df_l = pd.DataFrame(all_logs)
            df_l = _to_cn(df_l, LOGS_COLS)
            return df_l
        return pd.DataFrame()
    except:
        return pd.DataFrame()

def load_dynamic_data():
    """assignments + logs（相容舊版呼叫，不用快取）"""
    df_a = load_assignments()
    df_l = _load_logs_cached()
    return df_a, df_l
    try:
        sb       = get_supabase()
        all_logs = []
        page     = 0
        while True:
            res = sb.table("logs").select(
                "created_at,name,group_id,question_id,result,student_answer,score,task_name"
            ).order("created_at", desc=False) \
             .range(page * 1000, (page + 1) * 1000 - 1) \
             .execute()
            if not res.data:
                break
            all_logs.extend(res.data)
            if len(res.data) < 1000:
                break
            page += 1
        if all_logs:
            df_l = pd.DataFrame(all_logs)
            df_l = _to_cn(df_l, LOGS_COLS)
            return df_l
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# ==============================================================================
# 動態資料寫入（Supabase）
# ==============================================================================
def append_to_sheet(worksheet_name: str, new_row: pd.DataFrame):
    """寫入一筆資料到 Supabase"""
    try:
        sb = get_supabase()
        row_dict = new_row.iloc[0].to_dict()

        if worksheet_name == "logs":
            en_row = _to_en_logs(row_dict)
            result = sb.table("logs").insert(en_row).execute()
        elif worksheet_name == "assignments":
            en_row = _to_en_assign(row_dict)
            result = sb.table("assignments").insert(en_row).execute()
        else:
            return False

        import time as _t; _t.sleep(0.5)
        return True
    except Exception as e:
        st.error(f"❌ Supabase 寫入失敗：{type(e).__name__}: {e}")
        return False

# ------------------------------------------------------------------------------
# 🔐 【權限控管與登入】
# ------------------------------------------------------------------------------
if not st.session_state.get('logged_in', False):
    # 登入頁只載入學生帳號（速度快）
    df_s = load_students_only()
    if df_s is None or df_s.empty:
        load_students_only.clear()
        df_s = load_students_only()
    _, c, _ = st.columns([1, 1.2, 1])
    with c:
        if df_s is None or df_s.empty:
            st.error("⚠️ 帳號資料讀取失敗，請稍後重試。")
            if st.button("🔄 重新載入", type="primary", use_container_width=True, key="login_reload"):
                load_students_only.clear()
                st.rerun()
            st.stop()
        st.markdown("### 🔵 系統登入")
        with st.form("login_form"):
            i_id = st.text_input("帳號 (學號/員工編號)", key="l_id")
            i_pw = st.text_input("密碼", type="password", key="l_pw")
            _login_submitted = st.form_submit_button("🚀 登入系統", use_container_width=True, type="primary")
        # Enter 鍵觸發登入
        st.markdown("""<script>
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('登入系統'));
                if (btn) btn.click();
            }
        });
        </script>""", unsafe_allow_html=True)
        if _login_submitted:
            std_id, std_pw = standardize(i_id), standardize(i_pw)
            df_s['c_id'] = df_s['帳號'].apply(standardize)
            df_s['c_pw'] = df_s['密碼'].apply(standardize)
            user = df_s[df_s['c_id'] == std_id]
            if not user.empty and user.iloc[0]['c_pw'] == std_pw:
                _was_loaded = st.session_state.get('static_loaded', False)
                st.session_state.clear()
                st.session_state.update({
                    "logged_in": True,
                    "user_id": f"EA{std_id}",
                    "user_name": user.iloc[0]['姓名'],
                    "group_id": user.iloc[0]['分組'],
                    "view_mode": "管理後台" if is_admin(user.iloc[0]["分組"]) else "練習模式",
                    "static_loaded": _was_loaded,
                })
                st.rerun()
            else:
                st.error("❌ 帳號或密碼錯誤")
        show_version_caption()
    st.stop()

# 載入靜態資料（有快取，重複登入幾乎瞬間）
if 'static_loaded' not in st.session_state:
    with st.spinner("⏳ 載入題庫中，請稍候..."):
        df_q, df_s, df_mcq = load_core_data()
        df_r, df_v, df_rm  = load_extended_data()
        df_lp, df_ls       = load_listening_data()
    st.session_state['static_loaded'] = True
else:
    df_q, df_s, df_mcq = load_core_data()
    df_r, df_v, df_rm  = load_extended_data()
    df_lp, df_ls       = load_listening_data()
df_a = load_assignments()
# df_l 延遲載入（不立即讀 logs）
df_l = pd.DataFrame()

def _get_df_l():
    """懶載入 logs，只在需要時才查詢"""
    _cached = _load_logs_cached()
    return _cached if not _cached.empty else pd.DataFrame()

if df_q is None or df_s is None:
    # 立即清快取重試一次
    load_core_data.clear(); load_extended_data.clear(); load_listening_data.clear()
    df_q, df_s, df_mcq = load_core_data()
df_r, df_v, df_rm = load_extended_data()
df_lp, df_ls = load_listening_data()

if df_q is None or df_s is None:
    st.error("⚠️ 題庫讀取失敗，請按下方按鈕重試。")
    st.caption("（通常是 Google Sheets API 暫時限流，幾秒後即可恢復）")
    err = st.session_state.get('_load_error', '')
    if err:
        with st.expander("🔍 錯誤詳情（給老師看）"):
            st.code(err)
    if st.button("🔄 重新載入", type="primary", use_container_width=True):
        load_core_data.clear(); load_extended_data.clear(); load_listening_data.clear()
        st.rerun()
    st.stop()

# ------------------------------------------------------------------------------
# 📦 【盒子 E：側邊排行】
# ------------------------------------------------------------------------------
with st.sidebar:
    st.write(f"👤 {st.session_state.user_name} ({st.session_state.group_id})")
    if is_admin(st.session_state.group_id):
        st.session_state.view_mode = st.radio("功能切換：", ["管理後台", "進入練習"], key="sidebar_view_mode")
    if st.button("🚪 登出系統", use_container_width=True, key="sidebar_logout"):
        st.session_state.clear()
        st.rerun()

    # 裝置類型（影響單選題選項排列）
    _device = st.selectbox(
        "📱 裝置類型",
        ["電腦/平板（2欄）", "手機（1欄）"],
        key="device_layout",
        label_visibility="collapsed",
        help="選擇裝置類型，調整單選題選項排列方式"
    )
    st.session_state['mcq_cols'] = 1 if "手機" in _device else 2

    st.divider()
    st.markdown("🏆 **成就排行**")
    now_sb = get_now()
    today  = now_sb.date()

    # 時段選擇：用 selectbox（不產生額外按鈕 rerun）
    _periods = ["今日", "昨天", "前天", "三天", "七天", "30天"]
    period = st.selectbox("📅 統計期間", _periods, key="sb_period", label_visibility="collapsed")

    _d = {
        "今日": (today, today),
        "昨天": (today - timedelta(days=1), today - timedelta(days=1)),
        "前天": (today - timedelta(days=2), today - timedelta(days=2)),
        "三天": (today - timedelta(days=2), today),
        "七天": (today - timedelta(days=6), today),
        "30天": (today - timedelta(days=29), today),
    }
    date_from, date_to = _d.get(period, (today, today))
    date_from_str = date_from.strftime("%Y-%m-%d")
    date_to_str   = date_to.strftime("%Y-%m-%d")
    st.caption(f"📅 {date_from_str} ～ {date_to_str}")

    # 更新按鈕：只有按了才重新計算
    _lb_cache_key = f"_lb_{period}_{st.session_state.group_id}"
    _need_update  = False  # 不自動計算，等使用者按更新

    if st.button("🔄 更新排行榜", use_container_width=True, key="lb_refresh") or _need_update:
        df_l = _get_df_l()
        try:
            target_group = st.session_state.group_id if not is_admin(st.session_state.group_id) else None
            df_lb_all = _load_logs_cached()
            if not df_lb_all.empty:
                df_lb = df_lb_all.copy()
                if target_group:
                    df_lb = df_lb[df_lb["分組"] == target_group]
                df_lb = df_lb[
                    (df_lb["時間"].str[:10] >= date_from_str) &
                    (df_lb["時間"].str[:10] <= date_to_str)
                ]
                df_lb_ans = df_lb[
                    ~df_lb["結果"].str.contains("📖|練習", na=False)
                ]
                if target_group:
                    members = sorted(df_s[df_s["分組"] == target_group]["姓名"].tolist())
                else:
                    members = sorted(df_s[~df_s["分組"].isin(["ADMIN","TEACHER"])]["姓名"].tolist())
                member_stats = []
                for m in members:
                    m_logs = df_lb_ans[df_lb_ans["姓名"] == m]
                    member_stats.append((m, len(m_logs[m_logs["結果"] == "✅"]), len(m_logs)))
                member_stats.sort(key=lambda x: x[1], reverse=True)
                st.session_state[_lb_cache_key] = member_stats
            else:
                st.session_state[_lb_cache_key] = []
        except Exception as e:
            st.caption(f"排行榜載入失敗：{e}")

    # 顯示快取結果（不重新計算）
    member_stats = st.session_state.get(_lb_cache_key, [])
    if member_stats:
        for rank, (m, correct, total_ans) in enumerate(member_stats, 1):
            medal = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else "👤"))
            color = "#c8a400" if rank == 1 else ("#9e9e9e" if rank == 2 else ("#cd7f32" if rank == 3 else "#333"))
            st.markdown(
                f'<div style="font-size:12px;color:{color};">{medal} {m}: {correct} ({total_ans} 題)</div>',
                unsafe_allow_html=True
            )
    else:
        st.caption("暫無資料，請按更新")
    st.caption(f"Ver {VERSION}")

# 共用：產生含學生名字的班級標籤
def _group_label(g):
    stus = sorted(df_s[df_s['分組'] == g]['姓名'].tolist())
    return f"{g}（{'、'.join(stus)}）"

# 共用：產生列印用 HTML
def _gen_print_html(questions, mode, title="題目列表", group_logs=None, target_students=None):
    """
    mode:
      1 = 只列印題目
      2 = 題目 + 正確答案 + 解析
      3 = 題目 + 答案 + 解析 + 學生答題紀錄
    """
    rows_html = ""
    for i, q in enumerate(questions, 1):
        q_unit  = str(q.get('單元', ''))
        if '單選' in q_unit:
            q_text = str(q.get('單選題目') or q.get('中文題目') or '').strip()
            q_ans  = str(q.get('單選答案') or '').strip()
        elif '單字' in q_unit or q.get('_type') == 'vocab':
            q_text = str(q.get('中文意思') or '').strip()
            q_ans  = str(q.get('英文單字') or '').strip()
        elif q.get('_type') == 'reading' or '朗讀' in q_unit:
            q_text = str(q.get('朗讀句子') or '').strip()
            q_ans  = q_text
        else:
            q_text = str(q.get('重組中文題目') or q.get('中文題目') or '').strip()
            q_ans  = str(q.get('重組英文答案') or q.get('英文答案') or '').strip()
        q_analysis = str(q.get('解析') or q.get('單選解析') or '').strip()
        qid = str(q.get('題目ID', ''))

        ans_block     = ""
        analysis_block = ""
        record_block  = ""

        if mode >= 2:
            ans_block = f"<div class='ans'>✅ {q_ans}</div>"
            if q_analysis:
                analysis_block = f"<div class='note'>📝 {q_analysis}</div>"

        if mode >= 3 and group_logs is not None and target_students:
            stu_records = []
            for stu in target_students:
                stu_rows = group_logs[
                    (group_logs['姓名'] == stu) &
                    (group_logs['題目ID'] == qid) &
                    (~group_logs['結果'].str.contains('📖', na=False))
                ] if not group_logs.empty else pd.DataFrame()
                if stu_rows.empty:
                    stu_records.append(f"<span class='stu'>{stu}：未作答</span>")
                else:
                    hist = "".join(stu_rows.sort_values('時間')['結果'].tolist())
                    stu_records.append(f"<span class='stu'>{stu}：{hist}</span>")
            record_block = "<div class='records'>" + "　".join(stu_records) + "</div>"

        rows_html += f"""
        <div class='qblock'>
          <div class='qnum'>{i}.</div>
          <div class='qbody'>
            <div class='qtxt'>{q_text}</div>
            {ans_block}{analysis_block}{record_block}
          </div>
        </div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
    <title>{title}</title>
    <style>
      body {{ font-family: 'Microsoft JhengHei', Arial, sans-serif; font-size:13px; margin:20px; color:#222; }}
      h2 {{ font-size:16px; border-bottom:2px solid #333; padding-bottom:6px; }}
      .qblock {{ display:flex; margin-bottom:14px; page-break-inside:avoid; }}
      .qnum {{ min-width:30px; font-weight:bold; color:#555; }}
      .qbody {{ flex:1; }}
      .qtxt {{ margin-bottom:4px; white-space:pre-wrap; line-height:1.6; }}
      .ans {{ color:#1a7a1a; font-size:12px; margin:2px 0; }}
      .note {{ color:#555; font-size:11px; margin:2px 0; }}
      .records {{ font-size:11px; color:#333; margin-top:4px; background:#f5f5f5; padding:4px 6px; border-radius:4px; }}
      .stu {{ margin-right:10px; }}
      @media print {{
        body {{ margin:10px; }}
        button {{ display:none; }}
      }}
    </style></head><body>
    <h2>{title}</h2>
    {rows_html}
    <script>window.onload = function(){{ window.print(); }}</script>
    </body></html>"""
    return html

def _gen_print_pdf(questions, mode, title="題目列表", group_logs=None, target_students=None):
    """產生 PDF bytes，支援中文，格式清晰"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib import colors
    import io

    # 內建 CJK 字體
    # 鎖定使用 HeiseiMin-W3（明體，支援繁體中文）
    fn = 'Helvetica'
    for cjk in ['HeiseiMin-W3', 'HeiseiKakuGo-W5', 'STSong-Light']:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(cjk))
            fn = cjk
            break
        except:
            continue

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)

    black = colors.black
    style_title = ParagraphStyle('title', fontName=fn, fontSize=15, leading=22,
                                 spaceAfter=6, textColor=black, fontWeight='bold')
    style_q     = ParagraphStyle('q',    fontName=fn, fontSize=14, leading=22,
                                 spaceAfter=0, textColor=black, leftIndent=0)
    style_sub   = ParagraphStyle('sub',  fontName=fn, fontSize=14, leading=20,
                                 spaceAfter=0, textColor=black, leftIndent=0)
    style_blank = ParagraphStyle('blank',fontName=fn, fontSize=10, leading=14,
                                 spaceAfter=0, textColor=black)

    def safe(t):
        return str(t).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

    story = []
    story.append(Paragraph(safe(title), style_title))
    story.append(HRFlowable(width="100%", thickness=1, color=black))
    story.append(Spacer(1, 4*mm))

    for i, q in enumerate(questions, 1):
        q_unit = str(q.get("單元", ""))
        if "單選" in q_unit:
            q_text = str(q.get("單選題目") or q.get("中文題目") or "")
            q_ans  = str(q.get("單選答案") or "").strip()
        elif "單字" in q_unit or q.get("_type") == "vocab":
            q_text = str(q.get("中文意思") or "")
            q_ans  = str(q.get("英文單字") or "").strip()
        elif q.get("_type") == "reading" or "朗讀" in q_unit:
            q_text = str(q.get("朗讀句子") or "")
            q_ans  = q_text.strip()
        else:
            q_text = str(q.get("重組中文題目") or q.get("中文題目") or "")
            q_ans  = str(q.get("重組英文答案") or q.get("英文答案") or "").strip()
        q_analysis = str(q.get("解析") or q.get("單選解析") or "").strip()
        qid = str(q.get("題目ID", ""))

        # 題目
        story.append(Paragraph(f"<b>{i}.</b>  {safe(q_text)}", style_q))

        if mode == 1:
            # 只有題目：底下留 2mm 空白
            story.append(Spacer(1, 2*mm))
        elif mode >= 2:
            # 答案
            story.append(Spacer(1, 2*mm))
            story.append(Paragraph(f"<b>答案：</b>{safe(q_ans)}", style_sub))
            if q_analysis:
                story.append(Paragraph(f"<b>解析：</b>{safe(q_analysis)}", style_sub))
            if mode >= 3 and group_logs is not None and target_students:
                recs = []
                for stu in target_students:
                    rows = group_logs[
                        (group_logs["姓名"] == stu) &
                        (group_logs["題目ID"] == qid) &
                        (~group_logs["結果"].str.contains("📖", na=False))
                    ] if not group_logs.empty else pd.DataFrame()
                    hist = "".join(rows.sort_values("時間")["結果"].tolist()) if not rows.empty else "未作答"
                    recs.append(f"{stu}：{hist}")
                story.append(Paragraph("　".join(recs), style_sub))
            story.append(Spacer(1, 4*mm))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ── Google Drive 聽力音檔資料夾 ───────────────────────────────────────────────
GDRIVE_AUDIO_FOLDER_ID = "1tp1vjB2kSg60OBrdAj2kPm5fPI1ls9EO"

@st.cache_resource
def get_gdrive_audio_service():
    """取得可讀取 Drive 資料夾的 service（drive.readonly scope）"""
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds_dict = {
        "type": "service_account",
        "project_id":                  st.secrets["connections"]["gsheets"]["project_id"],
        "private_key_id":              st.secrets["connections"]["gsheets"]["private_key_id"],
        "private_key":                 st.secrets["connections"]["gsheets"]["private_key"],
        "client_email":                st.secrets["connections"]["gsheets"]["client_email"],
        "client_id":                   st.secrets["connections"]["gsheets"]["client_id"],
        "auth_uri":                    "https://accounts.google.com/o/oauth2/auth",
        "token_uri":                   "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url":        st.secrets["connections"]["gsheets"].get("client_x509_cert_url", "")
    }
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)

@st.cache_data(ttl=3600)
def load_audio_file_index():
    """讀取音檔資料夾，建立 {總編號: file_id} 對照表，快取 1 小時"""
    try:
        svc     = get_gdrive_audio_service()
        results = svc.files().list(
            q=f"'{GDRIVE_AUDIO_FOLDER_ID}' in parents and trashed=false",
            fields="files(id, name)",
            pageSize=500
        ).execute()
        files = results.get("files", [])
        # 檔名格式：01-p.mp3 → key = "01-p"
        index = {}
        for f in files:
            name_no_ext = f["name"].rsplit(".", 1)[0]  # 去副檔名
            index[name_no_ext.lower()] = f["id"]
        return index
    except Exception as e:
        return {}

def get_audio_url(file_id):
    """回傳可直接播放的 Drive 音檔 URL"""
    return f"https://drive.google.com/uc?export=download&id={file_id}"



@st.cache_resource
def get_gdrive_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds_dict = {
        "type": "service_account",
        "project_id":                  st.secrets["connections"]["gsheets"]["project_id"],
        "private_key_id":              st.secrets["connections"]["gsheets"]["private_key_id"],
        "private_key":                 st.secrets["connections"]["gsheets"]["private_key"],
        "client_email":                st.secrets["connections"]["gsheets"]["client_email"],
        "client_id":                   st.secrets["connections"]["gsheets"]["client_id"],
        "auth_uri":                    "https://accounts.google.com/o/oauth2/auth",
        "token_uri":                   "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url":        st.secrets["connections"]["gsheets"].get("client_x509_cert_url", "")
    }
    creds = Credentials.from_service_account_info(creds_dict,
              scopes=["https://www.googleapis.com/auth/drive.file"])
    return build("drive", "v3", credentials=creds)

def _upload_pdf_to_gdrive(pdf_bytes, filename):
    """上傳 PDF 到 Google Drive，回傳分享連結"""
    from googleapiclient.http import MediaIoBaseUpload
    import io
    svc   = get_gdrive_service()
    meta  = {"name": filename, "parents": [GDRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
    f     = svc.files().create(
                body=meta, media_body=media, fields="id,webViewLink",
                supportsAllDrives=True
            ).execute()
    svc.permissions().create(
        fileId=f["id"],
        body={"type":"anyone","role":"reader"},
        supportsAllDrives=True
    ).execute()
    return f["webViewLink"]

def _upload_gdocs_to_gdrive(text_content, filename):
    """上傳純文字並轉成 Google Docs，回傳分享連結"""
    from googleapiclient.http import MediaIoBaseUpload
    import io
    svc   = get_gdrive_service()
    # 直接上傳為 Google Docs 格式
    meta  = {
        "name": filename,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [GDRIVE_FOLDER_ID]
    }
    media = MediaIoBaseUpload(io.BytesIO(text_content.encode('utf-8')), mimetype="text/plain")
    doc   = svc.files().create(
                body=meta, media_body=media, fields="id,webViewLink",
                supportsAllDrives=True
            ).execute()
    svc.permissions().create(
        fileId=doc["id"],
        body={"type":"anyone","role":"writer"},
        supportsAllDrives=True
    ).execute()
    return doc["webViewLink"]

def _create_question_sheet(questions, mode, title="題目列表", group_logs=None, target_students=None):
    """建立 Google Sheets 題目表，回傳試算表連結"""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_dict = {
        "type": "service_account",
        "project_id":                  st.secrets["connections"]["gsheets"]["project_id"],
        "private_key_id":              st.secrets["connections"]["gsheets"]["private_key_id"],
        "private_key":                 st.secrets["connections"]["gsheets"]["private_key"],
        "client_email":                st.secrets["connections"]["gsheets"]["client_email"],
        "client_id":                   st.secrets["connections"]["gsheets"]["client_id"],
        "auth_uri":                    "https://accounts.google.com/o/oauth2/auth",
        "token_uri":                   "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url":        st.secrets["connections"]["gsheets"].get("client_x509_cert_url","")
    }
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc     = gspread.authorize(creds)

    # 在指定資料夾建立試算表
    sh = gc.create(title, folder_id=GDRIVE_FOLDER_ID)
    ws = sh.sheet1

    # 建立標題列
    headers = ["#", "題目"]
    if mode >= 2:
        headers += ["答案", "解析"]
    if mode >= 3 and target_students:
        headers += target_students

    ws.append_row(headers)

    # 寫入題目
    for i, q in enumerate(questions, 1):
        q_unit = str(q.get('單元', ''))
        if '單選' in q_unit:
            q_text = str(q.get('單選題目') or q.get('中文題目') or '').strip()
            q_ans  = str(q.get('單選答案') or '').strip()
        elif '單字' in q_unit or q.get('_type') == 'vocab':
            q_text = str(q.get('中文意思') or '').strip()
            q_ans  = str(q.get('英文單字') or '').strip()
        elif q.get('_type') == 'reading' or '朗讀' in q_unit:
            q_text = str(q.get('朗讀句子') or '').strip()
            q_ans  = q_text
        else:
            q_text = str(q.get('重組中文題目') or q.get('中文題目') or '').strip()
            q_ans  = str(q.get('重組英文答案') or q.get('英文答案') or '').strip()
        q_analysis = str(q.get('解析') or q.get('單選解析') or '').strip()
        qid = str(q.get('題目ID', ''))

        row = [i, q_text]
        if mode >= 2:
            row += [q_ans, q_analysis]
        if mode >= 3 and group_logs is not None and target_students:
            for stu in target_students:
                rows = group_logs[
                    (group_logs['姓名'] == stu) & (group_logs['題目ID'] == qid) &
                    (~group_logs['結果'].str.contains('📖', na=False))
                ] if not group_logs.empty else pd.DataFrame()
                hist = "".join(rows.sort_values('時間')['結果'].tolist()) if not rows.empty else "未作答"
                row.append(hist)
        ws.append_row(row)

    # 格式化標題列（粗體）
    ws.format('A1:Z1', {'textFormat': {'bold': True}, 'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}})
    # 設定任何人可以閱覽
    sh.share(None, perm_type='anyone', role='reader')

    return sh.url

def _gen_plain_text(questions, mode, title="題目列表", group_logs=None, target_students=None):
    """產生純文字（供 Google Docs 用）"""
    lines = [title, "=" * 50, ""]
    for i, q in enumerate(questions, 1):
        q_unit = str(q.get('單元', ''))
        if '單選' in q_unit:
            q_text = str(q.get('單選題目') or q.get('中文題目') or '').strip()
            q_ans  = str(q.get('單選答案') or '').strip()
        elif '單字' in q_unit or q.get('_type') == 'vocab':
            q_text = str(q.get('中文意思') or '').strip()
            q_ans  = str(q.get('英文單字') or '').strip()
        elif q.get('_type') == 'reading' or '朗讀' in q_unit:
            q_text = str(q.get('朗讀句子') or '').strip()
            q_ans  = q_text
        else:
            q_text = str(q.get('重組中文題目') or q.get('中文題目') or '').strip()
            q_ans  = str(q.get('重組英文答案') or q.get('英文答案') or '').strip()
        q_analysis = str(q.get('解析') or q.get('單選解析') or '').strip()
        qid = str(q.get('題目ID', ''))
        lines.append(f"{i}. {q_text}")
        if mode >= 2:
            lines.append(f"   答案：{q_ans}")
            if q_analysis:
                lines.append(f"   解析：{q_analysis}")
        if mode >= 3 and group_logs is not None and target_students:
            for stu in target_students:
                rows = group_logs[
                    (group_logs['姓名'] == stu) & (group_logs['題目ID'] == qid) &
                    (~group_logs['結果'].str.contains('📖', na=False))
                ] if not group_logs.empty else pd.DataFrame()
                hist = "".join(rows.sort_values('時間')['結果'].tolist()) if not rows.empty else "未作答"
                lines.append(f"   {stu}：{hist}")
        lines.append("")
    return "\n".join(lines)

def _gen_csv(questions, mode, group_logs=None, target_students=None):
    """產生 CSV，每題一行，可直接貼入 Google Sheets"""
    import csv, io
    output = io.StringIO()
    headers = ["#", "題目"]
    if mode >= 2:
        headers += ["答案", "解析"]
    if mode >= 3 and target_students:
        headers += target_students
    writer = csv.writer(output)
    writer.writerow(headers)
    for i, q in enumerate(questions, 1):
        q_unit = str(q.get("單元", ""))
        if "單選" in q_unit:
            q_text = str(q.get("單選題目") or q.get("中文題目") or "").strip()
            q_ans  = str(q.get("單選答案") or "").strip()
        elif "單字" in q_unit or q.get("_type") == "vocab":
            q_text = str(q.get("中文意思") or "").strip()
            q_ans  = str(q.get("英文單字") or "").strip()
        elif q.get("_type") == "reading" or "朗讀" in q_unit:
            q_text = str(q.get("朗讀句子") or "").strip()
            q_ans  = q_text
        else:
            q_text = str(q.get("重組中文題目") or q.get("中文題目") or "").strip()
            q_ans  = str(q.get("重組英文答案") or q.get("英文答案") or "").strip()
        q_analysis = str(q.get("解析") or q.get("單選解析") or "").strip()
        qid = str(q.get("題目ID", ""))
        row = [i, q_text]
        if mode >= 2:
            row += [q_ans, q_analysis]
        if mode >= 3 and group_logs is not None and target_students:
            for stu in target_students:
                rows = group_logs[
                    (group_logs["姓名"] == stu) & (group_logs["題目ID"] == qid) &
                    (~group_logs["結果"].str.contains("📖", na=False))
                ] if not group_logs.empty else pd.DataFrame()
                hist = "".join(rows.sort_values("時間")["結果"].tolist()) if not rows.empty else "未作答"
                row.append(hist)
        writer.writerow(row)
    return ("\ufeff" + output.getvalue()).encode("utf-8")

if is_admin(st.session_state.group_id) and st.session_state.view_mode == "管理後台":
    hc1, hc2, hc3 = st.columns([3, 1, 1])
    hc1.markdown("## 🟢 導師中心")
    if hc2.button("🔄 更新資料", use_container_width=True, key="admin_refresh"):
        load_core_data.clear(); load_extended_data.clear(); load_listening_data.clear()
        st.cache_data.clear()
        st.rerun()
    if hc3.button("🧪 測試寫入", use_container_width=True, key="test_write"):
        try:
            sb_t = get_supabase()
            test_row = {
                "created_at": get_now().strftime("%Y-%m-%d %H:%M:%S"),
                "name": "測試",
                "group_id": "TEST",
                "question_id": "TEST_001",
                "result": "🧪",
                "student_answer": "",
                "score": ""
            }
            res = sb_t.table("logs").insert(test_row).execute()
            st.success(f"✅ Supabase 寫入成功！")
        except Exception as e:
            st.error(f"❌ 寫入失敗：{e}")

    t1, t2, t3, t4 = st.tabs(["📋 指派任務", "📋 學生名單", "📖 題目講解", "🏆 競賽結果"])

    with t1:
        # 指派任務獨立更新鍵（只更新 assignments）
        _t1_col1, _t1_col2 = st.columns([5, 1])
        _t1_col1.caption(f"任務資料：{len(df_a)} 筆")
        if _t1_col2.button("🔄", key="t1_refresh", help="更新任務資料"):
            load_assignments.clear()
            st.session_state['_a2_cache_stale'] = True
            st.rerun()
        # 重新取得最新 df_a（可能剛更新）
        df_a = load_assignments()
        # 發布成功後清空表單（在 widget 渲染前執行）
        if st.session_state.pop('t1_clear_form', False):
            for k in [
                # 題型 checkbox
                't1_inc_q', 't1_inc_mcq', 't1_inc_reading', 't1_inc_vocab', 't1_inc_rm',
                # 重組題篩選
                't1_v', 't1_u', 't1_y', 't1_b', 't1_l', 't1_start_sent', 't1_q_count',
                't1_grammar', 't1_diff',
                # 單選題篩選
                'mc_v', 'mc_u', 'mc_y', 'mc_b', 'mc_l', 'mc_start_sent', 'mc_q_count',
                'mc_grammar', 'mc_diff',
                # 朗讀題篩選
                'rt_v', 'rt_u', 'rt_y', 'rt_b', 'rt_l', 'rt_start_sent', 'rt_q_count',
                # 拼單字篩選
                'vt_v', 'vt_u', 'vt_y', 'vt_b', 'vt_l', 'vt_start_sent', 'vt_q_count',
                'vt_mode', 'vt_timer', 'vt_extra',
                # 閱讀單句篩選
                'rmt_v', 'rmt_u', 'rmt_y', 'rmt_b', 'rmt_l', 'rmt_start', 'rmt_count',
                'rmt_grammar', 'rmt_diff',
                # 班級/學生/日期
                't1_group', 't1_mode', 't1_stu', 't1_start', 't1_end',
                # 參考學生
                't1_ref_stu', 't1_ref_logic', 't1_ref_n',
            ]:
                st.session_state.pop(k, None)

        # ══════════════════════════════════════════════════════════════════
        # 區塊一：發布新任務
        # ══════════════════════════════════════════════════════════════════
        st.subheader("📢 發布新任務")

        # ── 基本設定 ──────────────────────────────────────────────────────
        all_groups     = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique().tolist())
        group_opts_t1  = [_group_label(g) for g in all_groups]
        group_map_t1   = {_group_label(g): g for g in all_groups}
        sel_groups_lbl = st.multiselect("目標班級/分組（可複選）", group_opts_t1, default=[], key="t1_group")
        target_groups  = [group_map_t1[l] for l in sel_groups_lbl if l in group_map_t1]

        # 指派對象：依選取班級合併學生名單
        if target_groups:
            group_members = sorted(df_s[df_s['分組'].isin(target_groups)]['姓名'].tolist())
        else:
            group_members = []

        target_mode = st.radio("指派對象", ["全班", "指定學生"], horizontal=True, key="t1_mode")
        if target_mode == "指定學生":
            target_students_t1 = st.multiselect("選擇學生（可複選）", group_members, default=group_members, key="t1_stu")
        else:
            target_students_t1 = group_members

        # 寫入任務時記錄所有選取班級
        target_group = ",".join(target_groups) if target_groups else ""

        # 開始／結束日期
        dc1, dc2 = st.columns(2)
        now_tw_t1  = get_now()
        date_start = dc1.date_input("📅 開始日期", value=now_tw_t1.date(), key="t1_start")
        date_end   = dc2.date_input("📅 結束日期", value=now_tw_t1.date() + timedelta(days=7), key="t1_end")

        # ── 題目範圍篩選（選填） ──────────────────────────────────────────
        # ── 重組題範圍（選填） ────────────────────────────────────────────
        include_q = st.checkbox("✏️ 加入重組題", value=False, key="t1_inc_q")
        df_t1_final = pd.DataFrame()

        if include_q:
            if df_q.empty:
                st.warning("重組工作表尚無資料。")
            else:
                st.markdown("**⚙️ 重組題範圍**")
                tc = st.columns(5)
                t1v = tc[0].selectbox("版本",  sorted(df_q["版本"].unique()), key="t1_v")
                t1u = tc[1].selectbox("單元",  sorted(df_q[df_q["版本"] == t1v]["單元"].unique()), key="t1_u")
                t1y = tc[2].selectbox("年度",  sorted(df_q[(df_q["版本"] == t1v) & (df_q["單元"] == t1u)]["年度"].unique()), key="t1_y")
                t1b = tc[3].selectbox("冊編號", sorted(df_q[(df_q["版本"] == t1v) & (df_q["單元"] == t1u) & (df_q["年度"] == t1y)]["冊編號"].unique()), key="t1_b")
                t1l = tc[4].selectbox("課編號", sorted(df_q[(df_q["版本"] == t1v) & (df_q["單元"] == t1u) & (df_q["年度"] == t1y) & (df_q["冊編號"] == t1b)]["課編號"].unique()), key="t1_l")

                df_t1_scope = df_q[
                    (df_q["版本"] == t1v) & (df_q["單元"] == t1u) &
                    (df_q["年度"] == t1y) & (df_q["冊編號"] == t1b) &
                    (df_q["課編號"] == t1l)
                ].copy()

                extra_cols = st.columns(2)
                if "文法" in df_t1_scope.columns:
                    gram_opts = ["（不限）"] + sorted([v for v in df_t1_scope["文法"].unique() if v and v != ""])
                    t1_gram = extra_cols[0].selectbox("文法（選填）", gram_opts, key="t1_grammar")
                    if t1_gram != "（不限）":
                        df_t1_scope = df_t1_scope[df_t1_scope["文法"] == t1_gram]
                if "難度" in df_t1_scope.columns:
                    diff_opts = ["（不限）"] + sorted([v for v in df_t1_scope["難度"].unique() if v and v != ""])
                    t1_diff = extra_cols[1].selectbox("難度（選填）", diff_opts, key="t1_diff")
                    if t1_diff != "（不限）":
                        df_t1_scope = df_t1_scope[df_t1_scope["難度"] == t1_diff]

                df_t1_scope["題目ID"] = df_t1_scope.apply(
                    lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1
                )
                total_in_scope = len(df_t1_scope)

                sc1, sc2 = st.columns(2)
                all_sent_nums = sorted(df_t1_scope["句編號"].unique(), key=lambda x: int(x) if str(x).isdigit() else 0)
                t1_start_sent = sc1.selectbox("🔢 起始句編號", all_sent_nums, key="t1_start_sent") if all_sent_nums else None
                t1_q_count    = sc2.number_input("🔢 題目數量", min_value=0, max_value=total_in_scope, value=total_in_scope, key="t1_q_count")

                if t1_start_sent:
                    df_t1_scope["_num"] = pd.to_numeric(df_t1_scope["句編號"], errors="coerce").fillna(0)
                    df_t1_scope = df_t1_scope[df_t1_scope["_num"] >= int(t1_start_sent)].sort_values("_num").copy()
                if t1_q_count > 0:
                    df_t1_scope = df_t1_scope.head(int(t1_q_count)).copy()
                st.caption(f"📚 範圍 {total_in_scope} 題 → 篩選後 {len(df_t1_scope)} 題")

                df_t1_final = df_t1_scope.copy()
                with st.expander(f"📋 預覽重組題清單（{len(df_t1_final)} 題）", expanded=False):
                    prev = [c for c in ["句編號", "重組中文題目", "題目ID"] if c in df_t1_final.columns]
                    st.dataframe(df_t1_final[prev], use_container_width=True)
        else:
            t1v = t1u = t1y = t1b = t1l = ""

        st.divider()

        # ── 單選題範圍（選填） ────────────────────────────────────────────
        include_mcq = st.checkbox("🔵 加入單選題", value=False, key="t1_inc_mcq")
        df_mcq_final = pd.DataFrame()

        if include_mcq:
            if df_mcq.empty:
                st.warning("單選工作表尚無資料。")
            else:
                st.markdown("**⚙️ 單選題範圍**")
                mc = st.columns(5)
                mv = mc[0].selectbox("版本",  sorted(df_mcq["版本"].unique()), key="mc_v")
                mu_src = df_mcq[df_mcq["版本"] == mv]
                mu = mc[1].selectbox("單元",  sorted(mu_src["單元"].unique()), key="mc_u")
                my_src = mu_src[mu_src["單元"] == mu]
                my = mc[2].selectbox("年度",  sorted(my_src["年度"].unique()), key="mc_y")
                mb_src = my_src[my_src["年度"] == my]
                mb = mc[3].selectbox("冊編號", sorted(mb_src["冊編號"].unique()), key="mc_b")
                ml_src = mb_src[mb_src["冊編號"] == mb]
                ml = mc[4].selectbox("課編號", sorted(ml_src["課編號"].unique()), key="mc_l")

                df_mcq_scope = ml_src[ml_src["課編號"] == ml].copy()
                mc_total_before = len(df_mcq_scope)  # 文法/難度篩選前的總題數

                mc_extra = st.columns(2)
                if "文法" in df_mcq_scope.columns:
                    mc_gram_opts = ["（不限）"] + sorted([v for v in df_mcq_scope["文法"].unique() if v and v != ""])
                    mc_gram = mc_extra[0].selectbox("文法（選填）", mc_gram_opts, key="mc_grammar")
                    if mc_gram != "（不限）":
                        df_mcq_scope = df_mcq_scope[df_mcq_scope["文法"] == mc_gram]
                if "難度" in df_mcq_scope.columns:
                    mc_diff_opts = ["（不限）"] + sorted([v for v in df_mcq_scope["難度"].unique() if v and v != ""])
                    mc_diff = mc_extra[1].selectbox("難度（選填）", mc_diff_opts, key="mc_diff")
                    if mc_diff != "（不限）":
                        df_mcq_scope = df_mcq_scope[df_mcq_scope["難度"] == mc_diff]

                df_mcq_scope["題目ID"] = df_mcq_scope.apply(
                    lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1
                )
                mc_total = len(df_mcq_scope)
                mcs1, mcs2 = st.columns(2)
                mc_sent_opts = sorted(df_mcq_scope["句編號"].unique(), key=lambda x: int(x) if str(x).isdigit() else 0)
                mc_start = mcs1.selectbox("🔢 起始句編號", mc_sent_opts, key="mc_start_sent") if mc_sent_opts else None
                mc_count = mcs2.number_input("🔢 題目數量", 0, max(mc_total,1), mc_total, key="mc_q_count")

                if mc_start:
                    df_mcq_scope["_num"] = pd.to_numeric(df_mcq_scope["句編號"], errors="coerce").fillna(0)
                    df_mcq_scope = df_mcq_scope[df_mcq_scope["_num"] >= int(mc_start)].sort_values("_num").copy()
                if mc_count > 0:
                    df_mcq_scope = df_mcq_scope.head(int(mc_count)).copy()

                df_mcq_final = df_mcq_scope.copy()
                st.caption(f"📚 範圍 {mc_total_before} 題 → 篩選後 {len(df_mcq_final)} 題")
                with st.expander(f"📋 預覽單選題清單（{len(df_mcq_final)} 題）", expanded=False):
                    prev = [c for c in ["句編號", "單選題目", "題目ID"] if c in df_mcq_final.columns]
                    st.dataframe(df_mcq_final[prev], use_container_width=True)

        st.divider()

        # ── 參考學生錯題篩選（重組＋單選共用） ───────────────────────────
        ref_students = []
        if not df_t1_final.empty or not df_mcq_final.empty:
            st.markdown("**👥 參考學生錯題（選填）**")
            ref_col1, ref_col2, ref_col3 = st.columns(3)
            all_students  = sorted(df_s[~df_s["分組"].isin(["ADMIN","TEACHER"])]["姓名"].tolist())
            ref_students  = ref_col1.multiselect("參考學生（可複選）", all_students, key="t1_ref_stu")
            ref_logic     = ref_col2.selectbox("篩選邏輯", ["OR：任一人答錯過", "AND：所有人都答錯過"], key="t1_ref_logic")
            ref_min_err   = ref_col3.number_input("合計答錯次數 ≥", min_value=1, max_value=20, value=1, key="t1_ref_n")

        st.divider()


        # ── 朗讀題目範圍（選填） ──────────────────────────────────────────
        include_reading = st.checkbox("🎤 加入朗讀題", key="t1_inc_reading")
        df_r_final = pd.DataFrame()

        if include_reading:
            if df_r.empty:
                st.warning("reading 工作表尚無資料，無法加入朗讀題。")
            else:
                df_r2 = df_r.copy()
                if '題目ID' not in df_r2.columns:
                    df_r2['題目ID'] = df_r2.apply(
                        lambda r: f"R_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                    )
                if '單元' not in df_r2.columns:
                    df_r2['單元'] = '朗讀'

                st.markdown("**⚙️ 朗讀題範圍**")
                rc_ = st.columns(5)
                rv_ = rc_[0].selectbox("版本",  sorted(df_r2['版本'].unique()),  key="rt_v")
                ru_src = df_r2[df_r2['版本'] == rv_]
                ru_ = rc_[1].selectbox("單元",  sorted(ru_src['單元'].unique()),  key="rt_u")
                ry_src = ru_src[ru_src['單元'] == ru_]
                ry_ = rc_[2].selectbox("年度",  sorted(ry_src['年度'].unique()),  key="rt_y")
                rb_src = ry_src[ry_src['年度'] == ry_]
                rb_ = rc_[3].selectbox("冊編號", sorted(rb_src['冊編號'].unique()), key="rt_b")
                rl_src = rb_src[rb_src['冊編號'] == rb_]
                rl_ = rc_[4].selectbox("課編號", sorted(rl_src['課編號'].unique()), key="rt_l")

                df_r_final = rl_src[rl_src['課編號'] == rl_].copy()

                # 文法／難度篩選（選填）
                r_extra = st.columns(2)
                if '文法' in df_r_final.columns:
                    r_gram_opts = ["（不限）"] + sorted([v for v in df_r_final['文法'].unique() if v and v != ''])
                    r_gram = r_extra[0].selectbox("文法（選填）", r_gram_opts, key="rt_grammar")
                    if r_gram != "（不限）":
                        df_r_final = df_r_final[df_r_final['文法'] == r_gram]
                if '難度' in df_r_final.columns:
                    r_diff_opts = ["（不限）"] + sorted([v for v in df_r_final['難度'].unique() if v and v != ''])
                    r_diff = r_extra[1].selectbox("難度（選填）", r_diff_opts, key="rt_diff")
                    if r_diff != "（不限）":
                        df_r_final = df_r_final[df_r_final['難度'] == r_diff]

                r_total = len(df_r_final)
                # 朗讀總題數已下移合併

                # 起始句編號 & 題目數量
                rs1, rs2 = st.columns(2)
                r_sent_opts = sorted(df_r_final['句編號'].unique(), key=lambda x: int(x) if str(x).isdigit() else 0) if '句編號' in df_r_final.columns else []
                r_start_sent = rs1.selectbox("🔢 起始句編號", r_sent_opts, key="rt_start_sent") if r_sent_opts else None
                r_q_count    = rs2.number_input("🔢 題目數量", min_value=0, max_value=max(r_total, 1), value=r_total, key="rt_q_count")

                # 套用起始句與數量
                if r_start_sent and '句編號' in df_r_final.columns:
                    df_r_final['_num'] = pd.to_numeric(df_r_final['句編號'], errors='coerce').fillna(0)
                    df_r_final = df_r_final[df_r_final['_num'] >= int(r_start_sent)].sort_values('_num').copy()
                if r_q_count > 0:
                    df_r_final = df_r_final.head(int(r_q_count)).copy()
                st.caption(f"📚 範圍 {r_total} 題 → 篩選後 {len(df_r_final)} 題")

                preview_r_cols = [c for c in ['句編號', '朗讀句子', '英文句子', '題目ID'] if c in df_r_final.columns]
                with st.expander(f"📋 預覽朗讀清單（{len(df_r_final)} 題）", expanded=False):
                    st.dataframe(df_r_final[preview_r_cols], use_container_width=True)

        st.divider()

        # ── 單字重組範圍（選填） ──────────────────────────────────────────
        include_vocab = st.checkbox("🔤 加入單字重組題", key="t1_inc_vocab")
        df_v_final = pd.DataFrame()

        if include_vocab:
            if df_v.empty:
                st.warning("vocab 工作表尚無資料，無法加入單字題。")
            else:
                df_v2 = df_v.copy()
                if '題目ID' not in df_v2.columns:
                    df_v2['題目ID'] = df_v2.apply(
                        lambda r: f"V_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                    )

                st.markdown("**⚙️ 單字題範圍**")
                vc_ = st.columns(5)
                vv_ = vc_[0].selectbox("版本",  sorted(df_v2['版本'].unique()), key="vt_v")
                vu_src = df_v2[df_v2['版本'] == vv_]
                vu_ = vc_[1].selectbox("單元",  sorted(vu_src['單元'].unique()) if '單元' in vu_src.columns else ['單字'], key="vt_u")
                vy_src = vu_src[vu_src['單元'] == vu_] if '單元' in vu_src.columns else vu_src
                vy_ = vc_[2].selectbox("年度",  sorted(vy_src['年度'].unique()), key="vt_y")
                vb_src = vy_src[vy_src['年度'] == vy_]
                vb_ = vc_[3].selectbox("冊編號", sorted(vb_src['冊編號'].unique()), key="vt_b")
                vl_src = vb_src[vb_src['冊編號'] == vb_]
                vl_ = vc_[4].selectbox("課編號", sorted(vl_src['課編號'].unique()), key="vt_l")

                df_v_scope_t1 = vl_src[vl_src['課編號'] == vl_].copy()

                # 文法／難度篩選（選填）
                v_extra = st.columns(2)
                if '文法' in df_v_scope_t1.columns:
                    v_gram_opts = ["（不限）"] + sorted([v for v in df_v_scope_t1['文法'].unique() if v and v != ''])
                    v_gram = v_extra[0].selectbox("文法（選填）", v_gram_opts, key="vt_grammar")
                    if v_gram != "（不限）":
                        df_v_scope_t1 = df_v_scope_t1[df_v_scope_t1['文法'] == v_gram]
                if '難度' in df_v_scope_t1.columns:
                    v_diff_opts = ["（不限）"] + sorted([v for v in df_v_scope_t1['難度'].unique() if v and v != ''])
                    v_diff = v_extra[1].selectbox("難度（選填）", v_diff_opts, key="vt_diff")
                    if v_diff != "（不限）":
                        df_v_scope_t1 = df_v_scope_t1[df_v_scope_t1['難度'] == v_diff]

                v_total = len(df_v_scope_t1)
                # 拼單字總題數已下移合併

                vs1, vs2 = st.columns(2)
                v_sent_opts = sorted(df_v_scope_t1['句編號'].unique(), key=lambda x: int(x) if str(x).isdigit() else 0) if '句編號' in df_v_scope_t1.columns else []
                vt_start = vs1.selectbox("🔢 起始句編號", v_sent_opts, key="vt_start_sent") if v_sent_opts else None
                vt_count = vs2.number_input("🔢 題目數量", 0, max(v_total, 1), v_total, key="vt_q_count")

                if vt_start and '句編號' in df_v_scope_t1.columns:
                    df_v_scope_t1['_num'] = pd.to_numeric(df_v_scope_t1['句編號'], errors='coerce').fillna(0)
                    df_v_scope_t1 = df_v_scope_t1[df_v_scope_t1['_num'] >= int(vt_start)].sort_values('_num').copy()
                if vt_count > 0:
                    df_v_scope_t1 = df_v_scope_t1.head(int(vt_count)).copy()

                # 難度設定
                vm1, vm2, vm3 = st.columns(3)
                vt_mode  = vm1.selectbox("模式鎖定", ["學生自選", "拆字母", "鍵盤"], key="vt_mode")
                vt_timer = vm2.number_input("限時（秒，0=不限）", 0, 300, 60, key="vt_timer")
                vt_extra = vm3.number_input("干擾字母數", 0, 10, 0, key="vt_extra")

                st.caption(f"📚 範圍 {v_total} 題 → 篩選後 {len(df_v_scope_t1)} 題")
                df_v_final = df_v_scope_t1.copy()

                preview_v_cols = [c for c in ['句編號', '中文意思', '英文單字', '題目ID'] if c in df_v_final.columns]
                with st.expander(f"📋 預覽單字清單（{len(df_v_final)} 題）", expanded=False):
                    st.dataframe(df_v_final[preview_v_cols], use_container_width=True)

        st.divider()

        # ── 閱讀單句範圍（選填） ──────────────────────────────────────────
        include_rm = st.checkbox("📖 加入閱讀單句題", key="t1_inc_rm")
        if include_rm and not df_rm.empty:
            # 閱讀單句篩選（已有）
            pass

        # ── 聽力句子重組 ───────────────────────────────────────────────────────
        include_ls = st.checkbox("🎧 加入聽力句子重組題", key="t1_inc_ls")
        df_ls_final = pd.DataFrame()
        if include_ls and not df_ls.empty:
            st.markdown("**🎧 聽力句子重組出題範圍**")
            lsc_ = st.columns(5)
            lsv_opts = [""] + sorted(df_ls['版本'].unique().tolist())
            lsv_ = lsc_[0].selectbox("版本", lsv_opts, key="lst_v")
            ls_src = df_ls[df_ls['版本'] == lsv_] if lsv_ else df_ls
            lsu_opts = [""] + sorted(ls_src['單元'].unique().tolist()) if '單元' in ls_src.columns else [""]
            lsu_ = lsc_[1].selectbox("單元", lsu_opts, key="lst_u")
            ls_src2 = ls_src[ls_src['單元'] == lsu_] if lsu_ and '單元' in ls_src.columns else ls_src
            lsy_opts = [""] + sorted(ls_src2['年度'].unique().tolist())
            lsy_ = lsc_[2].selectbox("年度", lsy_opts, key="lst_y")
            ls_src3 = ls_src2[ls_src2['年度'] == lsy_] if lsy_ else ls_src2
            lsb_opts = [""] + sorted(ls_src3['冊編號'].unique().tolist())
            lsb_ = lsc_[3].selectbox("冊編號", lsb_opts, key="lst_b")
            ls_src4 = ls_src3[ls_src3['冊編號'] == lsb_] if lsb_ else ls_src3
            lsl_opts = [""] + sorted(ls_src4['課編號'].unique().tolist())
            lsl_ = lsc_[4].selectbox("課編號", lsl_opts, key="lst_l")
            ls_src5 = ls_src4[ls_src4['課編號'] == lsl_] if lsl_ else ls_src4
            ls_total = len(ls_src5)
            df_ls_final = ls_src5.sample(frac=1).reset_index(drop=True)
            st.caption(f"📚 範圍 {ls_total} 題 → 篩選後 {len(df_ls_final)} 題")
        include_lp = st.checkbox("🎧 加入聽力音標題", key="t1_inc_lp")
        df_lp_final = pd.DataFrame()  # 預設空值
        if include_lp and not df_lp.empty:

            st.markdown("**🎧 聽力音標出題範圍**")
            lpc_ = st.columns(4)
            lpv_opts = [""] + sorted(df_lp['版本'].unique().tolist())
            lpv_ = lpc_[0].selectbox("版本", lpv_opts, key="lpt_v")
            lp_src = df_lp[df_lp['版本'] == lpv_] if lpv_ else df_lp
            lpu_opts = [""] + sorted(lp_src['單元'].unique().tolist())
            lpu_ = lpc_[1].selectbox("單元", lpu_opts, key="lpt_u")
            lp_src2 = lp_src[lp_src['單元'] == lpu_] if lpu_ else lp_src
            lpg_opts = [""] + sorted(lp_src2['組編號'].unique().tolist())
            lpg_ = lpc_[2].selectbox("組編號", lpg_opts, key="lpt_g")
            lp_src3 = lp_src2[lp_src2['組編號'] == lpg_] if lpg_ else lp_src2
            lp_total = len(lp_src3)
            lp_count = lpc_[3].number_input("題數", min_value=0, max_value=max(lp_total, 1), value=lp_total, key="lpt_count")
            df_lp_final = lp_src3.head(int(lp_count)).copy() if lp_count > 0 else lp_src3.copy()
            df_lp_final = df_lp_final.sample(frac=1).reset_index(drop=True)  # 隨機排列（無固定種子）
            st.caption(f"📚 範圍 {lp_total} 題 → 篩選後 {len(df_lp_final)} 題")
        else:
            df_lp_final = pd.DataFrame()
        df_rm_final = pd.DataFrame()

        if include_rm:
            if df_rm.empty:
                st.warning("閱讀單句工作表尚無資料，無法加入閱讀單句題。")
            else:
                df_rm2 = df_rm.copy()
                if '題目ID' not in df_rm2.columns:
                    df_rm2['題目ID'] = df_rm2.apply(
                        lambda r: f"RM_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                    )

                st.markdown("**⚙️ 閱讀單句範圍**")
                rmc_ = st.columns(5)
                rmv_ = rmc_[0].selectbox("版本",  sorted(df_rm2['版本'].unique()), key="rmt_v")
                rmu_src = df_rm2[df_rm2['版本'] == rmv_]
                rmu_ = rmc_[1].selectbox("單元",  sorted(rmu_src['單元'].unique()) if '單元' in rmu_src.columns else ['閱讀'], key="rmt_u")
                rmy_src = rmu_src[rmu_src['單元'] == rmu_] if '單元' in rmu_src.columns else rmu_src
                rmy_ = rmc_[2].selectbox("年度",  sorted(rmy_src['年度'].unique()), key="rmt_y")
                rmb_src = rmy_src[rmy_src['年度'] == rmy_]
                rmb_ = rmc_[3].selectbox("冊編號", sorted(rmb_src['冊編號'].unique()), key="rmt_b")
                rml_src = rmb_src[rmb_src['冊編號'] == rmb_]
                rml_ = rmc_[4].selectbox("課編號", sorted(rml_src['課編號'].unique()), key="rmt_l")

                df_rm_scope = rml_src[rml_src['課編號'] == rml_].copy()

                # 文法／難度篩選
                rm_extra = st.columns(2)
                if '文法' in df_rm_scope.columns:
                    rm_gram_opts = ["（不限）"] + sorted([v for v in df_rm_scope['文法'].unique() if v and v != ''])
                    rm_gram = rm_extra[0].selectbox("文法（選填）", rm_gram_opts, key="rmt_grammar")
                    if rm_gram != "（不限）":
                        df_rm_scope = df_rm_scope[df_rm_scope['文法'] == rm_gram]
                if '難度' in df_rm_scope.columns:
                    rm_diff_opts = ["（不限）"] + sorted([v for v in df_rm_scope['難度'].unique() if v and v != ''])
                    rm_diff = rm_extra[1].selectbox("難度（選填）", rm_diff_opts, key="rmt_diff")
                    if rm_diff != "（不限）":
                        df_rm_scope = df_rm_scope[df_rm_scope['難度'] == rm_diff]

                rm_total = len(df_rm_scope)
                rms1, rms2 = st.columns(2)
                rm_sent_opts = sorted(df_rm_scope['句編號'].unique(), key=lambda x: int(x) if str(x).isdigit() else 0) if '句編號' in df_rm_scope.columns else []
                rm_start = rms1.selectbox("🔢 起始句編號", rm_sent_opts, key="rmt_start") if rm_sent_opts else None
                rm_count = rms2.number_input("🔢 題目數量", 0, max(rm_total,1), rm_total, key="rmt_count")

                if rm_start and '句編號' in df_rm_scope.columns:
                    df_rm_scope['_num'] = pd.to_numeric(df_rm_scope['句編號'], errors='coerce').fillna(0)
                    df_rm_scope = df_rm_scope[df_rm_scope['_num'] >= int(rm_start)].sort_values('_num').copy()
                if rm_count > 0:
                    df_rm_scope = df_rm_scope.head(int(rm_count)).copy()

                df_rm_final = df_rm_scope.copy()
                st.caption(f"📚 範圍 {rm_total} 題 → 篩選後 {len(df_rm_final)} 題")

                preview_rm_cols = [c for c in ['句編號', '題目', '選項A', '選項B', '選項C', '選項D', '正確選項列出'] if c in df_rm_final.columns]
                with st.expander(f"📋 預覽閱讀單句清單（{len(df_rm_final)} 題）", expanded=False):
                    st.dataframe(df_rm_final[preview_rm_cols], use_container_width=True)

        st.divider()

        # 合計摘要表（按計算鍵後才更新）
        st.divider()
        _calc_col1, _calc_col2 = st.columns([3, 1])
        _calc_col1.markdown("**📊 確認題數後再發布**")
        _do_calc = _calc_col2.button("🔢 計算題數", use_container_width=True, key="t1_calc")

        if _do_calc:
            st.session_state['_t1_summary'] = {
                '重組': len(df_t1_final),
                '單選': len(df_mcq_final),
                '朗讀': len(df_r_final),
                '拼單字': len(df_v_final),
                '閱讀': len(df_rm_final),
                '聽力音標': len(df_lp_final),
                '聽力重組': len(df_ls_final),
            }

        _summary = st.session_state.get('_t1_summary')
        if _summary:
            _summary_cols = st.columns(7)
            _icons = ["✏️ 重組","🔵 單選","🎤 朗讀","🔤 拼單字","📖 閱讀","🎧 聽力音標","🎧 聽力重組"]
            _keys  = ["重組","單選","朗讀","拼單字","閱讀","聽力音標","聽力重組"]
            for _ci, (_lbl, _k) in enumerate(zip(_icons, _keys)):
                _summary_cols[_ci].metric(_lbl, f"{_summary.get(_k, 0)} 題")
            total_q = sum(_summary.values())
            st.info(f"📊 本次任務合計：**{total_q} 題**　（重組 {_summary.get('重組',0)} ＋ 單選 {_summary.get('單選',0)} ＋ 朗讀 {_summary.get('朗讀',0)} ＋ 拼單字 {_summary.get('拼單字',0)} ＋ 閱讀單句 {_summary.get('閱讀',0)} ＋ 聽力音標 {_summary.get('聽力音標',0)} ＋ 聽力重組 {_summary.get('聽力重組',0)}）")
        else:
            st.caption("← 點「計算題數」確認出題範圍")

        if st.button("🚀 確認發布任務", use_container_width=True, type="primary"):
            # 清除舊的成功訊息
            st.session_state.pop('_publish_success', None)
            if not target_groups:
                st.error("❌ 請至少選擇一個目標班級")
            elif not include_q and not include_mcq and not include_reading and not include_vocab and not include_rm and not include_lp and not include_ls:
                st.error("❌ 請至少勾選一種題型")
            elif df_t1_final.empty and df_mcq_final.empty and df_r_final.empty and df_v_final.empty and df_rm_final.empty and df_lp_final.empty and df_ls_final.empty:
                st.error("❌ 目前無符合條件的題目，請調整篩選條件")
            elif not target_students_t1:
                st.error("❌ 請至少選擇一位學生")
            elif date_end < date_start:
                st.error("❌ 結束日期不能早於開始日期")
            else:
                q_ids   = df_t1_final['題目ID'].tolist()  if (not df_t1_final.empty  and '題目ID' in df_t1_final.columns)  else []
                mcq_ids = df_mcq_final['題目ID'].tolist() if (not df_mcq_final.empty and '題目ID' in df_mcq_final.columns) else []
                r_ids   = df_r_final['題目ID'].tolist()   if (not df_r_final.empty   and '題目ID' in df_r_final.columns)   else []
                v_ids   = df_v_final['題目ID'].tolist()   if (not df_v_final.empty   and '題目ID' in df_v_final.columns)   else []
                rm_ids  = df_rm_final['題目ID'].tolist()  if (not df_rm_final.empty  and '題目ID' in df_rm_final.columns)  else []
                lp_ids  = [_get_lp_qid(r) for _, r in df_lp_final.iterrows()] if not df_lp_final.empty else []
                ls_ids  = [_get_ls_qid(r) for _, r in df_ls_final.iterrows()] if not df_ls_final.empty else []
                all_ids = q_ids + mcq_ids + r_ids + v_ids + rm_ids + lp_ids + ls_ids

                has_q   = bool(q_ids)
                has_mcq = bool(mcq_ids)
                has_r   = bool(r_ids)
                has_v   = bool(v_ids)
                has_rm  = bool(rm_ids)
                has_lp  = bool(lp_ids)
                has_ls  = bool(ls_ids)
                if has_ls and not has_q and not has_mcq and not has_r and not has_v and not has_rm and not has_lp:
                    task_type = "聽力重組"
                elif has_lp and not has_q and not has_mcq and not has_r and not has_v and not has_rm and not has_ls:
                    task_type = "聽力音標"
                elif has_rm and not has_q and not has_mcq and not has_r and not has_v and not has_lp:
                    task_type = "閱讀單句"
                elif has_r and not has_q and not has_mcq and not has_v and not has_rm and not has_lp:
                    task_type = "朗讀"
                elif has_v and not has_q and not has_mcq and not has_r and not has_rm and not has_lp:
                    task_type = "單字"
                elif has_mcq and not has_q and not has_r and not has_v and not has_rm and not has_lp:
                    task_type = "單選"
                elif has_q and not has_mcq and not has_r and not has_v and not has_rm and not has_lp:
                    task_type = "一般"
                else:
                    task_type = "混合"

                # vocab 難度設定存入任務
                vocab_cfg = ""
                if has_v:
                    vt_mode_val  = st.session_state.get('vt_mode', '學生自選')
                    vt_timer_val = st.session_state.get('vt_timer', 60)
                    vt_extra_val = st.session_state.get('vt_extra', 0)
                    vocab_cfg = f"{vt_mode_val}|{vt_timer_val}|{vt_extra_val}"

                # 自動產生任務名稱（新格式）
                publish_time = get_now().strftime("%Y-%m-%d_%H:%M")
                teacher_name = st.session_state.user_name
                groups_label = ",".join(target_groups)

                # 取得主要題型的篩選資訊（只顯示一次題型）
                def _make_task_name(ttype, v, u, y, b, l, start, count, groups, teacher, ptime, dstart, dend):
                    # 格式：題型-單元-版本-年度-冊-課-起始題-題數-班級-出題老師-出題戳記-開始日~結束日
                    u_part    = f"-{u}" if u and str(u).strip() else ""
                    start_str = f"-起始{start}" if start else ""
                    return f"{ttype}{u_part}-{v}-{y}年-冊{b}-課{l}{start_str}-{count}題-{groups}-{teacher}-{ptime}-{dstart}~{dend}"

                if mcq_ids:
                    mv_ = st.session_state.get('mc_v', '')
                    mu_ = st.session_state.get('mc_u', '')
                    my_ = st.session_state.get('mc_y', '')
                    mb_ = st.session_state.get('mc_b', '')
                    ml_ = st.session_state.get('mc_l', '')
                    ms_ = st.session_state.get('mc_start_sent', '')
                    auto_desc = _make_task_name("單選", mv_, mu_, my_, mb_, ml_, ms_, len(mcq_ids), groups_label, teacher_name, publish_time, str(date_start), str(date_end))
                elif q_ids:
                    auto_desc = _make_task_name("重組", t1v, t1u, t1y, t1b, t1l, st.session_state.get('t1_start_sent',''), len(q_ids), groups_label, teacher_name, publish_time, str(date_start), str(date_end))
                elif r_ids:
                    rv_ = st.session_state.get('rt_v', '')
                    ru_ = st.session_state.get('rt_u', '')
                    ry_ = st.session_state.get('rt_y', '')
                    rb_ = st.session_state.get('rt_b', '')
                    rl_ = st.session_state.get('rt_l', '')
                    rs_ = st.session_state.get('rt_start_sent', '')
                    auto_desc = _make_task_name("朗讀", rv_, ru_, ry_, rb_, rl_, rs_, len(r_ids), groups_label, teacher_name, publish_time, str(date_start), str(date_end))
                elif v_ids:
                    vv_ = st.session_state.get('vt_v', '')
                    vu_ = st.session_state.get('vt_u', '')
                    vy_ = st.session_state.get('vt_y', '')
                    vb_ = st.session_state.get('vt_b', '')
                    vl_ = st.session_state.get('vt_l', '')
                    vs_ = st.session_state.get('vt_start_sent', '')
                    auto_desc = _make_task_name("拼單字", vv_, vu_, vy_, vb_, vl_, vs_, len(v_ids), groups_label, teacher_name, publish_time, str(date_start), str(date_end))
                elif rm_ids:
                    rmv_ = st.session_state.get('rmt_v', '')
                    rmu_ = st.session_state.get('rmt_u', '')
                    rmy_ = st.session_state.get('rmt_y', '')
                    rmb_ = st.session_state.get('rmt_b', '')
                    rml_ = st.session_state.get('rmt_l', '')
                    rms_ = st.session_state.get('rmt_start', '')
                    auto_desc = _make_task_name("閱讀單句", rmv_, rmu_, rmy_, rmb_, rml_, rms_, len(rm_ids), groups_label, teacher_name, publish_time, str(date_start), str(date_end))
                elif lp_ids:
                    lpv_ = st.session_state.get('lpt_v', '')
                    lpu_ = st.session_state.get('lpt_u', '')
                    auto_desc = _make_task_name("聽力音標", lpv_, lpu_, '', '', '', '', len(lp_ids), groups_label, teacher_name, publish_time, str(date_start), str(date_end))
                elif ls_ids:
                    lsv_ = st.session_state.get('lst_v', '')
                    lsu_ = st.session_state.get('lst_u', '')
                    lsy_ = st.session_state.get('lst_y', '')
                    lsb_ = st.session_state.get('lst_b', '')
                    lsl_ = st.session_state.get('lst_l', '')
                    auto_desc = _make_task_name("聽力重組", lsv_, lsu_, lsy_, lsb_, lsl_, '', len(ls_ids), groups_label, teacher_name, publish_time, str(date_start), str(date_end))
                else:
                    auto_desc = f"混合任務-{groups_label}-{teacher_name}-{publish_time}-{date_start}~{date_end}"

                # 產生唯一編號：T + 6碼台灣日期 + 3碼流水號（從001計）
                _today_str = get_now().strftime("%y%m%d")  # 台灣時間 yymmdd
                # 查詢今日已有幾個任務（從 df_a 計算）
                import re as _re_tid
                _today_prefix = f"T{_today_str}"
                _existing = [str(r.get('任務編號','') or '') for _, r in df_a.iterrows() if not df_a.empty] if not df_a.empty else []
                _today_cnt = sum(1 for _e in _existing if _e.startswith(_today_prefix))
                task_id = f"T{_today_str}{_today_cnt+1:03d}"
                # 任務名稱前面加編號
                auto_desc = f"[{task_id}] {auto_desc}"

                new_task  = pd.DataFrame([{
                    "建立時間":   get_now().strftime("%Y-%m-%d %H:%M:%S"),
                    "任務名稱":   auto_desc,
                    "任務編號":   task_id,
                    "對象班級":   target_group,
                    "指派學生":   ",".join(target_students_t1),
                    "指派人數":   len(target_students_t1),
                    "內容":       f"{t1v}|{t1u}|{t1y}|{t1b}|{t1l}",
                    "任務說明":   "",
                    "單字設定":   vocab_cfg,
                    "題目數":     len(all_ids),
                    "題目ID清單": ",".join(all_ids),
                    "開始日期":   str(date_start),
                    "結束日期":   str(date_end),
                    "參考學生":   ",".join(ref_students) if ref_students else "",
                    "狀態":       "進行中",
                    "類型":       task_type
                }])
                if append_to_sheet("assignments", new_task):
                    st.success(f"🎉 任務發布成功！共 {len(all_ids)} 題，已指派給 {len(target_students_t1)} 位學生。請至任務列表確認。")
                    st.balloons()
                    st.session_state['_a2_cache_stale'] = True
                    st.session_state['_publish_success'] = f"🎉 任務發布成功！\n任務序號：**{task_id}**\n任務名稱：**{auto_desc}**\n共 {len(all_ids)} 題，已指派給 {len(target_students_t1)} 位學生。"
                    # 立即清空所有篩選 key
                    _clear_keys = [
                        't1_inc_q', 't1_inc_mcq', 't1_inc_reading', 't1_inc_vocab', 't1_inc_rm', 't1_inc_lp',
                        't1_v', 't1_u', 't1_y', 't1_b', 't1_l', 't1_start_sent', 't1_q_count', 't1_grammar', 't1_diff',
                        'mc_v', 'mc_u', 'mc_y', 'mc_b', 'mc_l', 'mc_start_sent', 'mc_q_count', 'mc_grammar', 'mc_diff',
                        'rt_v', 'rt_u', 'rt_y', 'rt_b', 'rt_l', 'rt_start_sent', 'rt_q_count',
                        'vt_v', 'vt_u', 'vt_y', 'vt_b', 'vt_l', 'vt_start_sent', 'vt_q_count', 'vt_mode', 'vt_timer', 'vt_extra',
                        'rmt_v', 'rmt_u', 'rmt_y', 'rmt_b', 'rmt_l', 'rmt_start', 'rmt_count', 'rmt_grammar', 'rmt_diff',
                        'lpt_v', 'lpt_u', 'lpt_g', 'lpt_count',
                        'lst_v', 'lst_u', 'lst_y', 'lst_b', 'lst_l', 't1_inc_ls',
                        't1_group', 't1_mode', 't1_stu', 't1_start', 't1_end',
                        't1_ref_stu', 't1_ref_logic', 't1_ref_n', '_t1_summary',
                    ]
                    for _k in _clear_keys:
                        st.session_state.pop(_k, None)
                    st.rerun()

        # 顯示發布成功訊息（rerun 後仍然保留）
        if st.session_state.get('_publish_success'):
            st.success(st.session_state['_publish_success'])

        # ══════════════════════════════════════════════════════════════════
        # 區塊二：集合多任務→指派新任務
        # ══════════════════════════════════════════════════════════════════
        st.divider()
        st.subheader("🔗 集合多任務→指派新任務")
        st.caption("從多個任務中篩選題目（聯集），集中讓學生練習錯題或未作答題目")

        df_a_active = df_a[df_a.get('狀態', pd.Series(dtype=str)).fillna('') != '已刪除'].copy() if not df_a.empty else pd.DataFrame()

        if df_a_active.empty:
            st.info("目前尚無任務可選。")
        else:
            task_names_all = _sort_task_names(df_a_active['任務名稱'].tolist()) if '任務名稱' in df_a_active.columns else []

            # ── 步驟1：選擇來源任務 ──────────────────────────────────────
            st.markdown("**① 選擇來源任務（可複選）**")
            sel_src_tasks = st.multiselect(
                "來源任務", task_names_all, default=[], key="combine_src_tasks",
                label_visibility="collapsed"
            )

            if sel_src_tasks:
                # ── 步驟2：篩選條件 ──────────────────────────────────────
                st.markdown("**② 題目篩選條件**")
                c2a, c2b = st.columns(2)
                combine_scope = c2a.radio(
                    "篩選範圍",
                    ["📚 所有題目（聯集）", "❌ 只取曾錯題", "❓ 只取未作答"],
                    key="combine_scope", horizontal=False
                )
                combine_ref_group_opts = ["不限"] + [_group_label(g) for g in sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique())]
                combine_ref_group_map  = {"不限": None, **{_group_label(g): g for g in sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique())}}
                combine_ref_lbl  = c2b.selectbox("參考學生來自班級", combine_ref_group_opts, key="combine_ref_group")
                combine_ref_grp  = combine_ref_group_map.get(combine_ref_lbl)
                if combine_ref_grp:
                    ref_pool = sorted(df_s[df_s['分組'] == combine_ref_grp]['姓名'].tolist())
                else:
                    ref_pool = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['姓名'].tolist())
                combine_ref_stus = st.multiselect("參考哪些學生的作答（預設全選）", ref_pool, key="combine_ref_stus")
                ref_stus = combine_ref_stus if combine_ref_stus else ref_pool

                # ── 收集所有來源任務的題目ID ──────────────────────────────
                all_src_qids = set()
                for tn in sel_src_tasks:
                    row_t = df_a_active[df_a_active['任務名稱'] == tn]
                    if not row_t.empty:
                        ids_str = str(row_t.iloc[0].get('題目ID清單', '') or '')
                        for qid in ids_str.split(','):
                            qid = qid.strip()
                            if qid and qid != 'nan':
                                # 統一格式（去V_前綴）
                                all_src_qids.add(qid[2:] if qid.startswith('V_') else qid)

                # ── 依條件篩選 ────────────────────────────────────────────
                if combine_scope != "📚 所有題目（聯集）" and ref_stus:
                    try:
                        # 用快取的 df_l
                        if not df_l.empty:
                            if df_l.empty: df_l = _get_df_l()
                            df_c_logs = df_l[df_l['姓名'].isin(ref_stus)].copy()
                            df_c_logs['question_id'] = df_c_logs['題目ID'].apply(
                                lambda x: x[2:] if str(x).startswith('V_') else x
                            )
                            answered = set(df_c_logs[~df_c_logs['結果'].str.contains('📖', na=False)]['question_id'].tolist())
                            wrong    = set(df_c_logs[df_c_logs['結果'] == '❌']['question_id'].tolist())
                        else:
                            answered, wrong = set(), set()
                        if combine_scope == "❌ 只取曾錯題":
                            filtered_qids = all_src_qids & wrong
                        else:  # 只取未作答
                            filtered_qids = all_src_qids - answered
                    except:
                        filtered_qids = all_src_qids
                else:
                    filtered_qids = all_src_qids

                st.info(f"📊 來源題目共 {len(all_src_qids)} 題，篩選後 **{len(filtered_qids)} 題**")

                if filtered_qids:
                    # ── 步驟3：指派設定 ───────────────────────────────────
                    st.markdown("**③ 指派設定**")
                    c3a, c3b = st.columns(2)
                    comb_grp_opts = [_group_label(g) for g in sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique())]
                    comb_grp_map  = {_group_label(g): g for g in sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique())}
                    sel_comb_grp_lbls = c3a.multiselect("目標班級", comb_grp_opts, key="combine_target_groups")
                    target_comb_groups = [comb_grp_map[l] for l in sel_comb_grp_lbls if l in comb_grp_map]

                    if target_comb_groups:
                        comb_all_stus = sorted(df_s[df_s['分組'].isin(target_comb_groups)]['姓名'].tolist())
                    else:
                        comb_all_stus = []

                    sel_comb_stus = c3b.multiselect("指派學生（預設全班）", comb_all_stus, key="combine_target_stus")
                    final_comb_stus = sel_comb_stus if sel_comb_stus else comb_all_stus

                    comb_date_col1, comb_date_col2 = st.columns(2)
                    comb_date_start = comb_date_col1.date_input("開始日期", value=get_now().date(), key="combine_date_start")
                    comb_date_end   = comb_date_col2.date_input("結束日期", value=(get_now() + timedelta(days=7)).date(), key="combine_date_end")

                    comb_task_name = st.text_input(
                        "任務名稱（留空自動產生）",
                        placeholder=f"{st.session_state.user_name}-集合任務-{get_now().strftime('%m%d')}-共{len(filtered_qids)}題",
                        key="combine_task_name"
                    )

                    # ── 預覽 ─────────────────────────────────────────────
                    with st.expander(f"📋 預覽題目清單（{len(filtered_qids)} 題）", expanded=False):
                        st.write(", ".join(sorted(filtered_qids)[:30]) + ("..." if len(filtered_qids) > 30 else ""))

                    # ── 發布 ─────────────────────────────────────────────
                    if st.button("🚀 發布集合任務", type="primary", use_container_width=True, key="combine_publish"):
                        if not target_comb_groups:
                            st.error("❌ 請選擇目標班級")
                        elif not final_comb_stus:
                            st.error("❌ 沒有指派學生")
                        else:
                            _today_str2 = get_now().strftime("%y%m%d")
                            _today_prefix2 = f"T{_today_str2}"
                            _existing2 = [str(r.get('任務編號','') or '') for _, r in df_a.iterrows()] if not df_a.empty else []
                            _today_cnt2 = sum(1 for _e in _existing2 if _e.startswith(_today_prefix2))
                            comb_task_id = f"T{_today_str2}{_today_cnt2+1:03d}"
                            _teacher_name = st.session_state.user_name
                            _publish_time = get_now().strftime("%Y-%m-%d_%H:%M")
                            _groups_label = ','.join(target_comb_groups)
                            _raw_name = comb_task_name.strip() or f"集合任務-{len(filtered_qids)}題-{_groups_label}-{_teacher_name}-{_publish_time}-{comb_date_start}~{comb_date_end}"
                            auto_name = f"[{comb_task_id}] {_raw_name}"
                            new_comb_task = pd.DataFrame([{
                                "建立時間":   get_now().strftime("%Y-%m-%d %H:%M:%S"),
                                "任務名稱":   auto_name,
                                "任務編號":   comb_task_id,
                                "對象班級":   ",".join(target_comb_groups),
                                "指派學生":   ",".join(final_comb_stus),
                                "指派人數":   len(final_comb_stus),
                                "內容":       "",
                                "任務說明":   f"集合自：{', '.join(sel_src_tasks[:3])}{'...' if len(sel_src_tasks)>3 else ''}",
                                "單字設定":   "",
                                "題目數":     len(filtered_qids),
                                "題目ID清單": ",".join(sorted(filtered_qids)),
                                "開始日期":   str(comb_date_start),
                                "結束日期":   str(comb_date_end),
                                "參考學生":   ",".join(ref_stus),
                                "狀態":       "進行中",
                                "類型":       "一般"
                            }])
                            try:
                                _sb_comb = get_supabase()
                                _comb_row = _to_en_assign({
                                    "建立時間":   get_now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "任務名稱":   auto_name,
                                    "任務編號":   comb_task_id,
                                    "對象班級":   ",".join(target_comb_groups),
                                    "指派學生":   ",".join(final_comb_stus),
                                    "指派人數":   len(final_comb_stus),
                                    "內容":       "",
                                    "任務說明":   f"集合自：{', '.join(sel_src_tasks[:3])}{'...' if len(sel_src_tasks)>3 else ''}",
                                    "單字設定":   "",
                                    "題目數":     len(filtered_qids),
                                    "題目ID清單": ",".join(sorted(filtered_qids)),
                                    "開始日期":   str(comb_date_start),
                                    "結束日期":   str(comb_date_end),
                                    "參考學生":   ",".join(ref_stus),
                                    "狀態":       "進行中",
                                    "類型":       "一般"
                                })
                                _sb_comb.table("assignments").insert(_comb_row).execute()
                                load_assignments.clear()
                                st.session_state['_a2_cache_stale'] = True
                                st.session_state['_publish_success'] = f"🎉 集合任務發布成功！\n任務序號：**{comb_task_id}**\n任務名稱：**{auto_name}**\n共 {len(filtered_qids)} 題，已指派給 {len(final_comb_stus)} 位學生。"
                                st.balloons()
                                for _k in ['combine_src_tasks','combine_scope','combine_ref_group',
                                           'combine_date_start','combine_date_end','comb_task_name',
                                           'combine_target_groups','combine_stus']:
                                    st.session_state.pop(_k, None)
                                st.rerun()
                            except Exception as _e_comb:
                                st.error(f"❌ 發布失敗：{_e_comb}")

        # ══════════════════════════════════════════════════════════════════
        # 區塊三：競賽答題模式任務
        # ══════════════════════════════════════════════════════════════════
        st.divider()
        st.subheader("🏆 競賽答題模式")
        st.caption("題目隨機、選項隨機、答完不顯示對錯，最後一起顯示成績和排名")

        with st.expander("➕ 建立競賽任務", expanded=False):
            import re as _re_race

            # 選擇來源任務
            _race_task_opts = ["（請選擇任務）"]
            _df_a_race = pd.DataFrame()
            if not df_a.empty and '任務名稱' in df_a.columns:
                _df_a_race = df_a[df_a.get('狀態', pd.Series(dtype=str)).fillna('') != '已刪除'].copy()
                _df_a_race = _df_a_race[_df_a_race['任務名稱'].str.contains(r'\[T\d+\]', regex=True, na=False)]
                _race_task_opts = ["（請選擇任務）"] + _sort_task_names(_df_a_race['任務名稱'].tolist())

            sel_race_src = st.selectbox("📋 選擇來源任務", _race_task_opts, key="race_src_task")

            # 指派班級
            all_groups_race = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique())
            race_groups = st.multiselect("👥 指派班級", [_group_label(g) for g in all_groups_race], key="race_groups")
            race_group_ids = [g for g in all_groups_race if _group_label(g) in race_groups]

            # 日期
            _rcc1, _rcc2 = st.columns(2)
            race_date_start = _rcc1.date_input("開始日期", value=get_now().date(), key="race_date_start")
            race_date_end   = _rcc2.date_input("結束日期", value=get_now().date(), key="race_date_end")

            if st.button("🚀 發布競賽任務", type="primary", use_container_width=True, key="race_publish"):
                if sel_race_src == "（請選擇任務）":
                    st.error("請先選擇來源任務")
                elif not race_groups:
                    st.error("請選擇指派班級")
                else:
                    _race_row = _df_a_race[_df_a_race['任務名稱'] == sel_race_src].iloc[0]
                    _race_qids_str = str(_race_row.get('題目ID清單','') or '')
                    _race_qids = [q.strip() for q in _race_qids_str.split(',') if q.strip() and q.strip() != 'nan']
                    _race_stus = []
                    for _rg in race_group_ids:
                        _race_stus.extend(df_s[df_s['分組'] == _rg]['姓名'].tolist())
                    _race_stus = sorted(set(_race_stus))

                    try:
                        # 取任務序號
                        _sb_r = get_supabase()
                        _today_r = get_now().strftime("%y%m%d")
                        _exist_r = _sb_r.table("assignments").select("task_id").execute()
                        _today_cnt_r = sum(1 for row in (_exist_r.data or []) if str(row.get('task_id','')).startswith(f'T{_today_r}'))
                        _race_tid = f"T{_today_r}{_today_cnt_r+1:03d}"
                        _groups_lbl = ','.join(race_group_ids)
                        _teacher = st.session_state.user_name
                        _ptime   = get_now().strftime("%Y-%m-%d_%H:%M")
                        _race_name = f"[{_race_tid}] 競賽模式-{_sort_task_names([sel_race_src])[0]}-{len(_race_qids)}題-{_groups_lbl}-{_teacher}-{_ptime}-{race_date_start}~{race_date_end}"

                        _race_payload = _to_en_assign({
                            "建立時間":  get_now().strftime("%Y-%m-%d %H:%M:%S"),
                            "任務名稱":  _race_name,
                            "任務編號":  _race_tid,
                            "對象班級":  _groups_lbl,
                            "指派學生":  ','.join(_race_stus),
                            "指派人數":  len(_race_stus),
                            "內容":      "競賽模式",
                            "任務說明":  f"競賽模式，來源：{sel_race_src}",
                            "單字設定":  "",
                            "題目數":    len(_race_qids),
                            "題目ID清單": ','.join(_race_qids),
                            "開始日期":  str(race_date_start),
                            "結束日期":  str(race_date_end),
                            "參考學生":  '',
                            "狀態":      "進行中",
                            "類型":      "競賽",
                        })
                        _sb_r.table("assignments").insert(_race_payload).execute()
                        load_assignments.clear()
                        st.session_state['_a2_cache_stale'] = True
                        st.success(f"🎉 競賽任務發布！序號：{_race_tid}，共 {len(_race_qids)} 題，{len(_race_stus)} 位學生")
                        st.balloons()
                        st.rerun()
                    except Exception as _e_race:
                        st.error(f"❌ 發布失敗：{_e_race}")

        # ══════════════════════════════════════════════════════════════════
        # 區塊四：任務列表
        # ══════════════════════════════════════════════════════════════════
        st.divider()
        st.subheader("📋 任務列表")

        # ── 任務列表（處理結果快取在 session_state，避免每次 rerun 重跑）──
        _a2_cache_key = f"_df_a2_processed_{len(df_a)}_{id(df_a)}"
        if _a2_cache_key not in st.session_state or st.session_state.get('_a2_cache_stale', False):
            df_a2 = df_a[df_a.get('狀態', pd.Series(dtype=str)).fillna('') != '已刪除'].copy() if not df_a.empty else pd.DataFrame()
            if not df_a2.empty and '建立時間' in df_a2.columns:
                df_a2 = df_a2.sort_values(
                    by='任務名稱',
                    key=lambda col: col.apply(lambda n: re.sub(r'^\[T\d+\]\s*', '', str(n)).strip().lower()),
                    ascending=True
                ).reset_index(drop=True)
            if not df_a2.empty and '任務名稱' in df_a2.columns:
                df_a2 = df_a2[df_a2['任務名稱'].str.contains(r'\[T\d+\]', regex=True, na=False)]
            # 提取老師名
            def _get_teacher(name):
                clean = re.sub(r'^\[T\d+\]\s*', '', str(name).strip())
                m = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}:\d{2})', clean)
                if m:
                    before_dt = clean[:m.start()].rstrip('-')
                    parts = before_dt.split('-')
                    if parts:
                        return parts[-1].strip()
                return clean.split('-')[0].strip() or '未知'
            if not df_a2.empty:
                df_a2['_teacher'] = df_a2['任務名稱'].apply(_get_teacher)
            st.session_state[_a2_cache_key] = df_a2
            st.session_state['_a2_cache_stale'] = False
        else:
            df_a2 = st.session_state[_a2_cache_key]

        if df_a2.empty or '任務名稱' not in df_a2.columns:
            st.info("目前尚無任務。")
        else:
            teachers = sorted(df_a2['_teacher'].unique().tolist()) if '_teacher' in df_a2.columns else []

            # 依老師建立 Tab，登入老師排第一
            current_teacher = st.session_state.get('user_name', '')
            if current_teacher in teachers:
                teachers = [current_teacher] + [t for t in teachers if t != current_teacher]

            if len(teachers) == 1:
                teacher_tabs = [st.container()]
                teacher_map  = {teachers[0]: teacher_tabs[0]}
            else:
                teacher_tabs = st.tabs(teachers)
                teacher_map  = {t: teacher_tabs[i] for i, t in enumerate(teachers)}

            for teacher, tab_container in teacher_map.items():
                with tab_container:
                    df_teacher = df_a2[df_a2['_teacher'] == teacher]
                    # 分頁顯示任務
                    TASK_PAGE = 50
                    total_tasks = len(df_teacher)
                    total_task_pages = max(1, (total_tasks + TASK_PAGE - 1) // TASK_PAGE)
                    task_page_key = f"task_page_{teacher}"
                    cur_task_page = st.session_state.get(task_page_key, 0)

                    if total_task_pages > 1:
                        tp1, tp2, tp3 = st.columns([1, 3, 1])
                        if tp1.button("◀", key=f"tp_prev_{teacher}", disabled=cur_task_page==0):
                            st.session_state[task_page_key] = cur_task_page - 1
                            st.rerun()
                        tp2.caption(f"第 {cur_task_page+1}/{total_task_pages} 頁（共 {total_tasks} 個任務）")
                        if tp3.button("▶", key=f"tp_next_{teacher}", disabled=cur_task_page>=total_task_pages-1):
                            st.session_state[task_page_key] = cur_task_page + 1
                            st.rerun()
                        t_start = cur_task_page * TASK_PAGE
                        df_teacher_page = df_teacher.iloc[t_start:t_start+TASK_PAGE]
                    else:
                        df_teacher_page = df_teacher

                    for idx, row in df_teacher_page.iterrows():
                        task_name    = row.get('任務名稱', '未命名')
                        task_group   = row.get('對象班級', row.get('對象', ''))
                        task_start   = row.get('開始日期', '')
                        task_end     = row.get('結束日期', '')
                        task_status  = str(row.get('狀態', '進行中'))
                        date_info    = f"{task_start} ～ {task_end}" if task_start else ""
                        done_icon    = "⚫" if task_status == '已結束' else "🔵"
                        _exp_key     = f"exp_{teacher}_{idx}"

                        # 標題列：任務名稱 + 展開/收起按鈕
                        _col1, _col2 = st.columns([8, 1])
                        _col1.markdown(f"**{done_icon} {task_name}**　{task_group}　{date_info}")
                        _is_open = st.session_state.get(_exp_key, False)
                        if _col2.button("▼" if not _is_open else "▲", key=f"btn_{_exp_key}", use_container_width=True):
                            st.session_state[_exp_key] = not _is_open
                            st.rerun()

                        if _is_open:
                            # ── 展開後才計算 ─────────────────────────────────
                            task_stu_str = str(row.get('指派學生', ''))
                            task_q_ids   = str(row.get('題目ID清單', ''))
                            assigned_stus = [s.strip() for s in task_stu_str.split(',') if s.strip()] if task_stu_str else []
                            q_ids_set     = set([q.strip() for q in task_q_ids.split(',') if q.strip()]) if task_q_ids else set()
                            task_q_count  = len(q_ids_set) if q_ids_set else max(int(float(str(row.get('題目數', 0)) or 0)), 0)
                            assign_count  = len(assigned_stus)

                            # 取任務編號（用來篩選 logs）
                            _tid = str(row.get('任務編號', '') or '')
                            if not _tid:
                                _m = re.search(r'\[T(\d+)\]', task_name)
                                if _m: _tid = 'T' + _m.group(1)

                            # 依任務編號篩選 df_l
                            if _tid and not df_l.empty and '任務名稱' in df_l.columns:
                                df_l_task = df_l[df_l['任務名稱'].fillna('') == _tid]
                                if df_l_task.empty:
                                    df_l_task = df_l
                            else:
                                df_l_task = df_l

                            # 計算完成人數
                            completed = 0
                            if assigned_stus and q_ids_set and not df_l_task.empty and '題目ID' in df_l_task.columns:
                                for stu in assigned_stus:
                                    stu_done = set(df_l_task[(df_l_task['姓名'] == stu) & (~df_l_task['結果'].str.contains('📖', na=False))]['題目ID'].tolist())
                                    if q_ids_set.issubset(stu_done):
                                        completed += 1

                            all_done = (completed == assign_count and assign_count > 0)
                            # 任務說明
                            admin_desc = str(row.get('任務說明', '')).strip()
                            if admin_desc and admin_desc != 'nan':
                                st.info(f"📋 {admin_desc}")
        
                            ic1, ic2, ic3, ic4 = st.columns(4)
                            ic1.metric("指派人數", assign_count)
                            ic2.metric("已完成", completed)
                            ic3.metric("題目數", task_q_count)
                            ic4.metric("狀態", "🟢 全部完成" if all_done else ("🔴 進行中" if task_status != '已結束' else "⚫ 已結束"))
        
                            # 各學生完成狀況
                            if assigned_stus and q_ids_set and not df_l_task.empty and '題目ID' in df_l_task.columns:
                                st.markdown("**學生完成狀況：**")
                                sc = st.columns(min(len(assigned_stus), 5))
                                for i, stu in enumerate(assigned_stus):
                                    stu_done = set(df_l_task[(df_l_task['姓名'] == stu) & (~df_l_task['結果'].str.contains('📖', na=False))]['題目ID'].tolist())
                                    done_q   = len(q_ids_set & stu_done)
                                    sc[i % 5].markdown(f"{'✅' if q_ids_set.issubset(stu_done) else '🔄'} **{stu}**  \n{done_q}/{task_q_count} 題")
        
                            st.divider()
                            st.markdown("**✏️ 修改任務內容**")

                            # 日期
                            ed1, ed2 = st.columns(2)
                            try:
                                cur_start = datetime.strptime(task_start, "%Y-%m-%d").date() if task_start else get_now().date()
                                cur_end   = datetime.strptime(task_end,   "%Y-%m-%d").date() if task_end   else get_now().date() + timedelta(days=7)
                            except:
                                cur_start = get_now().date()
                                cur_end   = get_now().date() + timedelta(days=7)
                            new_start = ed1.date_input("開始日期", value=cur_start, key=f"edit_start_{idx}")
                            new_end   = ed2.date_input("結束日期", value=cur_end,   key=f"edit_end_{idx}")

                            # 任務名稱：自動把結尾日期~日期換成新的
                            import re as _re3
                            def _update_name_dates(name, s, e):
                                new = _re3.sub(r'\d{4}-\d{2}-\d{2}~\d{4}-\d{2}-\d{2}$', f"{s}~{e}", str(name).strip())
                                return new
                            auto_new_name = _update_name_dates(task_name, new_start, new_end)
                            # key 用 idx + 建立時間 hash，確保每個任務獨立
                            _name_key = f"edit_name_{idx}_{str(row.get('建立時間',''))}"
                            # 初始化時才寫入，避免被其他任務覆蓋
                            if _name_key not in st.session_state:
                                st.session_state[_name_key] = auto_new_name
                            new_name = st.text_input("任務名稱（可手動修改）", key=_name_key)
        
                            # 學生（可刪除）
                            st.markdown("**👥 指派學生（取消勾選即移除）**")
                            all_stu_pool = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['姓名'].tolist())
                            new_stus = st.multiselect(
                                "學生名單", all_stu_pool,
                                default=[s for s in assigned_stus if s in all_stu_pool],
                                key=f"edit_stus_{idx}"
                            )
        
                            if st.button("💾 儲存修改", key=f"save_task_{idx}", type="primary", use_container_width=True):
                                if new_end < new_start:
                                    st.error("❌ 結束日期不能早於開始日期")
                                elif not new_stus:
                                    st.error("❌ 請至少保留一位學生")
                                else:
                                    try:
                                        sb = get_supabase()
                                        task_created = str(row.get('建立時間', ''))
                                        sb.table("assignments").update({
                                            "task_name":         new_name.strip(),
                                            "start_date":        str(new_start),
                                            "end_date":          str(new_end),
                                            "assigned_students": ",".join(new_stus),
                                            "student_count":     str(len(new_stus))
                                        }).eq("created_at", task_created).execute()
                                        st.success("✅ 任務已更新")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"儲存失敗：{e}")
        
                            st.divider()
                            del_key = f"del_task_{idx}"
                            if st.button("🗑️ 刪除此任務", key=del_key):
                                try:
                                    sb = get_supabase()
                                    task_created = str(row.get('建立時間', ''))
                                    sb.table("assignments").update({
                                        "status": "已刪除"
                                    }).eq("created_at", task_created).execute()
                                    st.success("✅ 任務已標記刪除")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"刪除失敗：{e}")
        
                            # ── 下載 PDF（功能5）─────────────────────────────
                            if q_ids_set:
                                st.divider()
                                st.markdown("**🖨️ 下載 PDF**")
        
                                def _get_task_questions(qids):
                                    df_q2 = pd.concat([df_q, df_mcq], ignore_index=True) if not df_mcq.empty else df_q.copy()
                                    df_q2['題目ID'] = df_q2.apply(lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1)
                                    df_q2 = df_q2.drop_duplicates(subset='題目ID', keep='last')
                                    df_q2['題目ID'] = df_q2.apply(
                                        lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1
                                    )
                                    norm_ids = set(qid[2:] if qid.startswith('V_') else qid for qid in qids)
                                    return df_q2[df_q2['題目ID'].isin(norm_ids)].to_dict('records')
        
                                task_q_list = _get_task_questions(q_ids_set)
                                if task_q_list:
                                    export_mode_t1 = st.radio(
                                        "列印內容",
                                        ["① 只有題目", "② 題目＋答案＋解析"],
                                        horizontal=True, key=f"export_mode_task_{idx}"
                                    )
                                    t1_mode_num = 1 if "①" in export_mode_t1 else 2
                                    title_tsk   = f"{task_name}-共{len(task_q_list)}題"
        
                                    # 當選項改變時重新產生
                                    pdf_cache_key_t = f"pdf_task_{idx}_{t1_mode_num}"
                                    if st.session_state.get(f'pdf_task_cache_{idx}') != pdf_cache_key_t:
                                        try:
                                            pdf_task = _gen_print_pdf(task_q_list, t1_mode_num, title=title_tsk)
                                            st.session_state[f'pdf_task_data_{idx}']  = pdf_task
                                            st.session_state[f'pdf_task_name_{idx}']  = f"{title_tsk}.pdf"
                                            st.session_state[f'pdf_task_cache_{idx}'] = pdf_cache_key_t
                                            st.session_state[f'pdf_task_cnt_{idx}']   = 0
                                        except Exception as e:
                                            st.error(f"❌ PDF 產生失敗：{e}")
        
                                    if st.session_state.get(f'pdf_task_data_{idx}'):
                                        cnt_t = st.session_state.get(f'pdf_task_cnt_{idx}', 0)
                                        tl1, tl2 = st.columns(2)
                                        tl1.download_button(
                                            label=f"⬇️ 下載 PDF（{export_mode_t1[:1]}）",
                                            data=bytes(st.session_state[f'pdf_task_data_{idx}']),
                                            file_name=st.session_state.get(f'pdf_task_name_{idx}', 'print.pdf'),
                                            mime="application/pdf",
                                            use_container_width=True,
                                            key=f"dl_pdf_task_{idx}_{cnt_t}",
                                            on_click=lambda i=idx, c=cnt_t: st.session_state.update({f'pdf_task_cnt_{i}': c + 1})
                                        )
                                        tl2.download_button(
                                            label="📊 下載 CSV",
                                            data=_gen_csv(task_q_list, t1_mode_num),
                                            file_name=f"{title_tsk}.csv",
                                            mime="text/csv",
                                            use_container_width=True,
                                            key=f"dl_csv_task_{idx}_{cnt_t}"
                                        )

    with t2:
        st.subheader("👥 學生帳號清單")

        # ── 同步到 Supabase ──────────────────────────────────────────────
        _sync_c1, _sync_c2 = st.columns([4, 1])
        _sync_c1.caption("將 Google Sheets 學生資料同步到 Supabase students 資料表（自動建表）")
        if _sync_c2.button("🔄 同步到 Supabase", key="sync_students_to_sb", use_container_width=True):
            try:
                _sb_sync = get_supabase()
                # 讀取最新的 students 工作表
                _df_sync = conn.read(worksheet="students", ttl=0).fillna("").astype(str).replace(r'\.0$', '', regex=True)
                _df_sync = _df_sync[[c for c in _df_sync.columns if not str(c).startswith('Unnamed')]]

                # 自動建立資料表（若不存在）
                _create_sql = """
                CREATE TABLE IF NOT EXISTS students (
                    id bigserial primary key,
                    account text,
                    password text,
                    name text unique not null,
                    group_id text,
                    school_year text,
                    version text,
                    updated_at timestamptz default now()
                );
                """
                try:
                    _sb_sync.rpc('execute_sql', {'sql': _create_sql}).execute()
                except:
                    pass  # 若 rpc 不存在，嘗試直接 upsert（資料表已存在）

                # 欄位對照（中文→英文）
                _col_map = {
                    '帳號': 'account',
                    '密碼': 'password',
                    '姓名': 'name',
                    '分組': 'group_id',
                    '學年': 'school_year',
                    '版本': 'version',
                }
                _rows = []
                for _, r in _df_sync.iterrows():
                    _row = {}
                    for cn, en in _col_map.items():
                        _val = str(r.get(cn, '') or '').strip()
                        # 帳號和密碼：確保4位數字字串（補0）
                        if en in ('account', 'password') and _val.isdigit():
                            _val = _val.zfill(4)
                        _row[en] = _val
                    if _row.get('name'):  # 跳過空白列
                        _rows.append(_row)

                if _rows:
                    with st.spinner(f"⏳ 同步 {len(_rows)} 筆學生資料..."):
                        # 刪除已不在 Google Sheets 的學生
                        _names_in_sheet = [r['name'] for r in _rows]
                        # 取得 Supabase 現有學生
                        _existing = _sb_sync.table("students").select("name").execute()
                        _existing_names = [r['name'] for r in (_existing.data or [])]
                        _to_delete = [n for n in _existing_names if n not in _names_in_sheet]
                        if _to_delete:
                            for _dn in _to_delete:
                                _sb_sync.table("students").delete().eq("name", _dn).execute()
                        # upsert 新增/更新
                        _batch_size = 100
                        for _i in range(0, len(_rows), _batch_size):
                            _batch = _rows[_i:_i+_batch_size]
                            _sb_sync.table("students").upsert(_batch, on_conflict="name").execute()
                    _del_msg = f"，已刪除 {len(_to_delete)} 筆" if _to_delete else ""
                    st.success(f"✅ 成功同步 {len(_rows)} 筆學生資料{_del_msg}！")
                    load_students_only.clear()
                else:
                    st.warning("⚠️ Google Sheets 無學生資料")
            except Exception as _e_sync:
                st.error(f"❌ 同步失敗：{_e_sync}")
                st.code("""-- 請先在 Supabase SQL Editor 執行以下建表語法：
CREATE TABLE IF NOT EXISTS students (
    id bigserial primary key,
    account text,
    password text,
    name text unique not null,
    group_id text,
    school_year text,
    version text,
    updated_at timestamptz default now()
);""", language="sql")

        st.divider()

        # ── 篩選 ──────────────────────────────────────────────────────────
        sa1, sa2 = st.columns(2)
        s_group_filter = sa1.selectbox(
            "班級/分組",
            ["全部"] + sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique().tolist()),
            key="t3_sgroup"
        )
        s_name_filter = sa2.text_input("🔍 姓名搜尋", placeholder="輸入姓名關鍵字", key="t3_sname")

        # 套用篩選
        df_s_show = df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])].copy()
        if s_group_filter != "全部":
            df_s_show = df_s_show[df_s_show['分組'] == s_group_filter]
        if s_name_filter.strip():
            df_s_show = df_s_show[df_s_show['姓名'].str.contains(s_name_filter.strip(), na=False)]

        # 帳號、密碼補零至4位，並移除無名欄位
        df_s_display = df_s_show.copy()
        # 移除 Unnamed 欄位
        df_s_display = df_s_display[[c for c in df_s_display.columns if not str(c).startswith('Unnamed')]]
        for col in ['帳號', '密碼']:
            if col in df_s_display.columns:
                df_s_display[col] = df_s_display[col].apply(
                    lambda v: str(v).split('.')[0].strip().zfill(4) if str(v).split('.')[0].strip().isdigit() else str(v)
                )

        st.caption(f"共 {len(df_s_display)} 位學生")
        st.dataframe(df_s_display.reset_index(drop=True), use_container_width=True)

        st.divider()
        st.subheader("🎤 朗讀紀錄明細")

        # ── 篩選條件 ──────────────────────────────────────────────────────
        f1, f2, f3 = st.columns(3)

        # 班級
        all_groups_t3  = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique().tolist())
        group_opts_t3  = ["全部"] + [_group_label(g) for g in all_groups_t3]
        group_map_t3   = {"全部": "全部", **{_group_label(g): g for g in all_groups_t3}}
        sel_t3_lbl     = f1.selectbox("👥 班級", group_opts_t3, key="t3_rgroup")
        t3_group       = group_map_t3.get(sel_t3_lbl, "全部")
        if t3_group == "全部":
            t3_pool = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['姓名'].tolist())
        else:
            t3_pool = sorted(df_s[df_s['分組'] == t3_group]['姓名'].tolist())

        # 姓名搜尋
        t3_name = f2.text_input("🔍 姓名搜尋", placeholder="輸入姓名關鍵字", key="t3_name")

        # 時間
        now_t3   = get_now()
        t3_time  = f3.selectbox("🕐 時間範圍", ["全部", "今日", "本週", "本月", "自訂"], key="t3_time")
        if t3_time == "今日":
            t3_from, t3_to = now_t3.date(), now_t3.date()
        elif t3_time == "本週":
            t3_from = (now_t3 - timedelta(days=now_t3.weekday())).date()
            t3_to   = now_t3.date()
        elif t3_time == "本月":
            t3_from = now_t3.date().replace(day=1)
            t3_to   = now_t3.date()
        elif t3_time == "自訂":
            dc1, dc2 = st.columns(2)
            t3_from = dc1.date_input("起始日", value=now_t3.date() - timedelta(days=7), key="t3_from")
            t3_to   = dc2.date_input("結束日", value=now_t3.date(), key="t3_to")
        else:
            t3_from, t3_to = None, None

        # 題目範圍
        st.markdown("**⚙️ 題目範圍（選填）**")
        qc = st.columns(5)
        t3_v_opts = ["全部"] + sorted(df_r['版本'].unique().tolist()) if not df_r.empty else ["全部"]
        t3_v = qc[0].selectbox("版本", t3_v_opts, key="t3_v")
        t3_u_src  = df_r[df_r['版本'] == t3_v] if (not df_r.empty and t3_v != "全部") else df_r
        t3_u_opts = ["全部"] + sorted(t3_u_src['單元'].unique().tolist()) if not df_r.empty else ["全部"]
        t3_u = qc[1].selectbox("單元", t3_u_opts, key="t3_u")
        t3_y_src  = t3_u_src[t3_u_src['單元'] == t3_u] if t3_u != "全部" else t3_u_src
        t3_y_opts = ["全部"] + sorted(t3_y_src['年度'].unique().tolist()) if not df_r.empty else ["全部"]
        t3_y = qc[2].selectbox("年度", t3_y_opts, key="t3_y")
        t3_b_src  = t3_y_src[t3_y_src['年度'] == t3_y] if t3_y != "全部" else t3_y_src
        t3_b_opts = ["全部"] + sorted(t3_b_src['冊編號'].unique().tolist()) if not df_r.empty else ["全部"]
        t3_b = qc[3].selectbox("冊編號", t3_b_opts, key="t3_b")
        t3_l_src  = t3_b_src[t3_b_src['冊編號'] == t3_b] if t3_b != "全部" else t3_b_src
        t3_l_opts = ["全部"] + sorted(t3_l_src['課編號'].unique().tolist()) if not df_r.empty else ["全部"]
        t3_l = qc[4].selectbox("課次", t3_l_opts, key="t3_l")

        # ── 套用篩選 ──────────────────────────────────────────────────────
        # 姓名過濾
        if t3_name.strip():
            t3_pool = [n for n in t3_pool if t3_name.strip() in n]

        if not df_l.empty and '題目ID' in df_l.columns:
            reading_logs = df_l[
                (df_l['姓名'].isin(t3_pool)) &
                (df_l['結果'] == '🎤 朗讀')
            ].copy()
            reading_logs['時間_dt'] = pd.to_datetime(reading_logs['時間'], errors='coerce')

            if t3_from:
                reading_logs = reading_logs[reading_logs['時間_dt'].dt.date >= t3_from]
                reading_logs = reading_logs[reading_logs['時間_dt'].dt.date <= t3_to]

            # 題目範圍：R_版本_年度_冊編號_單元_課編號_句編號
            if t3_v != "全部":
                reading_logs = reading_logs[reading_logs['題目ID'].str.contains(f"_{t3_v}_", na=False) | reading_logs['題目ID'].str.startswith(f"R_{t3_v}_", na=False)]
            if t3_b != "全部":
                reading_logs = reading_logs[reading_logs['題目ID'].str.contains(f"_{t3_b}_", na=False)]
            if t3_l != "全部":
                reading_logs = reading_logs[reading_logs['題目ID'].str.contains(f"_{t3_l}_", na=False)]

            reading_logs = reading_logs.sort_values('時間', ascending=False).drop(columns=['時間_dt'], errors='ignore')
        else:
            reading_logs = pd.DataFrame()

        st.caption(f"共 {len(reading_logs)} 筆紀錄")

        if reading_logs.empty:
            st.info("無符合條件的朗讀紀錄。")
        else:
            for stu in t3_pool:
                stu_logs = reading_logs[reading_logs['姓名'] == stu]
                if stu_logs.empty:
                    continue
                with st.expander(f"👤 {stu}　共 {len(stu_logs)} 筆", expanded=False):
                    display_cols = [c for c in ['時間', '題目ID', '學生答案', '分數'] if c in stu_logs.columns]
                    st.dataframe(stu_logs[display_cols].reset_index(drop=True), use_container_width=True)

    # --------------------------------------------------------------------------
    # 🆕 【Tab 4：題目講解】
    # --------------------------------------------------------------------------
    with t3:
        @st.fragment
        def _t3_topic_explanation():
            st.subheader("📖 題目講解")
            # 題目講解獨立更新鍵（需要 assignments + logs）
            _t3_col1, _t3_col2 = st.columns([5, 1])
            # 在 fragment 內獨立載入 logs
            _df_a_local = load_assignments()
            _df_l_local = _load_logs_cached()
            _t3_col1.caption(f"答題記錄：{len(_df_l_local)} 筆")
            if _t3_col2.button("🔄", key="t3_refresh", help="更新答題記錄"):
                st.rerun()
                return

            # fragment 內部使用局部變數
            df_a = _df_a_local
            df_l = _df_l_local

            # ── 篩選條件 ─────────────────────────────────────────────────────────
            import re as _re_t4
            all_students_t4 = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['姓名'].tolist()) if not df_s.empty and '姓名' in df_s.columns else []

            with st.form("rev_filter_form"):
                _fc1, _fc2 = st.columns(2)
                all_groups_t4 = sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique()) if not df_s.empty else []
                sel_grp_t4 = _fc1.selectbox("👥 班級/分組", ["（不限）"] + [_group_label(g) for g in all_groups_t4], key="rev_grp_t4")

                _all_tasks_t4 = ["（不限）"]
                _df_a_t4      = pd.DataFrame()
                if not df_a.empty and '任務名稱' in df_a.columns:
                    _df_a_t4 = df_a[df_a.get('狀態', pd.Series(dtype=str)).fillna('') != '已刪除'].copy()
                    _df_a_t4 = _df_a_t4[_df_a_t4['任務名稱'].str.contains(r'\[T\d+\]', regex=True, na=False)]
                    _all_tasks_t4 = ["（不限）"] + _sort_task_names(_df_a_t4['任務名稱'].tolist())

                sel_task_t4 = _fc2.selectbox("📋 選擇任務", _all_tasks_t4, key="rev_task_t4")
                sel_stus_t4 = st.multiselect("👤 學生（空白=全部）",
                    options=all_students_t4, default=[], key="rev_stus_t4")
                scope_t4 = st.radio("顯示範圍",
                    ["📚 全部題目", "✏️ 已經答題", "❌ 只看錯題", "❓ 只看未作答"],
                    horizontal=True, key="rev_scope_t4")
                _submitted = st.form_submit_button("🔍 套用篩選", use_container_width=True, type="primary")
                if _submitted:
                    for _k in [k for k in list(st.session_state.keys()) if k.startswith('_t4_')]:
                        del st.session_state[_k]


            # 取得班級值
            _grp_map_t4   = {_group_label(g): g for g in (sorted(df_s[~df_s['分組'].isin(['ADMIN','TEACHER'])]['分組'].unique()) if not df_s.empty else [])}
            rev_group_t4  = _grp_map_t4.get(sel_grp_t4, "")
            _default_stus = sorted(df_s[df_s['分組'] == rev_group_t4]['姓名'].tolist()) if rev_group_t4 else all_students_t4
            target_stus_t4 = sel_stus_t4 if sel_stus_t4 else _default_stus
            task_ids_t4   = None
            rev_tid_t4    = ""

            if sel_task_t4 != "（不限）" and not _df_a_t4.empty:
                _tr = _df_a_t4[_df_a_t4['任務名稱'] == sel_task_t4]
                if not _tr.empty:
                    _ids_str    = str(_tr.iloc[0].get('題目ID清單','') or '')
                    task_ids_t4 = set(q.strip() for q in _ids_str.split(',') if q.strip() and q.strip() != 'nan')
                    rev_tid_t4  = str(_tr.iloc[0].get('任務編號','') or '')
                    if not rev_tid_t4:
                        _m = _re_t4.search(r'\[T\d+\]', sel_task_t4)
                        if _m: rev_tid_t4 = 'T' + _m.group(1)
                    st.info(f"📋 此任務共 {len(task_ids_t4)} 題")

            # 快取 key：用 hash 縮短（避免學生名單很長）
            import hashlib as _hl
            _stus_hash = _hl.md5(','.join(sorted(target_stus_t4)).encode()).hexdigest()[:8]
            _t4_key = f"_t4_{sel_task_t4}_{rev_group_t4}_{_stus_hash}"
            # 清除舊快取
            for _old_k in [k for k in list(st.session_state.keys()) if k.startswith('_t4_') and k != _t4_key]:
                del st.session_state[_old_k]

            if _t4_key not in st.session_state:
                def _apply_scope_t4_inner(df_in, logs_in):
                    if df_in.empty or '題目ID' not in df_in.columns: return df_in
                    if logs_in.empty or '題目ID' not in logs_in.columns:
                        if scope_t4 in ("✏️ 已經答題", "❌ 只看錯題"):
                            return pd.DataFrame()  # 沒有 logs 就沒有已答/錯題
                        return df_in
                    answered = set(logs_in['題目ID'].tolist())
                    # 錯題：結果包含❌，且排除練習模式
                    _err_logs = logs_in[
                        logs_in['結果'].fillna('').str.contains('❌', na=False) &
                        ~logs_in['結果'].fillna('').str.contains('練習', na=False)
                    ]
                    wrong = set(_err_logs['題目ID'].tolist())
                    if scope_t4 == "✏️ 已經答題":   return df_in[df_in['題目ID'].isin(answered)]
                    elif scope_t4 == "❌ 只看錯題":  return df_in[df_in['題目ID'].isin(wrong)]
                    elif scope_t4 == "❓ 只看未作答": return df_in[~df_in['題目ID'].isin(answered)]
                    return df_in

                _all_logs = _df_l_local[_df_l_local['姓名'].isin(target_stus_t4)].copy() if not _df_l_local.empty else pd.DataFrame()
                if not _all_logs.empty and '題目ID' in _all_logs.columns:
                    _task_orig_ids = task_ids_t4 or set()
                    # 先用題目ID + 任務名稱比對
                    _cond = pd.Series(False, index=_all_logs.index)
                    if _task_orig_ids:
                        _cond = _cond | _all_logs['題目ID'].isin(_task_orig_ids)
                    if rev_tid_t4 and '任務名稱' in _all_logs.columns:
                        _cond = _cond | (_all_logs['任務名稱'].fillna('') == rev_tid_t4)
                    _fl = _all_logs[_cond]
                    # 若找不到，用後三段模糊比對
                    if _fl.empty and _task_orig_ids:
                        _short_ids = set('_'.join(qid.split('_')[-3:]) for qid in _task_orig_ids)
                        _all_logs['_short'] = _all_logs['題目ID'].apply(lambda x: '_'.join(str(x).split('_')[-3:]))
                        _fl = _all_logs[_all_logs['_short'].isin(_short_ids)]
                        _all_logs = _all_logs.drop(columns=['_short'], errors='ignore')
                    if not _fl.empty:
                        _all_logs = _fl.drop(columns=['_short'], errors='ignore')
                    elif not rev_tid_t4 and not _task_orig_ids:
                        pass  # 沒有任何篩選條件，保留全部
                    else:
                        _all_logs = pd.DataFrame()  # 有條件但找不到，設空



                def _qid(r, prefix=""): return f"{prefix}{r['版本']}_{r['年度']}_{r['冊編號']}_{r.get('單元','')}_{r['課編號']}_{r['句編號']}"

                with st.spinner("🔄 計算中，請稍候..."):
                    def _get(df_src, pfx=""):
                        if task_ids_t4 is None or df_src.empty: return pd.DataFrame()
                        d = df_src.copy()
                        # 向量化 ID 產生（比 apply 快 3-5 倍）
                        d['題目ID'] = (pfx +
                            d['版本'].astype(str) + '_' +
                            d['年度'].astype(str) + '_' +
                            d['冊編號'].astype(str) + '_' +
                            d.get('單元', pd.Series([''] * len(d))).astype(str) + '_' +
                            d['課編號'].astype(str) + '_' +
                            d['句編號'].astype(str)
                        )
                        return d[d['題目ID'].isin(task_ids_t4)].copy()  # scope applied on retrieval
                    _mcq2 = df_mcq.copy()
                    _mcq2['題目ID'] = (
                        _mcq2['版本'].astype(str) + '_' + _mcq2['年度'].astype(str) + '_' +
                        _mcq2['冊編號'].astype(str) + '_' + _mcq2['單元'].astype(str) + '_' +
                        _mcq2['課編號'].astype(str) + '_' + _mcq2['句編號'].astype(str)
                    )
                    _rev_mcq = _mcq2[_mcq2['題目ID'].isin(task_ids_t4)].copy() if task_ids_t4 else pd.DataFrame()  # scope applied on retrieval
                    _rev_q   = _get(df_q)
                    _rev_rm  = _get(df_rm, "RM_")
                    _rev_r   = _get(df_r,  "R_")
                    _rev_v   = _get(df_v,  "V_")

                st.session_state[_t4_key] = {
                    'mcq': _mcq2[_mcq2['題目ID'].isin(task_ids_t4)].copy() if task_ids_t4 else _rev_mcq,
                    'q': _get(df_q) if False else _rev_q,  # already computed
                    'rm': _rev_rm, 'r': _rev_r, 'v': _rev_v, 'logs': _all_logs
                }

            _cached      = st.session_state[_t4_key]
            df_rev_mcq   = _cached['mcq']
            df_rev_q2    = _cached['q']
            df_rev_rm    = _cached['rm']
            df_rev_r     = _cached['r']
            df_rev_v     = _cached['v']
            all_logs_t4  = _cached['logs']

            def _apply_scope_t4(df_in, logs_in):
                """從快取取出後套用 scope 篩選"""
                if df_in.empty or '題目ID' not in df_in.columns: return df_in
                _logs = all_logs_t4 if all_logs_t4 is not None and not all_logs_t4.empty else logs_in
                if _logs.empty or '題目ID' not in _logs.columns:
                    if scope_t4 in ("✏️ 已經答題", "❌ 只看錯題"):
                        return pd.DataFrame()
                    return df_in
                _err_logs = _logs[
                    _logs['結果'].fillna('').str.contains('❌', na=False) &
                    ~_logs['結果'].fillna('').str.contains('練習', na=False)
                ]
                wrong    = set(_err_logs['題目ID'].tolist())
                _ans_logs = _logs[~_logs['結果'].fillna('').str.contains('📖', na=False)]
                answered  = set(_ans_logs['題目ID'].tolist())
                if scope_t4 == "✏️ 已經答題":   return df_in[df_in['題目ID'].isin(answered)]
                elif scope_t4 == "❌ 只看錯題":  return df_in[df_in['題目ID'].isin(wrong)]
                elif scope_t4 == "❓ 只看未作答": return df_in[~df_in['題目ID'].isin(answered)]
                return df_in





            if task_ids_t4 is not None:
                df_mcq2 = df_mcq.copy() if not df_mcq.empty else pd.DataFrame()
                if not df_mcq2.empty:
                    df_mcq2['題目ID'] = df_mcq2.apply(lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1)
                    df_rev_mcq = df_mcq2[df_mcq2['題目ID'].isin(task_ids_t4)].copy()
                else:
                    df_rev_mcq = pd.DataFrame()
            else:
                st.info("請先選擇任務後套用篩選，即可顯示單選題講解。")
                df_rev_mcq = pd.DataFrame()

            if df_rev_mcq.empty:
                st.info("此範圍尚無單選題。")
            else:
                mcq_logs = _df_l_local[_df_l_local['姓名'].isin(target_stus_t4)].copy() if not _df_l_local.empty else pd.DataFrame()
                if not mcq_logs.empty and '題目ID' in mcq_logs.columns:
                    _fl = mcq_logs[
                        mcq_logs['題目ID'].isin(task_ids_t4 or set()) |
                        (mcq_logs['任務名稱'].fillna('') == rev_tid_t4)
                    ]
                    if not _fl.empty: mcq_logs = _fl
                df_rev_mcq = _apply_scope_t4(df_rev_mcq, all_logs_t4)
                st.markdown(f"**共 {len(df_rev_mcq)} 題**")
                _rev_summary = f"👥 {_group_label(rev_group_t4)}／{len(target_stus_t4)} 位　🔍 {scope_t4}"
                st.info(_rev_summary)
                total_rev = len(df_rev_mcq)
                st.caption(f"共 {total_rev} 題")
                df_rev_page = df_rev_mcq

                for _qi, (_, qrow) in enumerate(df_rev_page.iterrows()):
                    qid     = qrow.get('題目ID','')
                    q_title = str(qrow.get('單選題目') or qrow.get('中文題目') or '').strip()
                    q_ans   = str(qrow.get('單選答案') or qrow.get('英文答案') or '').strip()
                    q_analysis = str(qrow.get('解析') or '').strip()
                    opts_html = ""
                    for opt in ['A','B','C','D']:
                        ov = str(qrow.get(f'選項{opt}') or '').strip()
                        if ov: opts_html += f"({opt}) {ov}　"
                    label = f"句{qrow.get('句編號','')}｜{q_title[:30]}{'…' if len(q_title)>30 else ''}"
                    with st.expander(label, expanded=True):
                        st.markdown(f"<div style='font-size:1.1rem;font-weight:600;padding:8px 0;white-space:pre-wrap;'>{q_title}</div>", unsafe_allow_html=True)
                        if opts_html: st.caption(opts_html)
                        st.markdown(f"<div style='color:green;padding:4px 0;'>✅ 正確答案：{q_ans}</div>", unsafe_allow_html=True)
                        if q_analysis: st.info(f"📝 解析：{q_analysis}")
                        st.divider()
                        for stu in target_stus_t4:
                            stu_rows = mcq_logs[(mcq_logs['姓名']==stu) & (mcq_logs['題目ID']==qid) & (~mcq_logs['結果'].str.contains('📖',na=False))] if not mcq_logs.empty else pd.DataFrame()
                            stu_rev  = mcq_logs[(mcq_logs['姓名']==stu) & (mcq_logs['題目ID']==qid) & (mcq_logs['結果'].str.contains('📖',na=False))] if not mcq_logs.empty else pd.DataFrame()
                            if stu_rows.empty:
                                st.markdown(f"　👤 **{stu}**：尚未作答")
                            else:
                                lines_s = []
                                for _, r in stu_rows.iterrows():
                                    t_str = str(r.get('時間',''))[:16]
                                    lines_s.append(f"{r.get('結果','—')} _{t_str}_")
                                st.markdown(f"　👤 **{stu}**：" + "　／　".join(lines_s))
                            if not stu_rev.empty:
                                rev_ls = [f"{r.get('結果','')} _{str(r.get('時間',''))[:16]}_" for _, r in stu_rev.iterrows()]
                                st.markdown(f"　　　　　" + "　／　".join(rev_ls))
                        btn_key = f"rev_done_mcq_{_qi}_{qid}"
                        if st.button("📖 講解完成，寫入紀錄", key=btn_key, type="primary", use_container_width=True):
                            now_str = get_now().strftime("%Y-%m-%d %H:%M:%S")
                            rows_log = [{"時間": now_str, "姓名": stu, "分組": rev_group_t4, "題目ID": qid, "結果": "📖 講解", "學生答案": ""} for stu in target_stus_t4]
                            if append_to_sheet("logs", pd.DataFrame(rows_log)):
                                st.success(f"✅ 已為 {len(target_stus_t4)} 位學生寫入講解紀錄！")

            # ── Tab2: 重組講解 ────────────────────────────────────────────────
            st.divider()
            st.markdown("### ✏️ 重組題")
        
            if task_ids_t4 is not None:
                df_q2 = df_q.copy()
                df_q2['題目ID'] = df_q2.apply(lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1)
                df_rev_q2 = df_q2[df_q2['題目ID'].isin(task_ids_t4)].copy()
            else:
                st.info("請先選擇任務後套用篩選，即可顯示重組題講解。")
                df_rev_q2 = pd.DataFrame()

            if df_rev_q2.empty:
                st.info("此範圍尚無重組題。")
            else:
                q_logs = _df_l_local[_df_l_local['姓名'].isin(target_stus_t4)].copy() if not _df_l_local.empty else pd.DataFrame()
                if not q_logs.empty and '題目ID' in q_logs.columns:
                    _fl = q_logs[
                        q_logs['題目ID'].isin(task_ids_t4 or set()) |
                        (q_logs['任務名稱'].fillna('') == rev_tid_t4)
                    ]
                    if not _fl.empty: q_logs = _fl
                df_rev_q2 = _apply_scope_t4(df_rev_q2, all_logs_t4)
                st.markdown(f"**共 {len(df_rev_q2)} 題**")
                st.info(f"👥 {_group_label(rev_group_t4)}／{len(target_stus_t4)} 位　🔍 {scope_t4}")
                total_rev = len(df_rev_q2)
                st.caption(f"共 {total_rev} 題")
                df_rev_page = df_rev_q2

                for _qi, (_, qrow) in enumerate(df_rev_page.iterrows()):
                    qid     = qrow.get('題目ID','')
                    q_title = str(qrow.get('重組中文題目') or qrow.get('中文題目') or '').strip()
                    q_ans   = str(qrow.get('重組英文答案') or qrow.get('英文答案') or '').strip()
                    label   = f"句{qrow.get('句編號','')}｜{q_title[:30]}{'…' if len(q_title)>30 else ''}"
                    with st.expander(label, expanded=True):
                        st.markdown(f"<div style='font-size:1.1rem;font-weight:600;padding:8px 0;'>{q_title}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='color:green;padding:4px 0;'>✅ {q_ans}</div>", unsafe_allow_html=True)
                        st.divider()
                        for stu in target_stus_t4:
                            stu_rows = q_logs[(q_logs['姓名']==stu) & (q_logs['題目ID']==qid) & (~q_logs['結果'].str.contains('📖',na=False))] if not q_logs.empty else pd.DataFrame()
                            stu_rev  = q_logs[(q_logs['姓名']==stu) & (q_logs['題目ID']==qid) & (q_logs['結果'].str.contains('📖',na=False))] if not q_logs.empty else pd.DataFrame()
                            if stu_rows.empty:
                                st.markdown(f"　👤 **{stu}**：尚未作答")
                            else:
                                lines_s = [f"{r.get('結果','—')} _{str(r.get('時間',''))[:16]}_" for _, r in stu_rows.iterrows()]
                                st.markdown(f"　👤 **{stu}**：" + "　／　".join(lines_s))
                            if not stu_rev.empty:
                                rev_ls = [f"{r.get('結果','')} _{str(r.get('時間',''))[:16]}_" for _, r in stu_rev.iterrows()]
                                st.markdown(f"　　　　　" + "　／　".join(rev_ls))
                        btn_key = f"rev_done_q_{_qi}_{qid}"
                        if st.button("📖 講解完成，寫入紀錄", key=btn_key, type="primary", use_container_width=True):
                            now_str = get_now().strftime("%Y-%m-%d %H:%M:%S")
                            rows_log = [{"時間": now_str, "姓名": stu, "分組": rev_group_t4, "題目ID": qid, "結果": "📖 講解", "學生答案": ""} for stu in target_stus_t4]
                            if append_to_sheet("logs", pd.DataFrame(rows_log)):
                                st.success(f"✅ 已為 {len(target_stus_t4)} 位學生寫入講解紀錄！")

            # ── Tab3: 閱讀單句講解 ────────────────────────────────────────────
            st.divider()
            st.markdown("### 📖 閱讀單句")
        
            if task_ids_t4 is not None:
                df_rm2 = df_rm.copy() if not df_rm.empty else pd.DataFrame()
                if not df_rm2.empty:
                    df_rm2['題目ID'] = df_rm2.apply(lambda r: f"RM_{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1)
                    df_rev_rm = df_rm2[df_rm2['題目ID'].isin(task_ids_t4)].copy()
                else:
                    df_rev_rm = pd.DataFrame()
            else:
                st.info("請先選擇任務後套用篩選，即可顯示閱讀單句題講解。")
                df_rev_rm = pd.DataFrame()
            if not df_rev_rm.empty:
                rm_logs = _df_l_local[_df_l_local['姓名'].isin(target_stus_t4)].copy() if not _df_l_local.empty else pd.DataFrame()
                if not rm_logs.empty and '題目ID' in rm_logs.columns:
                    _fl = rm_logs[
                        rm_logs['題目ID'].isin(task_ids_t4 or set()) |
                        (rm_logs['任務名稱'].fillna('') == rev_tid_t4)
                    ]
                    if not _fl.empty: rm_logs = _fl
                df_rev_rm = _apply_scope_t4(df_rev_rm, all_logs_t4)
                st.markdown(f"**共 {len(df_rev_rm)} 題**")
                st.info(f"👥 {_group_label(rev_group_t4)}／{len(target_stus_t4)} 位　🔍 {scope_t4}")
                total_rev = len(df_rev_rm)
                st.caption(f"共 {total_rev} 題")
                df_rev_page = df_rev_rm

                for _qi, (_, qrow) in enumerate(df_rev_page.iterrows()):
                    qid      = qrow.get('題目ID','')
                    passage  = str(qrow.get('答案') or '').strip()
                    question = str(qrow.get('題目') or '').strip()
                    correct  = str(qrow.get('正確選項列出') or '').strip()
                    analysis = str(qrow.get('解析') or '').strip()
                    label    = f"句{qrow.get('句編號','')}｜{question[:30]}{'…' if len(question)>30 else ''}"
                    with st.expander(label, expanded=True):
                        if passage: st.markdown(f"<div style='background:var(--color-background-secondary);padding:10px;border-radius:6px;margin-bottom:8px;'>{passage}</div>", unsafe_allow_html=True)
                        st.markdown(f"**{question}**")
                        opts_html = "　".join([f"({o}) {str(qrow.get(f'選項{o}') or '').strip()}" for o in ['A','B','C','D'] if qrow.get(f'選項{o}')])
                        if opts_html: st.caption(opts_html)
                        st.markdown(f"<div style='color:green;padding:4px 0;'>✅ 正確答案：{correct}</div>", unsafe_allow_html=True)
                        if analysis: st.info(f"📝 {analysis}")
                        st.divider()
                        for stu in target_stus_t4:
                            stu_rows = rm_logs[(rm_logs['姓名']==stu)&(rm_logs['題目ID']==qid)&(~rm_logs['結果'].str.contains('📖',na=False))] if not rm_logs.empty else pd.DataFrame()
                            if stu_rows.empty:
                                st.markdown(f"　👤 **{stu}**：尚未作答")
                            else:
                                lines_s = [f"{r.get('結果','—')} _{str(r.get('時間',''))[:16]}_" for _, r in stu_rows.iterrows()]
                                st.markdown(f"　👤 **{stu}**：" + "　／　".join(lines_s))
                        btn_key = f"rev_done_rm_{_qi}_{qid}"
                        if st.button("📖 講解完成，寫入紀錄", key=btn_key, type="primary", use_container_width=True):
                            now_str = get_now().strftime("%Y-%m-%d %H:%M:%S")
                            rows_log = [{"時間": now_str, "姓名": stu, "分組": rev_group_t4, "題目ID": qid, "結果": "📖 講解", "學生答案": ""} for stu in target_stus_t4]
                            if append_to_sheet("logs", pd.DataFrame(rows_log)):
                                st.success(f"✅ 已為 {len(target_stus_t4)} 位學生寫入講解紀錄！")

            # ── 朗讀講解 ──────────────────────────────────────────────────────
            st.divider()
            st.markdown("### 🎤 朗讀")
        
            if task_ids_t4 is not None:
                df_r2 = df_r.copy() if not df_r.empty else pd.DataFrame()
                if not df_r2.empty:
                    df_r2['題目ID'] = df_r2.apply(lambda r: f"R_{r['版本']}_{r['年度']}_{r['冊編號']}_{r.get('單元','')}_{r['課編號']}_{r['句編號']}", axis=1)
                    df_rev_r = df_r2[df_r2['題目ID'].isin(task_ids_t4)].copy()
            else:
                st.info("請先選擇任務後套用篩選，即可顯示朗讀題講解。")
                df_rev_r = pd.DataFrame()

            if not df_rev_r.empty:
                r_logs = _df_l_local[_df_l_local['姓名'].isin(target_stus_t4)].copy() if not _df_l_local.empty else pd.DataFrame()
                if not r_logs.empty and '題目ID' in r_logs.columns:
                    _fl = r_logs[
                        r_logs['題目ID'].isin(task_ids_t4 or set()) |
                        (r_logs['任務名稱'].fillna('') == rev_tid_t4)
                    ]
                    if not _fl.empty: r_logs = _fl
                df_rev_r = _apply_scope_t4(df_rev_r, all_logs_t4)
                st.markdown(f"**共 {len(df_rev_r)} 題**")
                st.info(f"👥 {_group_label(rev_group_t4)}／{len(target_stus_t4)} 位")
                st.caption(f"共 {len(df_rev_r)} 題")
                df_rev_page = df_rev_r
                for _qi, (_, qrow) in enumerate(df_rev_page.iterrows()):
                    qid       = qrow.get('題目ID','')
                    read_text = str(qrow.get('朗讀句子') or qrow.get('英文句子') or '').strip()
                    label     = f"句{qrow.get('句編號','')}｜{read_text[:30]}{'…' if len(read_text)>30 else ''}"
                    with st.expander(label, expanded=True):
                        st.markdown(f"<div style='font-size:1.2rem;font-weight:600;padding:8px 0;'>{read_text}</div>", unsafe_allow_html=True)
                        st.divider()
                        for stu in target_stus_t4:
                            stu_rows = r_logs[(r_logs['姓名']==stu)&(r_logs['題目ID']==qid)&(r_logs['結果']=='🎤 朗讀')] if not r_logs.empty else pd.DataFrame()
                            if stu_rows.empty:
                                st.markdown(f"　👤 **{stu}**：尚未朗讀")
                            else:
                                lines_s = [f"🎤 {r.get('分數','')}分 _{str(r.get('時間',''))[:16]}_" for _, r in stu_rows.sort_values('時間').iterrows()]
                                st.markdown(f"　👤 **{stu}**：" + "　／　".join(lines_s))
                        btn_key = f"rev_done_r_{_qi}_{qid}"
                        if st.button("📖 講解完成，寫入紀錄", key=btn_key, type="primary", use_container_width=True):
                            now_str = get_now().strftime("%Y-%m-%d %H:%M:%S")
                            rows_log = [{"時間": now_str, "姓名": stu, "分組": rev_group_t4, "題目ID": qid, "結果": "📖 講解", "學生答案": ""} for stu in target_stus_t4]
                            if append_to_sheet("logs", pd.DataFrame(rows_log)):
                                st.success(f"✅ 已為 {len(target_stus_t4)} 位學生寫入講解紀錄！")

            # ── Tab5: 拼單字講解 ──────────────────────────────────────────────
            st.divider()
            st.markdown("### 🔤 拼單字")
        
            if task_ids_t4 is not None:
                df_v2 = df_v.copy() if not df_v.empty else pd.DataFrame()
                if not df_v2.empty:
                    df_v2['題目ID'] = df_v2.apply(lambda r: f"V_{r['版本']}_{r['年度']}_{r['冊編號']}_{r.get('單元','')}_{r['課編號']}_{r['句編號']}", axis=1)
                    df_rev_v = df_v2[df_v2['題目ID'].isin(task_ids_t4)].copy()
            else:
                st.info("請先選擇任務後套用篩選，即可顯示拼單字題講解。")
                df_rev_v = pd.DataFrame()

            if not df_rev_v.empty:
                v_logs = _df_l_local[_df_l_local['姓名'].isin(target_stus_t4)].copy() if not _df_l_local.empty else pd.DataFrame()
                if not v_logs.empty and '題目ID' in v_logs.columns:
                    _fl = v_logs[
                        v_logs['題目ID'].isin(task_ids_t4 or set()) |
                        (v_logs['任務名稱'].fillna('') == rev_tid_t4)
                    ]
                    if not _fl.empty: v_logs = _fl
                df_rev_v = _apply_scope_t4(df_rev_v, all_logs_t4)
                st.markdown(f"**共 {len(df_rev_v)} 題**")
                st.info(f"👥 {_group_label(rev_group_t4)}／{len(target_stus_t4)} 位")
                st.caption(f"共 {len(df_rev_v)} 題")
                df_rev_page = df_rev_v
                for _qi, (_, qrow) in enumerate(df_rev_page.iterrows()):
                    qid     = qrow.get('題目ID','')
                    word    = str(qrow.get('英文單字') or '').strip()
                    meaning = str(qrow.get('中文意思') or '').strip()
                    label   = f"句{qrow.get('句編號','')}｜{meaning}　{word}"
                    with st.expander(label, expanded=True):
                        st.markdown(f"<div style='font-size:1.1rem;font-weight:600;'>{meaning}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='color:green;'>✅ {word}</div>", unsafe_allow_html=True)
                        st.divider()
                        for stu in target_stus_t4:
                            stu_rows = v_logs[(v_logs['姓名']==stu)&(v_logs['題目ID']==qid)&(~v_logs['結果'].str.contains('📖',na=False))] if not v_logs.empty else pd.DataFrame()
                            if stu_rows.empty:
                                st.markdown(f"　👤 **{stu}**：尚未作答")
                            else:
                                lines_s = [f"{r.get('結果','—')} _{str(r.get('時間',''))[:16]}_" for _, r in stu_rows.iterrows()]
                                st.markdown(f"　👤 **{stu}**：" + "　／　".join(lines_s))
                        btn_key = f"rev_done_v_{_qi}_{qid}"
                        if st.button("📖 講解完成，寫入紀錄", key=btn_key, type="primary", use_container_width=True):
                            now_str = get_now().strftime("%Y-%m-%d %H:%M:%S")
                            rows_log = [{"時間": now_str, "姓名": stu, "分組": rev_group_t4, "題目ID": qid, "結果": "📖 講解", "學生答案": ""} for stu in target_stus_t4]
                            if append_to_sheet("logs", pd.DataFrame(rows_log)):
                                st.success(f"✅ 已為 {len(target_stus_t4)} 位學生寫入講解紀錄！")
            st.divider()
        _t3_topic_explanation()

    with t4:
        st.subheader("🏆 競賽結果")

        # 選競賽任務
        _df_a_rt = pd.DataFrame()
        _race_opts = ["（請選擇競賽任務）"]
        if not df_a.empty and '任務名稱' in df_a.columns and '類型' in df_a.columns:
            _df_a_rt = df_a[df_a['類型'].fillna('') == '競賽'].copy()
            if not _df_a_rt.empty:
                _race_opts = ["（請選擇競賽任務）"] + _sort_task_names(_df_a_rt['任務名稱'].tolist())

        _sel_race = st.selectbox("📋 選擇競賽任務", _race_opts, key="t4_race_sel")

        if _sel_race == "（請選擇競賽任務）":
            st.info("請選擇競賽任務查看結果。")
        else:
            _rt4_col1, _rt4_col2 = st.columns([4, 1])
            _rt4_col1.caption("競賽結果即時統計")
            if _rt4_col2.button("🔄 更新", key="t4_race_refresh", use_container_width=True):
                st.session_state.pop('_race_result_cache', None)

            _race_cache_key = f"_race_result_{_sel_race}"
            if _race_cache_key not in st.session_state:
                _df_l_race = _get_df_l()
                _race_row  = _df_a_rt[_df_a_rt['任務名稱'] == _sel_race].iloc[0]
                _race_qids_str = str(_race_row.get('題目ID清單','') or '')
                _race_qids = set(q.strip() for q in _race_qids_str.split(',') if q.strip() and q.strip() != 'nan')
                _total_q   = len(_race_qids)

                # 篩選此競賽的 logs
                _rt_logs = pd.DataFrame()
                if not _df_l_race.empty and _race_qids:
                    _rev_tid = str(_race_row.get('任務編號','') or '')
                    _rt_logs = _df_l_race[
                        _df_l_race['題目ID'].isin(_race_qids) |
                        (_df_l_race['任務名稱'].fillna('') == _rev_tid)
                    ].copy()

                # 計算排名
                _rank_data = []
                if not _rt_logs.empty and '時間' in _rt_logs.columns:
                    for _stu, _sg in _rt_logs.groupby('姓名'):
                        _sg = _sg.sort_values('時間')
                        try:
                            _times = pd.to_datetime(_sg['時間'])
                            _gaps  = _times.diff().dt.total_seconds().fillna(9999)
                            _sg = _sg.copy()
                            _sg['參賽次'] = (_gaps > 300).cumsum() + 1
                        except:
                            _sg['參賽次'] = 1
                        for _ano, _ag in _sg.groupby('參賽次'):
                            _s_answered = set(_ag[~_ag['結果'].fillna('').str.contains('📖|練習')]['題目ID'].tolist())
                            _s_correct  = set(_ag[_ag['結果'].fillna('').str.contains('✅')]['題目ID'].tolist())
                            _s_wrong    = _s_answered - _s_correct
                            _s_acc      = len(_s_correct) / _total_q if _total_q else 0
                            _s_time = 9999
                            if len(_ag) >= 2:
                                try:
                                    _t_sorted = pd.to_datetime(_ag['時間']).sort_values()
                                    _s_time   = (_t_sorted.iloc[-1] - _t_sorted.iloc[0]).total_seconds()
                                except:
                                    pass
                            _rank_data.append({
                                '姓名': _stu,
                                '次數': int(_ano),
                                '答題數': len(_s_answered),
                                '答對數': len(_s_correct),
                                '答錯數': len(_s_wrong),
                                '正確率': _s_acc,
                                '作答秒數': _s_time,
                            })

                st.session_state[_race_cache_key] = {
                    'rank_data': _rank_data,
                    'total_q': _total_q,
                }

            _rc = st.session_state.get(_race_cache_key, {})
            _rank_data = _rc.get('rank_data', [])
            _total_q   = _rc.get('total_q', 0)

            if not _rank_data:
                st.info("目前尚無學生作答記錄。")
            else:
                _rank_df = pd.DataFrame(_rank_data).sort_values(
                    ['正確率', '作答秒數'], ascending=[False, True]
                ).reset_index(drop=True)
                _rank_df.index += 1
                _rank_df['正確率']  = _rank_df['正確率'].apply(lambda x: f"{int(x*100)}%")
                _rank_df['作答時間'] = _rank_df['作答秒數'].apply(
                    lambda x: f"{int(x//60)}分{int(x%60):02d}秒" if x < 9000 else "—"
                )
                _rank_df = _rank_df[['姓名','次數','答題數','答對數','答錯數','正確率','作答時間']]

                st.caption(f"共 {len(_rank_df)} 位學生作答　總題數：{_total_q} 題")
                st.dataframe(_rank_df, use_container_width=True, hide_index=False)

    st.stop()

# ------------------------------------------------------------------------------
# 📦 【盒子 C：練習範圍設定】
# ------------------------------------------------------------------------------
if not st.session_state.quiz_loaded:

    # ══════════════════════════════════════════════════════════════════════
    # 🆕 學生任務列表（登入後優先顯示）
    # ══════════════════════════════════════════════════════════════════════
    user_name = st.session_state.user_name
    today_dt  = get_now().date()

    # 找出指派給這位學生、未刪除、日期有效的任務
    my_tasks = []
    debug_info = []  # 除錯用
    if not df_a.empty:
        for _, arow in df_a.iterrows():
            task_n = str(arow.get('任務名稱', ''))
            # 過濾已刪除
            if str(arow.get('狀態', '')).strip() == '已刪除':
                debug_info.append(f"❌ {task_n}：已刪除")
                continue
            # 只顯示新格式任務（含 [Txxxxxxx] 編號前綴）
            import re as _re2
            if not _re2.search(r'\[T\d+\]', task_n):
                debug_info.append(f"❌ {task_n}：舊格式，略過")
                continue

            # 確認學生在指派名單中（ADMIN/TEACHER 跳過此檢查）
            if not is_admin(st.session_state.group_id):
                stu_str  = str(arow.get('指派學生', '') or arow.get('對象', '') or '')
                assigned = [s.strip() for s in stu_str.split(',') if s.strip()]
                if user_name not in assigned:
                    debug_info.append(f"❌ {task_n}：學生不在名單（名單：{stu_str[:50]}）")
                    continue

            # 日期範圍檢查
            try:
                end_str = str(arow.get('結束日期', '')).strip()
                if not end_str or end_str == 'nan':
                    debug_info.append(f"❌ {task_n}：無結束日期")
                    continue
                t_end = datetime.strptime(end_str, "%Y-%m-%d").date()
                if t_end < today_dt:
                    debug_info.append(f"❌ {task_n}：已過期（{end_str}）")
                    continue
            except Exception as e:
                debug_info.append(f"❌ {task_n}：日期格式錯誤（{e}）")
                continue

            debug_info.append(f"✅ {task_n}：符合條件")
            # 題目ID清單必須有資料才顯示
            task_ids_str = str(arow.get('題目ID清單', '') or '')
            valid_ids = [q.strip() for q in task_ids_str.split(',') if q.strip() and q.strip() != 'nan']
            if not valid_ids:
                debug_info.append(f"⚠️ {task_n}：符合條件但題目ID清單為空，不顯示")
                continue
            my_tasks.append(arow)

    # 依序號後的名稱排序（移除 [Txxxxxxxx] 前綴）
    my_tasks.sort(key=lambda r: re.sub(r'^\[T\d+\]\s*', '', str(r.get('任務名稱',''))).strip().lower())

    if my_tasks:
        st.markdown("<h2 style='margin-bottom:0'>📋 我的任務</h2>", unsafe_allow_html=True)
        for _task_idx, arow in enumerate(my_tasks):
            task_name    = arow.get('任務名稱', '未命名')
            task_id_key  = arow.get('任務編號', '') or ''
            # 若任務編號欄位空白，從任務名稱的 [Txxxxxxx] 提取
            if not task_id_key and task_name:
                import re as _re_tid
                _m = _re_tid.search(r'\[T(\d+)\]', task_name)
                if _m:
                    task_id_key = 'T' + _m.group(1)
            task_start   = str(arow.get('開始日期', '') or '')
            task_end     = str(arow.get('結束日期', '') or '')
            date_info    = f"{task_start} ～ {task_end}" if task_start else ""
            task_status  = str(arow.get('狀態', '進行中') or '')
            task_q_ids   = str(arow.get('題目ID清單', '') or '')
            # 預設值（避免任何路徑沒有賦值）
            done_cnt, all_done, my_done = 0, False, set()
            pending_ids, _start_idx_fwd, _is_practice = set(), 0, False
            # 過濾掉 nan 和空白
            raw_ids   = [q.strip() for q in task_q_ids.split(',') if q.strip() and q.strip() != 'nan']
            q_ids_set = set(raw_ids)  # 用於比對（set，去重）
            # q_ids_all 包含所有格式（有V_/無V_），用於 logs 比對
            q_ids_all = set()
            for qid in raw_ids:
                q_ids_all.add(qid)
                if qid.startswith('V_'):
                    q_ids_all.add(qid[2:])   # 無前綴版本
                elif not any(qid.startswith(p) for p in ('R_','RM_','LP_','LS_')):
                    q_ids_all.add(f"V_{qid}")  # 加 V_ 前綴版本
            task_q_count = len(raw_ids) if raw_ids else max(int(float(str(arow.get('題目數', 0) or 0))), 0)

            # 計算個人完成進度（混合任務：一般題答對 + 朗讀題有紀錄）
            task_type       = str(arow.get('類型', '一般'))
            is_race_task    = task_type == '競賽'
            is_reading_task = task_type == '朗讀'
            is_vocab_task   = task_type == '單字'
            is_mixed_task   = task_type == '混合'

            # 競賽模式 flag
            is_race_task    = task_type == '競賽'
            is_rm_task      = task_type == '閱讀單句'
            is_lp_task      = task_type == '聽力音標'
            is_ls_task      = task_type == '聽力重組'

            if q_ids_set and not is_race_task:
                try:
                    # 用快取的 df_l，依任務編號篩選
                    task_id_key_check = arow.get('任務編號', '') or ''
                    if not task_id_key_check and task_name:
                        import re as _re_tid2
                        _m2 = _re_tid2.search(r'\[T(\d+)\]', task_name)
                        if _m2:
                            task_id_key_check = 'T' + _m2.group(1)
                    if df_l.empty:
                        df_l = _get_df_l()
                    if not df_l.empty:
                        _stu_all = df_l[df_l['姓名'] == user_name]
                        # 用題目ID比對（最可靠，相容舊資料沒有任務名稱的 logs）
                        if q_ids_all and '題目ID' in _stu_all.columns:
                            stu_logs_check = _stu_all[_stu_all['題目ID'].isin(q_ids_all)]
                            # 再加上任務名稱比對的結果（取聯集）
                            if task_id_key_check and '任務名稱' in _stu_all.columns:
                                _by_name = _stu_all[_stu_all['任務名稱'].fillna('') == task_id_key_check]
                                if not _by_name.empty:
                                    stu_logs_check = pd.concat([stu_logs_check, _by_name]).drop_duplicates()
                        elif task_id_key_check and '任務名稱' in _stu_all.columns:
                            stu_logs_check = _stu_all[_stu_all['任務名稱'].fillna('') == task_id_key_check]
                        else:
                            stu_logs_check = _stu_all
                        my_correct = set(stu_logs_check[
                            stu_logs_check['結果'].fillna('').str.contains('✅', na=False) &
                            ~stu_logs_check['結果'].fillna('').str.contains('練習', na=False)
                        ]['題目ID'].tolist())
                        my_reading = set(stu_logs_check[
                            stu_logs_check['結果'].fillna('').str.contains('🎤|朗讀|分', na=False) &
                            ~stu_logs_check['結果'].fillna('').str.contains('練習', na=False)
                        ]['題目ID'].tolist())
                        # 已作答 = 有任何非講解紀錄（與複習模式一致）
                        my_answered = set(stu_logs_check[
                            ~stu_logs_check['結果'].fillna('').str.contains('📖|練習', na=False)
                        ]['題目ID'].tolist())
                    else:
                        my_correct, my_reading, my_answered = set(), set(), set()
                    my_done  = my_correct | my_reading | my_answered
                    done_cnt = len(q_ids_set & my_done)  # 用 q_ids_set（原始格式）避免重複計算
                    all_done = done_cnt >= len(q_ids_set)
                except:
                    my_done = set()
                    done_cnt, all_done = 0, False
            else:
                my_done = set()
                done_cnt, all_done = 0, False

            # 競賽任務：不計算完成數，直接顯示開始按鈕
            if is_race_task:
                done_cnt, all_done = 0, False
            status_icon = "🏆" if is_race_task else ("🟢" if all_done else ("🎤" if is_reading_task else "🔴"))
            if is_race_task:
                with st.expander(f"{status_icon} {task_name}　{date_info}", expanded=True):
                    _is_practice = False
                    btn_key = f"start_task_{_task_idx}_{task_name[:20]}"
                    if st.button("🏆 開始競賽", key=btn_key, type="primary", use_container_width=True):
                        import random as _rr
                        _race_records = []

                        def _race_qid(r, pfx=""):
                            return f"{pfx}{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}"

                        # 重組 + 單選（合併去重）
                        _rq2 = pd.concat([df_q, df_mcq], ignore_index=True) if not df_mcq.empty else df_q.copy()
                        if not _rq2.empty:
                            _rq2 = _rq2.copy()
                            _rq2['題目ID'] = _rq2.apply(lambda r: _race_qid(r), axis=1)
                            _rq2 = _rq2.drop_duplicates(subset='題目ID', keep='last')
                            _m = _rq2[_rq2['題目ID'].isin(q_ids_set)].copy()
                            if not _m.empty: _race_records.extend(_m.to_dict('records'))
                        # 朗讀
                        if not df_r.empty:
                            _rr2 = df_r.copy()
                            _rr2['題目ID'] = _rr2.apply(lambda r: _race_qid(r, "R_"), axis=1)
                            _rr2['_type'] = 'reading'
                            _m = _rr2[_rr2['題目ID'].isin(q_ids_set)].copy()
                            if not _m.empty: _race_records.extend(_m.to_dict('records'))
                        # 拼單字
                        if not df_v.empty:
                            _rv2 = df_v.copy()
                            _rv2['題目ID'] = _rv2.apply(lambda r: _race_qid(r, "V_"), axis=1)
                            _rv2['_type'] = 'vocab'
                            _m = _rv2[_rv2['題目ID'].isin(q_ids_set)].copy()
                            if not _m.empty: _race_records.extend(_m.to_dict('records'))
                        # 閱讀單句
                        if not df_rm.empty:
                            _rrm2 = df_rm.copy()
                            _rrm2['題目ID'] = _rrm2.apply(lambda r: _race_qid(r, "RM_"), axis=1)
                            _rrm2['_type'] = 'reading_mcq'
                            _m = _rrm2[_rrm2['題目ID'].isin(q_ids_set)].copy()
                            if not _m.empty: _race_records.extend(_m.to_dict('records'))
                        # 聽力音標
                        if not df_lp.empty:
                            _rlp2 = df_lp.copy()
                            _rlp2['題目ID'] = _rlp2.apply(_get_lp_qid, axis=1)
                            _rlp2['_type'] = 'listen_phon'
                            _m = _rlp2[_rlp2['題目ID'].isin(q_ids_set)].copy()
                            if not _m.empty: _race_records.extend(_m.to_dict('records'))
                        # 聽力句子重組
                        if not df_ls.empty:
                            _rls2 = df_ls.copy()
                            _rls2['題目ID'] = _rls2.apply(_get_ls_qid, axis=1)
                            _rls2['_type'] = 'listen_sent'
                            _m = _rls2[_rls2['題目ID'].isin(q_ids_set)].copy()
                            if not _m.empty: _race_records.extend(_m.to_dict('records'))
                        if not _race_records:
                            st.error("找不到題目，請確認任務設定")
                        else:
                            _rr.shuffle(_race_records)
                            # 清除所有舊答題狀態
                            _keys_to_clear = [k for k in list(st.session_state.keys()) if
                                k.startswith("mcq_order_") or k.startswith("mcq_written_") or
                                k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or
                                k.startswith("vocab_used_") or k.startswith("rm_order_") or
                                k.startswith("audio_scored_") or k.startswith("vocab_tts_") or
                                k.startswith("ls_ans_") or k.startswith("ls_shuf_")]
                            for _rk in _keys_to_clear:
                                del st.session_state[_rk]
                            st.session_state.update({
                                "quiz_list":     _race_records,
                                "q_idx":         0,
                                "quiz_loaded":   True,
                                "answered_count": 0,
                                "current_task_name": task_id_key,
                                "practice_mode": False,
                                "race_mode":     True,
                                "race_start_time": __import__("time").time(),
                                "race_attempt":  st.session_state.get("race_attempt", 0) + 1,
                                "show_analysis": False,
                                "current_res":   "",
                                "ans": [], "used_history": [], "shuf": [],
                                "tts_student":   None,
                                "stt_text_shown": "",
                            })
                            st.rerun()
            else:
                with st.expander(f"{status_icon} {task_name}　{date_info}　{done_cnt}/{task_q_count} 題完成", expanded=True):
                    # 任務說明
                    task_desc_text = str(arow.get('任務說明') or '').strip()
                    if task_desc_text and task_desc_text not in ('nan', 'None', ''):
                        st.info(f"📋 {task_desc_text}")

                    pc1, pc2 = st.columns(2)
                    pc1.metric("總題數", task_q_count)
                    pc2.metric("已完成", done_cnt)

                    if all_done and not st.session_state.get(f"_retry_started_{task_id_key}"):
                        st.success("🎉 此任務已全部完成！")

                        # 再次測驗按鈕 → 展開模式選擇
                        _retry_key = f"show_retry_opts_{_task_idx}"
                        if st.button("🔁 再次測驗", key=f"retry_task_{_task_idx}", use_container_width=True, type="primary"):
                            st.session_state[_retry_key] = True

                        if st.session_state.get(_retry_key):
                            st.markdown("**選擇答題方式：**")
                            _retry_mode = st.radio(
                                "答題方式",
                                ["📌 測驗-繼續未完成部分", "🔢 測驗-從第幾題開始", "⚡ 快速答題", "🏋️ 練習模式", "🎤 跟著唸"],
                                horizontal=False,
                                key=f"retry_mode_{_task_idx}"
                            )
                            _rc3 = st.columns([3, 1])[1]
                            retry_start = _rc3.number_input(
                                "從第幾題", min_value=1, max_value=task_q_count, value=1,
                                key=f"retry_start_{_task_idx}"
                            ) if _retry_mode != "📌 測驗-繼續未完成部分" else 1

                            _is_practice = (_retry_mode == "🏋️ 練習模式")
                            _is_quick    = (_retry_mode == "⚡ 快速答題")
                            _is_shadow   = (_retry_mode == "🎤 跟著唸")
                            _do_retry    = False
                            if st.button(f"🚀 開始{_retry_mode}", key=f"retry_go_{_task_idx}", type="primary", use_container_width=True):
                                _do_retry = True
                                st.session_state.pop(_retry_key, None)
                                # 清除完成記錄，避免重新顯示完成畫面
                                st.session_state[f"_retry_started_{task_id_key}"] = True
                        else:
                            _do_retry, _is_practice, _is_quick, retry_start = False, False, False, 1

                        if _do_retry:
                            _start_idx = max(0, int(retry_start) - 1)
                            if is_reading_task:
                                df_r2 = df_r.copy()
                                if '題目ID' not in df_r2.columns:
                                    df_r2['題目ID'] = df_r2.apply(
                                        lambda r: f"R_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                                    )
                                retry_r = df_r2[df_r2['題目ID'].isin(q_ids_set)].copy()
                                if not retry_r.empty:
                                    records = retry_r.to_dict('records')
                                    for rec in records:
                                        rec['_type'] = 'reading'
                                    for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_") or k.startswith("mcq_order_") or k.startswith("rm_order_") or k.startswith("mcq_written_")]:
                                        del st.session_state[_k]
                                    st.session_state.update({
                                        "quiz_list": records,
                                        "q_idx": min(_start_idx, len(records)-1),
                                        "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                        "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                    })
                                    st.rerun()
                            else:
                                _all_dfs = []
                                df_q2 = pd.concat([df_q, df_mcq], ignore_index=True) if not df_mcq.empty else df_q.copy()
                                df_q2['題目ID'] = df_q2.apply(lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1)
                                df_q2 = df_q2.drop_duplicates(subset='題目ID', keep='last')
                                df_q2['題目ID'] = df_q2.apply(lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1)
                                rq = df_q2[df_q2['題目ID'].isin(q_ids_set)].copy()
                                if not rq.empty: _all_dfs.append(rq)
                                if not df_v.empty:
                                    dv2 = df_v.copy()
                                    dv2['單元'] = dv2.get('單元', '拼單字')
                                    dv2['題目ID'] = dv2.apply(lambda r: f"V_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1)
                                    rv = dv2[dv2['題目ID'].isin(q_ids_set)].copy()
                                    if not rv.empty:
                                        vocab_cfg_str2 = str(arow.get('單字設定', '') or '')
                                        vcfg2 = vocab_cfg_str2.split('|') if vocab_cfg_str2 else []
                                        rv['_type'] = 'vocab'
                                        rv['_vocab_mode']  = (vcfg2[0] if len(vcfg2)>0 else '自選').replace('學生自選','自選')
                                        rv['_vocab_timer'] = int(vcfg2[1]) if len(vcfg2)>1 else 60
                                        rv['_vocab_extra'] = int(vcfg2[2]) if len(vcfg2)>2 else 0
                                        _all_dfs.append(rv)
                                if not df_rm.empty:
                                    drm2 = df_rm.copy()
                                    drm2['題目ID'] = drm2.apply(lambda r: f"RM_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1)
                                    rrm = drm2[drm2['題目ID'].isin(q_ids_set)].copy()
                                    if not rrm.empty:
                                        rrm['_type'] = 'reading_mcq'
                                        _all_dfs.append(rrm)
                                # 聽力音標
                                if not df_lp.empty:
                                    dlp2 = df_lp.copy()
                                    dlp2['題目ID'] = dlp2.apply(_get_lp_qid, axis=1)
                                    dlp2['_type']  = 'listen_phon'
                                    rlp = dlp2[dlp2['題目ID'].isin(q_ids_set)].copy()
                                    if not rlp.empty:
                                        import random as _rand_lp
                                        lp_recs = []
                                        for _, lp_row in rlp.iterrows():
                                            lp_d = lp_row.to_dict()
                                            distractors = _get_lp_distractors(df_lp, lp_row, n=3)
                                            opts = distractors + [lp_row.to_dict()]
                                            _rand_lp.shuffle(opts)
                                            opts = opts[:4]
                                            correct_idx = next((i for i, o in enumerate(opts) if o.get('KK符號') == lp_d.get('KK符號')), 0)
                                            lp_d['_lp_opts']        = opts
                                            lp_d['_lp_correct_opt'] = ["A","B","C","D"][correct_idx]
                                            lp_recs.append(lp_d)
                                        _all_dfs.append(pd.DataFrame(lp_recs))
                                # 聽力句子重組
                                if not df_ls.empty:
                                    dls2 = df_ls.copy()
                                    dls2['題目ID'] = dls2.apply(_get_ls_qid, axis=1)
                                    dls2['_type']  = 'listen_sent'
                                    rls = dls2[dls2['題目ID'].isin(q_ids_set)].copy()
                                    if not rls.empty:
                                        rls['_ls_words'] = rls['聽力重組英文答案'].apply(_ls_split_words)
                                        _all_dfs.append(rls)
                                # 純單字任務
                                if is_vocab_task and not df_v.empty:
                                    dv_r = df_v.copy()
                                    dv_r['題目ID'] = dv_r.apply(lambda r: f"V_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1)
                                    rv_r = dv_r[dv_r['題目ID'].isin(q_ids_set)].copy()
                                    if not rv_r.empty:
                                        vocab_cfg_str3 = str(arow.get('單字設定', '') or '')
                                        vcfg3 = vocab_cfg_str3.split('|') if vocab_cfg_str3 else []
                                        rv_r['_type']        = 'vocab'
                                        rv_r['_vocab_mode']  = (vcfg3[0] if len(vcfg3)>0 else '自選').replace('學生自選','自選')
                                        rv_r['_vocab_timer'] = int(vcfg3[1]) if len(vcfg3)>1 else 60
                                        rv_r['_vocab_extra'] = int(vcfg3[2]) if len(vcfg3)>2 else 0
                                        _all_dfs.append(rv_r)
                                # 純聽力音標任務
                                if is_lp_task and not df_lp.empty:
                                    dlp_r = df_lp.copy()
                                    dlp_r['題目ID'] = dlp_r.apply(_get_lp_qid, axis=1)
                                    rlp_r = dlp_r[dlp_r['題目ID'].isin(q_ids_set)].copy()
                                    if not rlp_r.empty:
                                        import random as _rand_lp_r
                                        lp_recs_r = []
                                        for _, lp_row_r in rlp_r.iterrows():
                                            lp_d_r = lp_row_r.to_dict()
                                            dist_r  = _get_lp_distractors(df_lp, lp_row_r, n=3)
                                            opts_r  = dist_r + [lp_row_r.to_dict()]
                                            _rand_lp_r.shuffle(opts_r)
                                            opts_r  = opts_r[:4]
                                            cidx_r  = next((i for i, o in enumerate(opts_r) if o.get('KK符號') == lp_d_r.get('KK符號')), 0)
                                            lp_d_r['_lp_opts']        = opts_r
                                            lp_d_r['_lp_correct_opt'] = ["A","B","C","D"][cidx_r]
                                            lp_d_r['_type']           = 'listen_phon'
                                            lp_recs_r.append(lp_d_r)
                                        _all_dfs.append(pd.DataFrame(lp_recs_r))
                                if _all_dfs:
                                    retry_all = pd.concat(_all_dfs, ignore_index=True)
                                    records   = retry_all.to_dict('records')
                                    for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_") or k.startswith("mcq_order_") or k.startswith("rm_order_") or k.startswith("mcq_written_")]:
                                        del st.session_state[_k]
                                    st.session_state.update({
                                        "quiz_list": records,
                                        "q_idx": min(_start_idx, len(records)-1),
                                        "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                        "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                    })
                                    st.rerun()
                    else:
                        task_content = str(arow.get('內容', ''))
                        parts        = [p.strip() for p in task_content.split('|')]
                        can_preload  = len(parts) == 5
                        remaining    = task_q_count - done_cnt

                        # 三個選項（含練習模式）- 競賽任務不顯示
                        # 三個選項（含練習模式）- 競賽任務不顯示
                        _mode = "📌 測驗-繼續未完成部分"  # default
                        _start_from = 1
                        if not is_race_task:
                            # 跟著唸只適用於重組/拼單字題型
                            _shadow_ok = is_vocab_task or task_type in ("一般", "混合", "")
                            _mode_opts = ["📌 測驗-繼續未完成部分", "🔢 測驗-從第幾題開始", "⚡ 快速答題", "🏋️ 練習模式"]
                            if _shadow_ok:
                                _mode_opts.append("🎤 跟著唸")
                            _mode = st.radio(
                                "練習方式",
                                _mode_opts,
                                horizontal=True,
                                key=f"start_mode_{_task_idx}"
                            )
                            if _mode in ("🔢 測驗-從第幾題開始", "🏋️ 練習模式", "⚡ 快速答題", "🎤 跟著唸"):
                                _start_from = st.number_input(
                                    "從第幾題（依任務原始題號）",
                                    min_value=1, max_value=task_q_count, value=1,
                                    key=f"start_from_{_task_idx}"
                                )
                                if _mode == "🏋️ 練習模式":
                                    st.caption("🏋️ 練習模式：可回上一題，作答紀錄標記為「練習」不列入正式記錄")
                                elif _mode == "⚡ 快速答題":
                                    st.caption("⚡ 快速答題：答完立即顯示對錯，自動跳下一題")
                                elif _mode == "🎤 跟著唸":
                                    st.caption("🎤 跟著唸：播放英文 TTS，可自行錄音練習，無需作答")

                        # 競賽模式任務：只顯示競賽按鈕，不顯示一般模式選項
                        pending_ids    = set()  # 預設空，按鈕按下才賦值
                        _start_idx_fwd = 0
                        if is_race_task:
                            _is_practice = False
                            btn_key = f"start_task_{_task_idx}_{task_name[:20]}"
                            if st.button("🏆 開始競賽", key=btn_key, type="primary", use_container_width=True):
                                pending_ids    = q_ids_set
                                _start_idx_fwd = 0
                                import random as _rr; _rr.shuffle(list(pending_ids))  # noqa
                        else:
                            _is_practice  = (_mode == "🏋️ 練習模式")
                            _is_quick     = (_mode == "⚡ 快速答題")
                            _is_shadow    = (_mode == "🎤 跟著唸")
                            btn_key = f"start_task_{_task_idx}_{task_name[:20]}"
                            label   = "📌 測驗-繼續未完成部分" if _mode == "📌 測驗-繼續未完成部分" else \
                                      (f"🏋️ 練習模式 從第 {_start_from} 題" if _is_practice else \
                                      (f"⚡ 快速答題 從第 {_start_from} 題" if _is_quick else \
                                      (f"🎤 跟著唸 從第 {_start_from} 題" if _is_shadow else \
                                       f"🔢 測驗-從第 {_start_from} 題開始")))
                            if st.button(f"🚀 {label}", key=btn_key, type="primary", use_container_width=True):
                                if _mode == "📌 測驗-繼續未完成部分":
                                    _start_idx_fwd = 0
                                    pending_ids = q_ids_set - my_done
                                    if not pending_ids:
                                        pending_ids = q_ids_set
                                else:
                                    _start_idx_fwd = max(0, int(_start_from) - 1)
                                    pending_ids = q_ids_set

                            if not hasattr(st.session_state, "_is_practice_defined"):
                                _is_practice = _is_practice if "_is_practice" in dir() else False

                            if pending_ids:  # 按鈕按下才載入
                              if is_reading_task:
                                  df_r2 = df_r.copy()
                                  if '題目ID' not in df_r2.columns:
                                      df_r2['題目ID'] = df_r2.apply(
                                          lambda r: f"R_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                                      )
                                  pending = df_r2[df_r2['題目ID'].isin(pending_ids)].copy()
                                  if not pending.empty:
                                      records = pending.to_dict('records')
                                      for r in records:
                                          r['_type'] = 'reading'
                                      # 清除所有舊的字母池，避免題目字母錯誤
                                      for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_") or k.startswith("mcq_order_") or k.startswith("rm_order_") or k.startswith("mcq_written_")]:
                                          del st.session_state[_k]
                                      st.session_state.update({
                                          "quiz_list": records,
                                          "q_idx": min(_start_idx_fwd, len(records)-1), "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                          "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                      })
                                      st.rerun()
  
                              elif is_vocab_task:
                                  # 純單字任務
                                  df_v2 = df_v.copy() if not df_v.empty else pd.DataFrame()
                                  if not df_v2.empty and '題目ID' not in df_v2.columns:
                                      df_v2['題目ID'] = df_v2.apply(
                                          lambda r: f"V_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                                      )
                                  pending = df_v2[df_v2['題目ID'].isin(
                                      {q for q in pending_ids if q.startswith('V_')} |
                                      {f"V_{q}" for q in pending_ids if not any(q.startswith(p) for p in ('V_','R_','RM_','LP_','LS_'))}
                                  )].copy() if not df_v2.empty else pd.DataFrame()
                                  if not pending.empty:
                                      vocab_cfg_str = str(arow.get('單字設定', '') or '')
                                      vcfg = vocab_cfg_str.split('|') if vocab_cfg_str else []
                                      v_mode_t  = vcfg[0] if len(vcfg) > 0 else '自選'
                                      if v_mode_t == '學生自選':
                                          v_mode_t = '自選'
                                      v_timer_t = int(vcfg[1]) if len(vcfg) > 1 else 60
                                      v_extra_t = int(vcfg[2]) if len(vcfg) > 2 else 0
                                      records = pending.to_dict('records')
                                      for rec in records:
                                          rec['_type']        = 'vocab'
                                          rec['_vocab_mode']  = v_mode_t
                                          rec['_vocab_timer'] = v_timer_t
                                          rec['_vocab_extra'] = v_extra_t
                                      # 清除所有舊的字母池，避免題目字母錯誤
                                      for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_") or k.startswith("mcq_order_") or k.startswith("rm_order_") or k.startswith("mcq_written_")]:
                                          del st.session_state[_k]
                                      st.session_state.update({
                                          "quiz_list": records,
                                          "q_idx": min(_start_idx_fwd, len(records)-1), "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                          "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                      })
                                      st.rerun()
  
                              elif is_rm_task:
                                  df_rm2 = df_rm.copy() if not df_rm.empty else pd.DataFrame()
                                  if not df_rm2.empty and '題目ID' not in df_rm2.columns:
                                      df_rm2['題目ID'] = df_rm2.apply(
                                          lambda r: f"RM_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                                      )
                                  pending = df_rm2[df_rm2['題目ID'].isin(pending_ids)].copy() if not df_rm2.empty else pd.DataFrame()
                                  if not pending.empty:
                                      records = pending.to_dict('records')
                                      for rec in records:
                                          rec['_type'] = 'reading_mcq'
                                      # 清除所有舊的字母池，避免題目字母錯誤
                                      for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_") or k.startswith("mcq_order_") or k.startswith("rm_order_") or k.startswith("mcq_written_")]:
                                          del st.session_state[_k]
                                      st.session_state.update({
                                          "quiz_list": records,
                                          "q_idx": min(_start_idx_fwd, len(records)-1), "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                          "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                      })
                                      st.rerun()
  
                              elif is_lp_task:
                                  if not df_lp.empty:
                                      dlp2 = df_lp.copy()
                                      dlp2['題目ID'] = dlp2.apply(_get_lp_qid, axis=1)
                                      pending_lp = dlp2[dlp2['題目ID'].isin(pending_ids)].copy()
                                      if not pending_lp.empty:
                                          import random as _rand_lp2
                                          lp_recs2 = []
                                          for _, lp_row in pending_lp.iterrows():
                                              lp_d = lp_row.to_dict()
                                              distractors = _get_lp_distractors(df_lp, lp_row, n=3)
                                              opts = distractors + [lp_row.to_dict()]
                                              _rand_lp2.shuffle(opts)
                                              opts = opts[:4]
                                              correct_idx = next((i for i, o in enumerate(opts) if o.get('KK符號') == lp_d.get('KK符號')), 0)
                                              lp_d['_lp_opts']        = opts
                                              lp_d['_lp_correct_opt'] = ["A","B","C","D"][correct_idx]
                                              lp_d['_type']           = 'listen_phon'
                                              lp_recs2.append(lp_d)
                                          import random as _rand_lp_final
                                          _rand_lp_final.shuffle(lp_recs2)
                                          records = lp_recs2
                                          # 預載第一題音檔
                                          if records:
                                              _f1 = records[min(_start_idx_fwd, len(records)-1)]
                                              _f1_num = str(_f1.get('總編號','')).strip()
                                              _f1_sym = str(_f1.get('KK符號','')).strip()
                                              _f1_qid = _f1.get('題目ID','')
                                              try:
                                                  _f1_fkey = f"{int(_f1_num):02d}-{_f1_sym}".lower()
                                              except:
                                                  _f1_fkey = f"{_f1_num}-{_f1_sym}".lower()
                                              _f1_cache = f"lp_audio_{min(_start_idx_fwd, len(records)-1)}_{_f1_qid}"
                                              if not st.session_state.get(_f1_cache):
                                                  try:
                                                      import requests as _req_f1, base64 as _b64_f1
                                                      _f1_idx = load_audio_file_index()
                                                      _f1_fid = _f1_idx.get(_f1_fkey, "")
                                                      if _f1_fid:
                                                          _f1_r = _req_f1.get(get_audio_url(_f1_fid), timeout=8)
                                                          if _f1_r.status_code == 200:
                                                              st.session_state[_f1_cache] = _b64_f1.b64encode(_f1_r.content).decode()
                                                  except:
                                                      pass
                                          for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_")]:
                                              del st.session_state[_k]
                                          st.session_state.update({
                                              "quiz_list": records,
                                              "q_idx": min(_start_idx_fwd, len(records)-1), "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                              "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                          })
                                          st.rerun()
                                      else:
                                          st.error("❌ 找不到任務題目（已全部完成或題目不存在）")
  
                              elif is_ls_task:
                                  if not df_ls.empty:
                                      dls_t = df_ls.copy()
                                      dls_t['題目ID'] = dls_t.apply(_get_ls_qid, axis=1)
                                      dls_t['_type']  = 'listen_sent'
                                      pending_ls = dls_t[dls_t['題目ID'].isin(pending_ids)].copy()
                                      if not pending_ls.empty:
                                          pending_ls['_ls_words'] = pending_ls['聽力重組英文答案'].apply(_ls_split_words)
                                          records = pending_ls.to_dict('records')
                                          for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_") or k.startswith("ls_ans_") or k.startswith("ls_used_") or k.startswith("ls_shuf_")]:
                                              del st.session_state[_k]
                                          st.session_state.update({
                                              "quiz_list": records,
                                              "q_idx": min(_start_idx_fwd, len(records)-1), "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                              "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                          })
                                          st.rerun()
  
                              elif is_mixed_task:
                                  df_q2 = pd.concat([df_q, df_mcq], ignore_index=True) if not df_mcq.empty else df_q.copy()
                                  df_q2['題目ID'] = df_q2.apply(lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1)
                                  df_q2 = df_q2.drop_duplicates(subset='題目ID', keep='last')
                                  df_q2['題目ID'] = df_q2.apply(
                                      lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1
                                  )
                                  df_r2 = df_r.copy() if not df_r.empty else pd.DataFrame()
                                  if not df_r2.empty and '題目ID' not in df_r2.columns:
                                      df_r2['題目ID'] = df_r2.apply(
                                          lambda r: f"R_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                                      )
                                  df_v2 = df_v.copy() if not df_v.empty else pd.DataFrame()
                                  if not df_v2.empty and '題目ID' not in df_v2.columns:
                                      df_v2['題目ID'] = df_v2.apply(
                                          lambda r: f"V_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                                      )
                                  df_rm2 = df_rm.copy() if not df_rm.empty else pd.DataFrame()
                                  if not df_rm2.empty and '題目ID' not in df_rm2.columns:
                                      df_rm2['題目ID'] = df_rm2.apply(
                                          lambda r: f"RM_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                                      )
                                  # 各題型只用對應格式比對（避免重複）
                                  _raw_v   = {q for q in pending_ids if q.startswith('V_')}
                                  _raw_r   = {q for q in pending_ids if q.startswith('R_') and not q.startswith('RM_')}
                                  _raw_rm  = {q for q in pending_ids if q.startswith('RM_')}
                                  _raw_lp  = {q for q in pending_ids if q.startswith('LP_')}
                                  _raw_ls  = {q for q in pending_ids if q.startswith('LS_')}
                                  _raw_q   = {q for q in pending_ids if not any(q.startswith(p) for p in ('V_','R_','RM_','LP_','LS_'))}
                                  # V_ 的無前綴版本不給 _q 使用
                                  _v_bare  = {q[2:] for q in _raw_v}  # V_xxx → xxx
                                  _q_ids   = _raw_q - _v_bare  # 排除拼單字的無前綴版本
                                  _v_ids   = _raw_v | {f"V_{q}" for q in _raw_q & _v_bare}
                                  _r_ids   = _raw_r | {f"R_{q}" for q in _raw_q if not q.startswith('R_')}
                                  _rm_ids  = _raw_rm | {f"RM_{q}" for q in _raw_q if not q.startswith('RM_')}
                                  pending_q  = df_q2[df_q2['題目ID'].isin(_q_ids)].copy()
                                  pending_r  = df_r2[df_r2['題目ID'].isin(_r_ids)].copy() if not df_r2.empty else pd.DataFrame()
                                  pending_v  = df_v2[df_v2['題目ID'].isin(_v_ids)].copy() if not df_v2.empty else pd.DataFrame()
                                  pending_rm = df_rm2[df_rm2['題目ID'].isin(_rm_ids)].copy() if not df_rm2.empty else pd.DataFrame()
                                  if not pending_r.empty:
                                      pending_r['_type'] = 'reading'
                                  if not pending_rm.empty:
                                      pending_rm['_type'] = 'reading_mcq'
                                  if not pending_v.empty:
                                      vocab_cfg_str = str(arow.get('單字設定', '') or '')
                                      vcfg = vocab_cfg_str.split('|') if vocab_cfg_str else []
                                      v_mode_mixed = vcfg[0] if len(vcfg) > 0 else '自選'
                                      if v_mode_mixed == '學生自選':
                                          v_mode_mixed = '自選'
                                      pending_v['_type']        = 'vocab'
                                      pending_v['_vocab_mode']  = v_mode_mixed
                                      pending_v['_vocab_timer'] = int(vcfg[1]) if len(vcfg) > 1 else 60
                                      pending_v['_vocab_extra'] = int(vcfg[2]) if len(vcfg) > 2 else 0
                                  # 聽力音標（混合任務）
                                  pending_lp_m = pd.DataFrame()
                                  if not df_lp.empty:
                                      dlp_m = df_lp.copy()
                                      dlp_m['題目ID'] = dlp_m.apply(_get_lp_qid, axis=1)
                                      _plp = dlp_m[dlp_m['題目ID'].isin(pending_ids)].copy()
                                      if not _plp.empty:
                                          import random as _rand_lpm
                                          _lp_recs_m = []
                                          for _, _lr in _plp.iterrows():
                                              _ld = _lr.to_dict()
                                              _dis = _get_lp_distractors(df_lp, _lr, n=3)
                                              _opts = _dis + [_lr.to_dict()]
                                              _rand_lpm.shuffle(_opts)
                                              _opts = _opts[:4]
                                              _ci = next((i for i, o in enumerate(_opts) if o.get('KK符號') == _ld.get('KK符號')), 0)
                                              _ld['_lp_opts'] = _opts
                                              _ld['_lp_correct_opt'] = ["A","B","C","D"][_ci]
                                              _ld['_type'] = 'listen_phon'
                                              _lp_recs_m.append(_ld)
                                          pending_lp_m = pd.DataFrame(_lp_recs_m)
                                  # 聽力句子重組（混合任務）
                                  pending_ls_m = pd.DataFrame()
                                  if not df_ls.empty:
                                      dls_m = df_ls.copy()
                                      dls_m['題目ID'] = dls_m.apply(_get_ls_qid, axis=1)
                                      dls_m['_type'] = 'listen_sent'
                                      _pls = dls_m[dls_m['題目ID'].isin(pending_ids)].copy()
                                      if not _pls.empty:
                                          _pls['_ls_words'] = _pls['聽力重組英文答案'].apply(_ls_split_words)
                                          pending_ls_m = _pls
                                  pending = pd.concat([pending_q, pending_r, pending_v, pending_rm, pending_lp_m, pending_ls_m], ignore_index=True)
                                  if not pending.empty:
                                      # 清除所有舊的字母池
                                      for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_") or k.startswith("mcq_order_") or k.startswith("rm_order_") or k.startswith("mcq_written_")]:
                                          del st.session_state[_k]
                                      st.session_state.update({
                                          "quiz_list": pending.to_dict('records'),
                                          "q_idx": min(_start_idx_fwd, len(pending)-1), "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                          "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                      })
                                      st.rerun()
  
                              elif (can_preload or q_ids_all) and pending_ids:
                                  # 直接從 df_q 取出未完成題目載入（優先用題目ID清單）
                                df_q2 = pd.concat([df_q, df_mcq], ignore_index=True) if not df_mcq.empty else df_q.copy()
                                df_q2['題目ID'] = df_q2.apply(lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1)
                                df_q2 = df_q2.drop_duplicates(subset='題目ID', keep='last')
                                df_q2['題目ID'] = df_q2.apply(
                                    lambda r: f"{r['版本']}_{r['年度']}_{r['冊編號']}_{r['單元']}_{r['課編號']}_{r['句編號']}", axis=1
                                )
                                pending_q = df_q2[df_q2['題目ID'].isin(pending_ids)].copy()
                                if not pending_q.empty:
                                    # 依句編號排序（不隨機）
                                    if '句編號' in pending_q.columns:
                                        pending_q['_sn'] = pd.to_numeric(pending_q['句編號'], errors='coerce').fillna(0)
                                        pending_q = pending_q.sort_values('_sn').drop(columns=['_sn'])
                                    records = pending_q.to_dict('records')
                                    for _k in [k for k in list(st.session_state.keys()) if k.startswith("vocab_pool_") or k.startswith("vocab_ans_") or k.startswith("vocab_used_") or k.startswith("mcq_order_") or k.startswith("rm_order_") or k.startswith("mcq_written_")]:
                                        del st.session_state[_k]
                                    st.session_state.update({
                                        "quiz_list": records,
                                        "q_idx": min(_start_idx_fwd, len(records)-1), "quiz_loaded": True, "answered_count": 0, "_timers_cleared": False, "current_task_name": task_id_key, "practice_mode": _is_practice, "quick_mode": locals().get("_is_quick", False), "shadow_mode": locals().get("_is_shadow", False), "race_mode": is_race_task if "is_race_task" in dir() else False, "race_start_time": __import__("time").time() if (is_race_task if "is_race_task" in dir() else False) else None,
                                        "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None
                                    })
                                    st.rerun()
                                else:
                                    st.error(f"❌ 找不到任務題目（已全部完成或題目不存在）")


        st.divider()

    else:
        st.info("目前沒有指派任務。")
        with st.expander("🔍 任務篩選除錯（點開查看）", expanded=False):
            for d in debug_info:
                st.caption(d)
            if not debug_info:
                st.caption("assignments 資料表為空或無法讀取")

    # 除錯：讓管理員看到原始 assignments 資料
    if not df_a.empty and is_admin(st.session_state.group_id):
        with st.expander("🔍 除錯：assignments 原始資料（僅管理員可見）", expanded=False):
            st.dataframe(df_a, use_container_width=True)
            st.write(f"今日：{today_dt} | 學生：{user_name} | 共 {len(my_tasks)} 個有效任務")

    # ══════════════════════════════════════════════════════════════════════
    # 原本的自由練習區（盒子 C）- 前三個 tab 暫時隱藏
    # ══════════════════════════════════════════════════════════════════════

    st.subheader("📖 復習模式")

    user_name = st.session_state.user_name

    rv_filter = st.radio("篩選方式", ["📋 依任務", "⚙️ 依範圍"], horizontal=True, key="rv_filter")
    rv_q_ids     = None
    rv_task_id   = None  # 任務編號，用來篩選 logs

    if rv_filter == "📋 依任務":
        if not df_a.empty and '任務名稱' in df_a.columns:
            import re as _re_rv
            user_group = st.session_state.group_id
            df_a_rv = df_a[df_a.get('狀態', pd.Series(dtype=str)).fillna('') != '已刪除'].copy()
            # 只顯示新格式任務
            df_a_rv = df_a_rv[df_a_rv['任務名稱'].apply(
                lambda n: bool(_re_rv.search(r'\[T\d+\]', str(n)))
            )]
            if '對象班級' in df_a_rv.columns:
                df_a_rv = df_a_rv[df_a_rv['對象班級'].apply(
                    lambda v: user_group in [g.strip() for g in str(v).split(',')]
                )]
            task_opts   = ["（請選擇任務）"] + _sort_task_names(df_a_rv['任務名稱'].tolist())
            sel_rv_task = st.selectbox("選擇任務", task_opts, key="rv_task")
            if sel_rv_task != "（請選擇任務）":
                task_row = df_a_rv[df_a_rv['任務名稱'] == sel_rv_task].iloc[0]
                ids_str  = str(task_row.get('題目ID清單', '') or '')
                rv_q_ids   = set([q.strip() for q in ids_str.split(',') if q.strip() and q.strip() != 'nan'])
                rv_task_id = str(task_row.get('任務編號', '') or '')
                # 若任務編號欄位空白，從任務名稱提取
                if not rv_task_id:
                    import re as _re_rvtid
                    _m3 = _re_rvtid.search(r'\[T(\d+)\]', sel_rv_task)
                    if _m3:
                        rv_task_id = 'T' + _m3.group(1)
                st.info(f"📋 共 {len(rv_q_ids)} 題")
        else:
            st.info("目前沒有指派任務。")

    else:
        rc1 = st.columns(4)
        # 合併所有題庫的版本/年度/冊/課選項
        _df_all_q = pd.concat([df for df in [df_q, df_mcq, df_r, df_v, df_rm] if not df.empty and '版本' in df.columns], ignore_index=True)
        rv_v_opts = sorted(_df_all_q['版本'].unique().tolist()) if not _df_all_q.empty else []
        rv_v = rc1[0].selectbox("版本", rv_v_opts, key="rv_v") if rv_v_opts else None
        _rv_v_src = _df_all_q[_df_all_q['版本'] == rv_v] if rv_v else pd.DataFrame()
        rv_y_opts = sorted(_rv_v_src['年度'].unique().tolist()) if not _rv_v_src.empty else []
        rv_y = rc1[1].selectbox("年度", rv_y_opts, key="rv_y") if rv_y_opts else None
        _rv_y_src = _rv_v_src[_rv_v_src['年度'] == rv_y] if rv_y else pd.DataFrame()
        rv_b_opts = sorted(_rv_y_src['冊編號'].unique().tolist()) if not _rv_y_src.empty else []
        rv_b = rc1[2].selectbox("冊別", rv_b_opts, key="rv_b") if rv_b_opts else None
        _rv_b_src = _rv_y_src[_rv_y_src['冊編號'] == rv_b] if rv_b else pd.DataFrame()
        rv_l_opts = sorted(_rv_b_src['課編號'].unique().tolist()) if not _rv_b_src.empty else []
        rv_l = rc1[3].selectbox("課次", rv_l_opts, key="rv_l") if rv_l_opts else None
        rv_u = None  # 依範圍模式不用單元篩選

    rv_scope = st.radio("顯示範圍", ["📚 全部題目", "✏️ 已經答題", "❌ 只看錯題", "❓ 只看未作答", "🔄 複習次數少的優先"], horizontal=True, key="rv_scope")

    if st.button("📖 開始復習", type="primary", use_container_width=True, key="rv_start"):
        try:
            df_l = _get_df_l()  # 懶載入 logs
            if not df_l.empty:
                my_logs = df_l[df_l['姓名'] == user_name].copy()
                # 不用任務名稱篩選，改用題目ID比對
                # （因為舊版 logs 沒有寫入任務名稱）
                if rv_filter == "📋 依任務" and rv_q_ids and '題目ID' in my_logs.columns:
                    my_logs = my_logs[
                        my_logs['題目ID'].isin(rv_q_ids) |
                        my_logs['任務名稱'].fillna('').eq(rv_task_id)
                    ]
            else:
                my_logs = pd.DataFrame()
        except:
            df_l = _get_df_l()
            my_logs = df_l[df_l['姓名'] == user_name].copy() if not df_l.empty and '姓名' in df_l.columns else pd.DataFrame()

        def _get_qid(r, prefix=""):
            return f"{prefix}{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}"

        def _match_ids(df_src, id_set, prefix="", extra_prefix="V_"):
            """同時比對有無前綴的題目ID"""
            d = df_src.copy()
            d['_qid']  = d.apply(lambda r: _get_qid(r, prefix), axis=1)
            d['_qidv'] = d.apply(lambda r: _get_qid(r, extra_prefix), axis=1)
            matched = d[d['_qid'].isin(id_set) | d['_qidv'].isin(id_set)].copy()
            if not matched.empty:
                matched['題目ID'] = matched.apply(
                    lambda r: r['_qidv'] if r['_qidv'] in id_set else r['_qid'], axis=1
                )
            matched = matched.drop(columns=['_qid','_qidv'], errors='ignore')
            return matched

        all_items = []

        if rv_filter == "📋 依任務" and rv_q_ids:
            # 先從各題庫比對
            if not df_q.empty:
                matched = _match_ids(df_q, rv_q_ids)
                if not matched.empty:
                    all_items.append(matched)
            if not df_mcq.empty:
                matched_m = _match_ids(df_mcq, rv_q_ids)
                # 若比對數量不足，嘗試用單元+課編號+句編號做模糊比對
                if len(matched_m) < len(rv_q_ids) * 0.5:
                    _rv_short = set()
                    for _tid in rv_q_ids:
                        _parts = _tid.split('_')
                        if len(_parts) >= 3:
                            _rv_short.add('_'.join(_parts[-3:]))
                    _mcq2 = df_mcq.copy()
                    _mcq2['_short_id'] = _mcq2.apply(
                        lambda r: f"{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1
                    )
                    _fallback = _mcq2[_mcq2['_short_id'].isin(_rv_short)].copy()
                    if len(_fallback) > len(matched_m):
                        _sample_tid = list(rv_q_ids)[0]
                        _parts0 = _sample_tid.split('_')
                        _ver0 = _parts0[0] if _parts0 else ''
                        _yr0  = _parts0[1] if len(_parts0) > 1 else ''
                        _bk0  = _parts0[2] if len(_parts0) > 2 else ''
                        _fallback['題目ID'] = _fallback.apply(
                            lambda r: f"{_ver0}_{_yr0}_{_bk0}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}",
                            axis=1
                        )
                        _fallback = _fallback.drop(columns=['_short_id'], errors='ignore')
                        matched_m = _fallback
                if not matched_m.empty:
                    all_items.append(matched_m)
            if not df_v.empty:
                uc = '單元' if '單元' in df_v.columns else None
                dv = df_v.copy()
                if uc is None:
                    dv['單元'] = '拼單字'
                mv = _match_ids(dv, rv_q_ids, extra_prefix="V_")
                if not mv.empty:
                    mv['_type'] = 'vocab'
                    all_items.append(mv)
            if not df_r.empty:
                dr = df_r.copy()
                dr['題目ID'] = dr.apply(lambda r: f"R_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1)
                mr = dr[dr['題目ID'].isin(rv_q_ids)].copy()
                if not mr.empty:
                    mr['_type'] = 'reading'
                    all_items.append(mr)
            if not df_rm.empty:
                drm = df_rm.copy()
                drm['題目ID'] = drm.apply(lambda r: f"RM_{r.get('版本','')}_{r.get('年度','')}_{r.get('冊編號','')}_{r.get('單元','')}_{r.get('課編號','')}_{r.get('句編號','')}", axis=1)
                mrm = drm[drm['題目ID'].isin(rv_q_ids)].copy()
                if not mrm.empty:
                    mrm['_type'] = 'reading_mcq'
                    all_items.append(mrm)
            # 聽力音標
            if not df_lp.empty:
                dlp_rv = df_lp.copy()
                dlp_rv['題目ID'] = dlp_rv.apply(_get_lp_qid, axis=1)
                dlp_rv['_type']  = 'listen_phon'
                mlp = dlp_rv[dlp_rv['題目ID'].isin(rv_q_ids)].copy()
                if not mlp.empty:
                    all_items.append(mlp)
            # 聽力句子重組
            if not df_ls.empty:
                dls_rv = df_ls.copy()
                dls_rv['題目ID'] = dls_rv.apply(_get_ls_qid, axis=1)
                dls_rv['_type']  = 'listen_sent'
                mls = dls_rv[dls_rv['題目ID'].isin(rv_q_ids)].copy()
                if not mls.empty:
                    all_items.append(mls)

            # 若題庫找不到，改用 logs 裡的題目ID直接建立簡易題目列表
            if not all_items and not my_logs.empty:
                matched_logs = my_logs[
                    my_logs['題目ID'].isin(rv_q_ids) &
                    (~my_logs['結果'].str.contains('📖', na=False))
                ].copy()
                if not matched_logs.empty:
                    # 用 logs 裡的唯一題目ID建立簡易題目列表
                    unique_qids = matched_logs.drop_duplicates('題目ID')[['題目ID']].copy()
                    unique_qids['題目'] = unique_qids['題目ID']  # 暫用 ID 作為題目顯示
                    all_items.append(unique_qids)
        elif rv_filter == "⚙️ 依範圍" and rv_v and rv_l:
            # 重組題
            dq = df_q[
                (df_q['版本'] == rv_v) & (df_q['單元'] == rv_u) &
                (df_q['年度'] == rv_y) & (df_q['冊編號'] == rv_b) &
                (df_q['課編號'] == rv_l)
            ].copy()
            if not dq.empty:
                dq['題目ID'] = dq.apply(lambda r: _get_qid(r), axis=1)
                all_items.append(dq)
            # 單選題
            if not df_mcq.empty:
                dm = df_mcq[
                    (df_mcq['版本'] == rv_v) &
                    (df_mcq['年度'] == rv_y) & (df_mcq['冊編號'] == rv_b) &
                    (df_mcq['課編號'] == rv_l)
                ].copy()
                if not dm.empty:
                    dm['題目ID'] = dm.apply(lambda r: _get_qid(r), axis=1)
                    all_items.append(dm)
            # 朗讀題
            if not df_r.empty:
                drv = df_r[
                    (df_r['版本'] == rv_v) &
                    (df_r['年度'] == rv_y) & (df_r['冊編號'] == rv_b) &
                    (df_r['課編號'] == rv_l)
                ].copy()
                if not drv.empty:
                    drv['題目ID'] = drv.apply(lambda r: f"R_{_get_qid(r)}", axis=1)
                    drv['_type'] = 'reading'
                    all_items.append(drv)
            # 拼單字
            if not df_v.empty:
                dvr = df_v[
                    (df_v['版本'] == rv_v) &
                    (df_v['年度'] == rv_y) & (df_v['冊編號'] == rv_b) &
                    (df_v['課編號'] == rv_l)
                ].copy()
                if not dvr.empty:
                    dvr['單元'] = dvr.get('單元', '拼單字')
                    dvr['題目ID'] = dvr.apply(lambda r: f"V_{_get_qid(r)}", axis=1)
                    dvr['_type'] = 'vocab'
                    all_items.append(dvr)
            # 閱讀單句
            if not df_rm.empty:
                drm = df_rm[
                    (df_rm['版本'] == rv_v) &
                    (df_rm['年度'] == rv_y) & (df_rm['冊編號'] == rv_b) &
                    (df_rm['課編號'] == rv_l)
                ].copy()
                if not drm.empty:
                    drm['題目ID'] = drm.apply(lambda r: f"RM_{_get_qid(r)}", axis=1)
                    drm['_type'] = 'reading_mcq'
                    all_items.append(drm)
            # 聽力音標（依範圍）
            if not df_lp.empty:
                dlp_range = df_lp.copy()
                dlp_range['題目ID'] = dlp_range.apply(_get_lp_qid, axis=1)
                dlp_range['_type']  = 'listen_phon'
                # 依版本/年度/冊/課篩選（聽力音標沒有年度/冊/課欄位，只用版本）
                if rv_v:
                    dlp_range = dlp_range[dlp_range['版本'] == rv_v]
                if not dlp_range.empty:
                    all_items.append(dlp_range)

        if not all_items:
            st.error("❌ 找不到題目，請重新選擇")

        else:
            df_rv = pd.concat(all_items, ignore_index=True)

            # 計算統計（在篩選前，用雙向ID比對）
            total_count = len(df_rv)
            if not my_logs.empty and '題目ID' in my_logs.columns:
                all_qids = set(df_rv['題目ID'].tolist())
                # 同時加入任務原始 ID（版本可能不同，如 3688 vs 歷屆聯考）
                if rv_q_ids:
                    all_qids |= set(rv_q_ids)
                # 同時產生有V_和無V_的版本來比對logs
                all_qids_alt = set()
                for qid in all_qids:
                    if qid.startswith('V_'):
                        all_qids_alt.add(qid[2:])
                    else:
                        all_qids_alt.add(f"V_{qid}")
                all_match = all_qids | all_qids_alt

                logs_in_scope = my_logs[
                    my_logs['題目ID'].isin(all_match) &
                    (~my_logs['結果'].str.contains('📖', na=False))
                ].copy()
                answered_ids = set(logs_in_scope['題目ID'].tolist())


                wrong_ever   = set(logs_in_scope[logs_in_scope['結果'] == '❌']['題目ID'].tolist())
                if '時間' in logs_in_scope.columns and not logs_in_scope.empty:
                    last_ans     = logs_in_scope.sort_values('時間').groupby('題目ID').last().reset_index()
                    last_correct = set(last_ans[last_ans['結果'] == '✅']['題目ID'].tolist())
                else:
                    last_correct = set(logs_in_scope[logs_in_scope['結果'] == '✅']['題目ID'].tolist())
            else:
                answered_ids = set()
                wrong_ever   = set()
                last_correct = set()

            # 計算每題複習次數
            review_counts = {}  # qid -> 複習次數
            if not my_logs.empty and '題目ID' in my_logs.columns:
                rv_logs = my_logs[my_logs['結果'] == '📖 複習'].copy()
                for qid_r in df_rv['題目ID'].tolist():
                    qid_r_alt = qid_r[2:] if qid_r.startswith('V_') else f"V_{qid_r}"
                    cnt = len(rv_logs[rv_logs['題目ID'].isin([qid_r, qid_r_alt])])
                    review_counts[qid_r] = cnt

            # 依顯示範圍篩選
            if rv_scope == "✏️ 已經答題":
                df_rv = df_rv[df_rv['題目ID'].isin(answered_ids) |
                              df_rv['題目ID'].apply(lambda x: x[2:] if x.startswith('V_') else f"V_{x}").isin(answered_ids)]
            elif rv_scope == "❌ 只看錯題":
                df_rv = df_rv[df_rv['題目ID'].isin(wrong_ever) |
                              df_rv['題目ID'].apply(lambda x: x[2:] if x.startswith('V_') else f"V_{x}").isin(wrong_ever)]
            elif rv_scope == "❓ 只看未作答":
                df_rv = df_rv[~(df_rv['題目ID'].isin(answered_ids) |
                                df_rv['題目ID'].apply(lambda x: x[2:] if x.startswith('V_') else f"V_{x}").isin(answered_ids))]
            elif rv_scope == "🔄 複習次數少的優先":
                df_rv['_rv_cnt'] = df_rv['題目ID'].apply(lambda x: review_counts.get(x, 0))
                df_rv = df_rv.sort_values('_rv_cnt', ascending=True).drop(columns=['_rv_cnt'])

            st.session_state['rv_items']        = df_rv.to_dict('records')
            st.session_state['rv_my_logs']      = my_logs.to_dict('records') if not my_logs.empty else []
            st.session_state['rv_review_counts'] = review_counts
            st.session_state['rv_stats']        = {
                'total':        total_count,
                'answered':     len(answered_ids),
                'wrong_ever':   len(wrong_ever),
                'last_correct': len(last_correct),
            }
            st.rerun()

    # ── 復習列表顯示 ──────────────────────────────────────────────────
    if st.session_state.get('rv_items') is not None:
        rv_items        = st.session_state['rv_items']
        rv_my_logs      = pd.DataFrame(st.session_state.get('rv_my_logs', []))
        rv_stats        = st.session_state.get('rv_stats', {})
        rv_review_counts = st.session_state.get('rv_review_counts', {})

        # 統計卡片
        if rv_stats:
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("📚 總題數",    rv_stats.get('total', 0))
            s2.metric("✏️ 已答題",   rv_stats.get('answered', 0))
            s3.metric("❌ 錯題數",    rv_stats.get('wrong_ever', 0),   help="曾經答錯過（同一題只算一次）")
            s4.metric("✅ 最後答對",  rv_stats.get('last_correct', 0), help="最後一次作答為正確的題數")
            st.divider()

        if not rv_items:
            st.info("✅ 此範圍沒有符合條件的題目。")
        else:
            st.markdown(f"**📋 顯示 {len(rv_items)} 題**")
            st.divider()
            for i, item in enumerate(rv_items, 1):
                qid    = item.get('題目ID', '')
                q_type = item.get('_type', '')
                q_unit = str(item.get('單元', ''))

                if q_type == 'reading' or '朗讀' in q_unit:
                    q_text     = str(item.get('朗讀句子') or item.get('英文句子') or '').strip()
                    q_ans      = q_text
                    type_label = "🎤 朗讀"
                elif q_type == 'vocab' or '單字' in q_unit:
                    q_text     = str(item.get('中文意思') or '').strip()
                    q_ans      = str(item.get('英文單字') or '').strip()
                    type_label = "🔤 單字"
                elif q_type == 'listen_sent':
                    q_text     = str(item.get('聽力重組英文答案') or '').strip()
                    q_ans      = q_text
                    type_label = "🎧 聽力重組"
                elif q_type == 'listen_phon':
                    q_text     = str(item.get('KK符號') or '').strip()
                    q_ans      = q_text
                    type_label = "🎧 聽力音標"
                elif (q_type == 'mcq' or '單選' in q_unit or
                      str(item.get('單選答案') or '').strip() or
                      any(str(item.get(f'選項{o}') or '').strip() for o in ['A','B','C','D'])):
                    q_text     = str(item.get('單選題目') or item.get('中文題目') or '').strip()
                    q_ans      = str(item.get('單選答案') or '').strip()
                    type_label = "🔵 單選"
                else:
                    q_text     = str(item.get('重組中文題目') or item.get('中文題目') or '').strip()
                    q_ans      = str(item.get('重組英文答案') or item.get('英文答案') or '').strip()
                    type_label = "📝 重組"

                q_analysis = str(item.get('解析') or '').strip()

                # 判斷是否已作答（支援新舊ID格式）
                qid_alt = qid[2:] if qid.startswith('V_') else f"V_{qid}"
                if not rv_my_logs.empty and '題目ID' in rv_my_logs.columns:
                    mql = rv_my_logs[
                        (rv_my_logs['題目ID'].isin([qid, qid_alt])) &
                        (~rv_my_logs['結果'].str.contains('📖', na=False))
                    ]
                    if '時間' in mql.columns:
                        mql = mql.sort_values('時間', ascending=True)
                    history    = "".join(mql['結果'].tolist()) if not mql.empty else "未作答"
                    has_answer = not mql.empty
                else:
                    history    = "未作答"
                    has_answer = False

                # 已作答才顯示答案和解析
                if q_type == 'reading' or '朗讀' in q_unit:
                    # 朗讀：永遠顯示答案（英文句子）和 TTS
                    ans_html      = f"<div style='color:#1565c0; font-size:1.1rem; font-weight:600; margin-top:6px;'>🔊 {q_ans}</div>"
                    analysis_html = f"<div style='color:#555; font-size:0.9rem; margin-top:4px;'>📝 {q_analysis}</div>" if q_analysis else ""
                elif q_type == 'listen_phon':
                    # 聽力音標：永遠顯示 KK 符號答案
                    ans_html      = f"<div style='color:#1565c0; font-size:1.2rem; font-weight:600; margin-top:6px;'>🎧 正確音標：{q_ans}</div>"
                    analysis_html = f"<div style='color:#555; font-size:0.9rem; margin-top:4px;'>📝 {q_analysis}</div>" if q_analysis else ""
                elif q_type == 'listen_sent':
                    # 聽力重組：永遠顯示答案和翻譯
                    ls_rv_trans = str(item.get('聽力重組中文翻譯') or '').strip()
                    ans_html      = f"<div style='color:#1565c0; font-size:1.1rem; font-weight:600; margin-top:6px;'>🎧 {q_ans}</div>" + (f"<div style='color:#555; font-size:0.9rem;'>📖 {ls_rv_trans}</div>" if ls_rv_trans else "")
                    analysis_html = ""
                else:
                    ans_html      = f"<div style='color:#2e7d32; font-size:1rem; margin-top:6px;'>✅ 答案：{q_ans}</div>" if has_answer else "<div style='color:#999; font-size:0.9rem; margin-top:6px;'>🔒 作答後才顯示答案</div>"
                    analysis_html = f"<div style='color:#555; font-size:0.9rem; margin-top:4px;'>📝 {q_analysis}</div>" if (q_analysis and has_answer) else ""
                history_html  = f"<div style='font-size:0.9rem; margin-top:6px;'>📊 我的記錄：{history}</div>"

                # 複習次數（只有已作答才顯示）
                rv_cnt      = rv_review_counts.get(qid, 0)
                rv_cnt_html = f"<div style='font-size:0.85rem; color:#888; margin-top:4px;'>🔄 已複習：{rv_cnt} 次</div>" if has_answer else ""

                st.markdown(
                    f"<div style='background:var(--color-background-secondary); border-radius:8px; padding:14px 16px; margin-bottom:4px;'>"
                    f"<div style='font-size:0.8rem; color:gray;'>{type_label}　{i} / {len(rv_items)}</div>"
                    f"<div style='font-size:1.1rem; font-weight:600; white-space:pre-wrap; margin:6px 0;'>{q_text}</div>"
                    f"{ans_html}"
                    f"{analysis_html}"
                    f"{history_html}"
                    f"{rv_cnt_html}"
                    f"</div>",
                    unsafe_allow_html=True
                )

                # 朗讀題：三種 TTS 模型音檔（session_state 快取）
                if q_type == 'reading' or '朗讀' in q_unit:
                    st.markdown("**🔊 朗讀音檔（點選產生並播放）**")
                    _tts_options = [
                        ("🎙️ 高清女聲",   "tts-1-hd", "nova",  0.6,  f"rv_tts_{i}_{qid}_hd_nova",   False),
                        ("🎙️ 高清男聲",   "tts-1-hd", "onyx",  0.6,  f"rv_tts_{i}_{qid}_hd_onyx",   False),
                        ("🎙️ 標準自然聲", "tts-1",    "alloy", 0.6,  f"rv_tts_{i}_{qid}_std_alloy",  True),
                    ]
                    for _label, _model, _voice, _speed, _tts_key, _auto in _tts_options:
                        _data_key = f"data_{_tts_key}"
                        # 標準自然聲：自動產生，直接顯示播放器
                        if _auto:
                            if not st.session_state.get(_data_key) and q_ans:
                                with st.spinner(f"{_label} 產生中..."):
                                    try:
                                        import openai as _oai_rv, base64 as _b64rv
                                        _cl = _oai_rv.OpenAI(api_key=st.secrets.get("OPENAI_API_KEY",""))
                                        _raw = _cl.audio.speech.create(
                                            model=_model, voice=_voice, input=q_ans, speed=_speed
                                        ).content
                                        st.session_state[_data_key] = _b64rv.b64encode(_raw).decode()
                                    except Exception as _e:
                                        st.caption(f"🔇 {_label} 失敗：{_e}")
                            if st.session_state.get(_data_key):
                                import base64 as _b64rv2
                                st.caption(f"{_label}（{_model}，{_speed}x）")
                                st.audio(_b64rv2.b64decode(st.session_state[_data_key]), format="audio/mp3")
                        else:
                            # 其他兩種：按鈕觸發
                            _col1, _col2 = st.columns([1, 3])
                            if _col1.button(_label, key=f"btn_{_tts_key}", use_container_width=True):
                                if not st.session_state.get(_data_key) and q_ans:
                                    with st.spinner("產生中..."):
                                        try:
                                            import openai as _oai_rv, base64 as _b64rv
                                            _cl = _oai_rv.OpenAI(api_key=st.secrets.get("OPENAI_API_KEY",""))
                                            _raw = _cl.audio.speech.create(
                                                model=_model, voice=_voice, input=q_ans, speed=_speed
                                            ).content
                                            st.session_state[_data_key] = _b64rv.b64encode(_raw).decode()
                                        except Exception as _e:
                                            _col2.caption(f"🔇 失敗：{_e}")
                            if st.session_state.get(_data_key):
                                import base64 as _b64rv2
                                _col2.audio(_b64rv2.b64decode(st.session_state[_data_key]), format="audio/mp3")
                            else:
                                _col2.caption("← 點左側按鈕產生音檔")
                    st.caption("🤖 音檔由 OpenAI TTS 產生（tts-1 / tts-1-hd 模型，速度 0.6x）")

                # 聽力音標：播放原始音檔
                if q_type == 'listen_phon':
                    lp_rv_num = str(item.get('總編號', '')).strip()
                    lp_rv_sym = str(item.get('KK符號', '')).strip()
                    try:
                        _lp_rv_key = f"{int(lp_rv_num):02d}-{lp_rv_sym}".lower()
                    except:
                        _lp_rv_key = f"{lp_rv_num}-{lp_rv_sym}".lower()
                    _rv_audio_index = load_audio_file_index()
                    _rv_file_id = _rv_audio_index.get(_lp_rv_key, "")
                    if _rv_file_id:
                        _rv_audio_data_key = f"rv_lp_audio_{i}_{qid}"
                        if not st.session_state.get(_rv_audio_data_key):
                            try:
                                import requests as _req_rv_lp
                                _rv_r = _req_rv_lp.get(get_audio_url(_rv_file_id), timeout=8)
                                if _rv_r.status_code == 200:
                                    import base64 as _b64_rv_lp
                                    st.session_state[_rv_audio_data_key] = _b64_rv_lp.b64encode(_rv_r.content).decode()
                            except:
                                pass
                        if st.session_state.get(_rv_audio_data_key):
                            import base64 as _b64_rv_lp2
                            st.markdown("**🎧 聆聽音檔：**")
                            st.audio(_b64_rv_lp2.b64decode(st.session_state[_rv_audio_data_key]), format="audio/mp3")
                    else:
                        st.caption(f"⚠️ 找不到音檔：{_lp_rv_key}")

                # 聽力句子重組：TTS 音檔
                if q_type == 'listen_sent':
                    ls_rv_ans   = str(item.get('聽力重組英文答案') or '').strip()
                    ls_rv_trans = str(item.get('聽力重組中文翻譯') or '').strip()
                    ls_rv_tts_key = f"rv_ls_tts_{i}_{qid}"
                    if not st.session_state.get(ls_rv_tts_key) and ls_rv_ans:
                        with st.spinner("🔊 產生音檔..."):
                            try:
                                import openai as _oai_rv_ls, base64 as _b64_rv_ls
                                _cl_rv_ls = _oai_rv_ls.OpenAI(api_key=st.secrets.get("OPENAI_API_KEY",""))
                                _raw_rv_ls = _cl_rv_ls.audio.speech.create(
                                    model="tts-1", voice="alloy", input=ls_rv_ans, speed=0.8
                                ).content
                                st.session_state[ls_rv_tts_key] = _b64_rv_ls.b64encode(_raw_rv_ls).decode()
                            except Exception as _e_rv_ls:
                                st.caption(f"🔇 失敗：{_e_rv_ls}")
                    if st.session_state.get(ls_rv_tts_key):
                        import base64 as _b64_rv_ls2
                        st.markdown("**🎧 聆聽音檔：**")
                        st.audio(_b64_rv_ls2.b64decode(st.session_state[ls_rv_tts_key]), format="audio/mp3")
                    if ls_rv_trans:
                        st.info(f"📖 中文翻譯：{ls_rv_trans}")

                # 複習按鈕（只有已作答才顯示）
                if has_answer:
                    if st.button("🔄 我已複習這題", key=f"rv_done_{i}_{qid}", use_container_width=True):
                        log_data = pd.DataFrame([{
                            "時間":    get_now().strftime("%Y-%m-%d %H:%M:%S"),
                            "姓名":    user_name,
                            "分組":    st.session_state.group_id,
                            "題目ID":  qid,
                            "結果":    "📖 複習",
                            "學生答案": "",
                            "任務名稱": st.session_state.get("current_task_name", ""), "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))
                        }])
                        if append_to_sheet("logs", log_data):
                            rv_review_counts[qid] = rv_review_counts.get(qid, 0) + 1
                            st.session_state['rv_review_counts'] = rv_review_counts
                            st.success(f"✅ 已記錄複習！這題已複習 {rv_review_counts[qid]} 次")
                st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

    show_version_caption()

# ------------------------------------------------------------------------------
# 📦 【盒子 D：練習引擎】
# ------------------------------------------------------------------------------
if st.session_state.quiz_loaded:
    # 追蹤實際作答題數（跳過的題不算）
    if 'answered_count' not in st.session_state:
        st.session_state['answered_count'] = 0

    total_q    = len(st.session_state.quiz_list)
    answered_c = st.session_state.get('answered_count', 0)
    _practice_mode = st.session_state.get('practice_mode', False)
    _race_mode     = st.session_state.get('race_mode', False)
    _quick_mode    = st.session_state.get('quick_mode', False)
    _shadow_mode   = st.session_state.get('shadow_mode', False)
    _mode_label    = "🏆 競賽模式" if _race_mode else ("🏋️ 練習模式" if _practice_mode else ("⚡ 快速答題" if _quick_mode else ("🎤 跟著唸" if _shadow_mode else "")))

    # ── 單題計時 ──────────────────────────────────────────────────────────
    import time as _time_sys
    _q_timer_key = f"_q_start_time_{st.session_state.q_idx}"
    # 若剛開始新任務（answered_count=0），清除所有舊計時器確保從90秒開始
    if st.session_state.get('answered_count', 0) == 0 and not st.session_state.get('_timers_cleared'):
        for _kt in list(st.session_state.keys()):
            if _kt.startswith("_q_start_time_"):
                st.session_state.pop(_kt, None)
        st.session_state['_timers_cleared'] = True
    if not st.session_state.get(_q_timer_key):
        st.session_state[_q_timer_key] = _time_sys.time()
    _q_elapsed  = int(_time_sys.time() - st.session_state[_q_timer_key])
    _idle_limit = 90

    # 90 秒閒置：寫入超時記錄並跳回任務列表
    if _q_elapsed >= _idle_limit and not st.session_state.get("show_analysis"):
        import pandas as _pd_timeout
        _timeout_row = {
            "時間": get_now().strftime("%Y-%m-%d %H:%M:%S"),
            "姓名": st.session_state.user_name,
            "分組": st.session_state.group_id,
            "題目ID": st.session_state.quiz_list[st.session_state.q_idx].get("題目ID", "N/A") if st.session_state.quiz_list else "N/A",
            "結果": "⏰ 超時",
            "學生答案": "",
            "分數": "",
            "任務名稱": st.session_state.get("current_task_name", ""),
            "作答秒數": _q_elapsed,
        }
        append_to_sheet("logs", _pd_timeout.DataFrame([_timeout_row]))
        # 清除 autorefresh 避免空轉
        _ar_key = f"timer_refresh_{st.session_state.q_idx}"
        st.session_state.pop(_ar_key, None)
        st.session_state.update({
            "quiz_loaded": False, "range_confirmed": False,
            "show_analysis": False, "current_res": "",
        })
        st.warning(f"⏰ 閒置超過 {_idle_limit} 秒，自動返回任務列表。")
        st.rerun()
    # 快速答題：答完自動跳下一題
    if _quick_mode and st.session_state.get('show_analysis') and st.session_state.get('_quick_auto_next'):
        st.session_state.pop('_quick_auto_next', None)
        _clear_q()  # 清除當前題狀態
        if st.session_state.q_idx + 1 < len(st.session_state.quiz_list):
            st.session_state.q_idx += 1
        else:
            st.session_state.update({"quiz_loaded": False, "range_confirmed": False, "quick_mode": False})
        st.rerun()
    # 競賽/練習模式進入第一題：強制清除對錯狀態
    if (_race_mode or _practice_mode or _quick_mode) and st.session_state.get('q_idx', 0) == 0:
        if not st.session_state.get('_first_q_cleared'):
            st.session_state['show_analysis'] = False
            st.session_state['current_res']   = ""
            st.session_state['_first_q_cleared'] = True
    elif st.session_state.get('q_idx', 0) > 0:
        st.session_state.pop('_first_q_cleared', None)
    # 計時顯示
    _remain = max(0, _idle_limit - _q_elapsed)
    _timer_color = "🔴" if _remain <= 15 else ("🟡" if _remain <= 30 else "🟢")
    _answered_now = st.session_state.get('answered_count', 0)
    if not st.session_state.get("show_analysis"):
        st.markdown(f"### 🔴 練習中 (第 {st.session_state.q_idx + 1} / {total_q} 題　｜　已作答 {_answered_now} 題　｜　{_timer_color} {_remain}秒) {_mode_label}")
    else:
        st.markdown(f"### 🔴 練習中 (第 {st.session_state.q_idx + 1} / {total_q} 題　｜　已作答 {_answered_now} 題) {_mode_label}")
    q = st.session_state.quiz_list[st.session_state.q_idx]

    # ── 跟著唸模式 ────────────────────────────────────────────────────────
    if _shadow_mode:
        _sh_ans = str(q.get('重組英文答案') or q.get('英文答案') or q.get('英文單字') or '').strip()
        _sh_zh  = str(q.get('重組中文題目') or q.get('中文意思') or q.get('中文') or '').strip()
        # 用 q_idx + 內容 hash 作為唯一 key，確保換題一定重新載入
        import hashlib as _hl
        _sh_hash = _hl.md5(_sh_ans.encode()).hexdigest()[:8]
        _sh_f_key = f"shadow_tts_f_{st.session_state.q_idx}_{_sh_hash}"
        _sh_m_key = f"shadow_tts_m_{st.session_state.q_idx}_{_sh_hash}"

        # 顯示英文和中文
        st.markdown(f"## 🔊 {_sh_ans}")
        if _sh_zh:
            st.markdown(f"**📖 {_sh_zh}**")
        st.divider()

        # 載入 TTS
        if _sh_ans and (not st.session_state.get(_sh_f_key) or not st.session_state.get(_sh_m_key)):
            with st.spinner("載入語音..."):
                try:
                    import openai as _oai_sh, base64 as _b64_sh
                    _cli_sh = _oai_sh.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                    if not st.session_state.get(_sh_f_key):
                        _tf = _cli_sh.audio.speech.create(model="tts-1", voice="nova", input=_sh_ans).content
                        st.session_state[_sh_f_key] = _b64_sh.b64encode(_tf).decode()
                    if not st.session_state.get(_sh_m_key):
                        _tm = _cli_sh.audio.speech.create(model="tts-1", voice="onyx", input=_sh_ans).content
                        st.session_state[_sh_m_key] = _b64_sh.b64encode(_tm).decode()
                    st.rerun()
                except Exception as _e_sh:
                    st.error(f"TTS 載入失敗：{_e_sh}")

        # 顯示播放器
        if st.session_state.get(_sh_f_key) or st.session_state.get(_sh_m_key):
            import base64 as _b64_sh, io as _io_sh
            _sc1, _sc2 = st.columns(2)
            if st.session_state.get(_sh_m_key):
                _sc1.caption("🎵 男聲（自動播放×2，0.75倍速）")
                _m_b64 = st.session_state[_sh_m_key]
                import streamlit.components.v1 as _cv1_sh
                _sc1.empty()
                _cv1_sh.html(f"""
                <audio id="male_audio" src="data:audio/mpeg;base64,{_m_b64}" style="width:100%;display:block" controls></audio>
                <script>
                var a = document.getElementById('male_audio');
                var count = 0;
                a.playbackRate = 0.75;
                a.play();
                a.onended = function(){{
                    count++;
                    if(count < 2){{ a.currentTime=0; a.play(); }}
                }};
                </script>
                """, height=60)
            if st.session_state.get(_sh_f_key):
                _sc2.caption("🎵 自然聲音")
                _sc2.audio(_io_sh.BytesIO(_b64_sh.b64decode(st.session_state[_sh_f_key])), format="audio/mpeg")

        # 學生錄音（選填）
        st.markdown("**🎙️ 自我練習錄音（選填）**")
        _sh_rec = st.audio_input("點擊錄音", key=f"shadow_rec_{st.session_state.q_idx}_{_sh_hash}", label_visibility="collapsed")
        if _sh_rec:
            _sh_score_key = f"shadow_score_{st.session_state.q_idx}_{_sh_hash}"
            if st.button("🤖 AI 評分", key=f"sh_ai_{st.session_state.q_idx}", type="primary"):
                with st.spinner("🔄 評分中，請稍候..."):
                    try:
                        import openai as _oai_sc, re as _re_sc
                        _cli_sc = _oai_sc.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                        # Whisper STT
                        _sh_rec.seek(0)
                        _transcript = _cli_sc.audio.transcriptions.create(
                            model="whisper-1",
                            file=("audio.wav", _sh_rec, "audio/wav"),
                            language="en"
                        )
                        _stt = _transcript.text.strip()
                        _std_clean = _re_sc.sub(r'[.,?!:;\'\"()\-]', '', _sh_ans).strip()
                        _stt_clean  = _re_sc.sub(r'[.,?!:;\'\"()\-]', '', _stt).strip()
                        # GPT-4o-mini 評分
                        _score_resp = _cli_sc.chat.completions.create(
                            model="gpt-4o-mini", max_tokens=10,
                            messages=[{"role": "user", "content":
                                f"You are an English pronunciation evaluator.\n"
                                f"Standard: \"{_std_clean}\"\nStudent said: \"{_stt_clean}\"\n"
                                f"Score accuracy 0-100. Reply with ONLY a single integer."}]
                        )
                        _score = max(0, min(100, int(_re_sc.sub(r'[^0-9]', '', _score_resp.choices[0].message.content.strip()) or '0')))
                        _emoji = "✅ 優秀！" if _score >= 90 else ("🟡 不錯！" if _score >= 70 else ("🟠 需加強" if _score >= 50 else "❌ 請再試試"))
                        st.session_state[_sh_score_key] = {"score": _score, "emoji": _emoji, "stt": _stt}
                        # 寫入 log（參考朗讀格式）
                        import time as _sh_st
                        append_to_sheet("logs", pd.DataFrame([{
                            "時間":    get_now().strftime("%Y-%m-%d %H:%M:%S"),
                            "姓名":    st.session_state.user_name,
                            "分組":    st.session_state.group_id,
                            "題目ID":  q.get("題目ID", "N/A"),
                            "結果":    "🎤 跟著唸",
                            "學生答案": _stt,
                            "分數":    _score,
                            "任務名稱": st.session_state.get("current_task_name", ""),
                            "作答秒數": round(_sh_st.time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", _sh_st.time())),
                        }]))
                        st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                        _load_logs_cached.clear()
                        st.rerun()
                    except Exception as _e_sc:
                        st.error(f"評分失敗：{_e_sc}")
            # 顯示評分結果
            if st.session_state.get(_sh_score_key):
                _sr = st.session_state[_sh_score_key]
                st.markdown(f"### {_sr['emoji']} {_sr['score']} 分")
                st.caption(f"AI 聽到：{_sr['stt']}")

        # 四個導航按鈕（移除再聽一次，改為三個）
        st.divider()
        _sh_c1, _sh_c2, _sh_c3 = st.columns(3)
        _total_sh = len(st.session_state.quiz_list)
        _idx_sh   = st.session_state.q_idx

        # 上一題
        if _sh_c1.button("⬅️ 上一題", key="sh_prev", use_container_width=True,
                          disabled=(_idx_sh == 0)):
            st.session_state.update({"ans": [], "shuf": [], "show_analysis": False, "current_res": ""})
            st.session_state.pop(f"_q_start_time_{_idx_sh}", None)
            # 清除所有 shadow TTS（確保換題重新載入）
            for _k in list(st.session_state.keys()):
                if _k.startswith("shadow_tts_"):
                    st.session_state.pop(_k, None)
            st.session_state.q_idx -= 1
            st.rerun()

        # 下一題
        if _sh_c2.button("➡️ 下一題", key="sh_next", use_container_width=True,
                          disabled=(_idx_sh + 1 >= _total_sh), type="primary"):
            import time as _sh_t
            _sh_elapsed = round(_sh_t.time() - st.session_state.get(f"_q_start_time_{_idx_sh}", _sh_t.time()))
            append_to_sheet("logs", pd.DataFrame([{
                "時間": get_now().strftime("%Y-%m-%d %H:%M:%S"),
                "姓名": st.session_state.user_name, "分組": st.session_state.group_id,
                "題目ID": q.get("題目ID", "N/A"), "結果": "🎤 跟著唸",
                "學生答案": "", "分數": "",
                "任務名稱": st.session_state.get("current_task_name", ""),
                "作答秒數": _sh_elapsed,
            }]))
            st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
            st.session_state.update({"ans": [], "shuf": [], "show_analysis": False, "current_res": ""})
            st.session_state.pop(f"_q_start_time_{_idx_sh}", None)
            # 清除所有 shadow TTS（確保換題重新載入）
            for _k in list(st.session_state.keys()):
                if _k.startswith("shadow_tts_"):
                    st.session_state.pop(_k, None)
            st.session_state.q_idx += 1
            st.rerun()

        # 結束
        if _sh_c3.button("🏁 結束", key="sh_end", use_container_width=True):
            st.session_state.update({"quiz_loaded": False, "range_confirmed": False, "shadow_mode": False})
            st.rerun()

        show_version_caption()
        st.stop()
    # ── 跟著唸模式結束 ───────────────────────────────────────────────────
    # 判斷題型：優先用 _type，其次看欄位，最後看單元名稱
    _qtype         = q.get("_type", "")
    _has_mcq_ans   = bool(str(q.get("單選答案") or "").strip())
    _has_mcq_field = any(str(q.get(f"選項{o}") or "").strip() for o in ["A","B","C","D"])
    is_mcq         = _qtype == "mcq" or _has_mcq_ans or _has_mcq_field or "單選" in q.get("單元", "")
    is_reading     = _qtype == "reading" or "朗讀" in q.get("單元", "")
    is_vocab       = _qtype == "vocab"
    is_reading_mcq = _qtype == "reading_mcq"
    is_listen_phon = _qtype == "listen_phon"
    is_listen_sent = _qtype == "listen_sent"
    # 避免 is_mcq 和其他類型衝突
    if is_reading or is_vocab or is_reading_mcq or is_listen_phon or is_listen_sent:
        is_mcq = False

    # 題目標題
    if is_listen_sent:
        # ── 聽力句子重組題 ────────────────────────────────────────────────────
        ls_qid     = q.get("題目ID", "")
        ls_answer  = str(q.get("聽力重組英文答案") or "").strip()
        ls_trans   = str(q.get("聽力重組中文翻譯") or "").strip()
        ls_words   = q.get("_ls_words", _ls_split_words(ls_answer))

        # TTS 音檔（自動產生，natural voice）
        ls_tts_key = f"ls_tts_{st.session_state.q_idx}_{ls_qid}"
        if not st.session_state.get(ls_tts_key) and ls_answer:
            with st.spinner("🔊 產生聆聽音檔..."):
                try:
                    import openai as _oai_ls, base64 as _b64_ls
                    _cl_ls = _oai_ls.OpenAI(api_key=st.secrets.get("OPENAI_API_KEY",""))
                    _raw_ls = _cl_ls.audio.speech.create(
                        model="tts-1", voice="alloy", input=ls_answer, speed=0.8
                    ).content
                    st.session_state[ls_tts_key] = _b64_ls.b64encode(_raw_ls).decode()
                except Exception as _e_ls:
                    st.caption(f"🔇 音檔產生失敗：{_e_ls}")
        st.markdown("**🎧 請聆聽音檔，重組成正確句子：**")
        if st.session_state.get(ls_tts_key):
            import base64 as _b64_ls2
            st.audio(_b64_ls2.b64decode(st.session_state[ls_tts_key]), format="audio/mp3")

        already_ls = st.session_state.get("show_analysis", False)

        # 答案顯示區
        ls_ans_key  = f"ls_ans_{st.session_state.q_idx}"
        ls_used_key = f"ls_used_{st.session_state.q_idx}"
        ls_shuf_key = f"ls_shuf_{st.session_state.q_idx}"
        if ls_shuf_key not in st.session_state:
            import random as _rls
            _rls_words = ls_words.copy()
            _rls.shuffle(_rls_words)
            st.session_state[ls_shuf_key] = _rls_words
        if ls_ans_key not in st.session_state:
            st.session_state[ls_ans_key] = []
        if ls_used_key not in st.session_state:
            st.session_state[ls_used_key] = []

        current_ls_ans = st.session_state[ls_ans_key]
        shuffled_words = st.session_state[ls_shuf_key]
        used_ls        = set(st.session_state[ls_used_key])

        # 顯示已選單字
        if current_ls_ans:
            ans_html_ls = " ".join([
                f"<span style='display:inline-block;padding:4px 10px;margin:2px;background:#4a90d9;color:white;border-radius:6px;font-size:1.1rem;font-weight:600;'>{w}</span>"
                for w in current_ls_ans
            ])
        else:
            ans_html_ls = "<span style='color:#aaa;font-size:1rem;'>點選下方單字</span>"
        st.markdown(f"<div style='padding:10px;min-height:45px;background:#f0f4ff;border-radius:8px;margin-bottom:6px;'>{ans_html_ls}</div>", unsafe_allow_html=True)

        # 退回/清除按鈕
        if not already_ls:
            _lsc1, _lsc2 = st.columns(2)
            if _lsc1.button("⬅️ 退回一步", key=f"ls_back_{st.session_state.q_idx}", use_container_width=True):
                if current_ls_ans:
                    st.session_state[ls_ans_key].pop()
                    used = st.session_state[ls_used_key]
                    if used:
                        used.pop()
                    st.session_state[ls_used_key] = used
                    st.rerun()
            if _lsc2.button("🗑️ 全部清除", key=f"ls_clear_{st.session_state.q_idx}", use_container_width=True):
                st.session_state[ls_ans_key] = []
                st.session_state[ls_used_key] = []
                st.rerun()

            # 單字按鈕（固定8欄）
            NUM_COLS_LS = min(len(shuffled_words), 8)
            if NUM_COLS_LS > 0:
                cols_ls = st.columns(NUM_COLS_LS)
                for wi, word in enumerate(shuffled_words):
                    col = cols_ls[wi % NUM_COLS_LS]
                    if wi in used_ls:
                        col.button("·", key=f"ls_w_{st.session_state.q_idx}_{wi}", use_container_width=True, disabled=True)
                    else:
                        if col.button(word, key=f"ls_w_{st.session_state.q_idx}_{wi}", use_container_width=True):
                            st.session_state[ls_ans_key].append(word)
                            st.session_state[ls_used_key].append(wi)
                            st.rerun()

            # 全部選完自動檢查
            if len(current_ls_ans) == len(shuffled_words) and not already_ls:
                _ls_user = " ".join(current_ls_ans)
                _ls_correct_clean = " ".join(_ls_split_words(ls_answer))
                _ls_ok = _ls_user.lower() == _ls_correct_clean.lower()
                try:
                    import time as _tls
                    sb_ls  = get_supabase()
                    en_ls  = _to_en_logs({
                        "時間":    get_now().strftime("%Y-%m-%d %H:%M:%S"),
                        "姓名":    st.session_state.user_name,
                        "分組":    st.session_state.group_id,
                        "題目ID":  ls_qid,
                        "結果":    "✅" if _ls_ok else "❌",
                        "學生答案": _ls_user,
                        "分數":    "",
                        "任務名稱": st.session_state.get("current_task_name", ""), "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))
                    })
                    sb_ls.table("logs").insert(en_ls).execute()
                    _tls.sleep(0.3)
                    st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                    _load_logs_cached.clear()
                except Exception as _e_ls2:
                    st.error(f"寫入失敗：{_e_ls2}")
                st.session_state.update({
                    "current_res":   "✅ 正確！" if _ls_ok else f"❌ 錯誤！",
                    "show_analysis": True
                })
                st.rerun()

            # 手動送出按鈕
            if st.button("✅ 檢查作答結果", type="primary", use_container_width=True, key=f"ls_submit_{st.session_state.q_idx}"):
                _ls_user2 = " ".join(current_ls_ans)
                _ls_ok2   = _ls_user2.lower() == " ".join(_ls_split_words(ls_answer)).lower()
                try:
                    import time as _tls2
                    sb_ls2 = get_supabase()
                    en_ls2 = _to_en_logs({
                        "時間":    get_now().strftime("%Y-%m-%d %H:%M:%S"),
                        "姓名":    st.session_state.user_name,
                        "分組":    st.session_state.group_id,
                        "題目ID":  ls_qid,
                        "結果":    "✅" if _ls_ok2 else "❌",
                        "學生答案": _ls_user2,
                        "分數":    "",
                        "任務名稱": st.session_state.get("current_task_name", ""), "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))
                    })
                    sb_ls2.table("logs").insert(en_ls2).execute()
                    _tls2.sleep(0.3)
                    st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                    _load_logs_cached.clear()
                except:
                    pass
                st.session_state.update({
                    "current_res":   "✅ 正確！" if _ls_ok2 else "❌ 錯誤！",
                    "show_analysis": True
                })
                st.rerun()

        # 結果顯示
        if already_ls:
            res_ls = st.session_state.get("current_res", "")
            if "✅" in res_ls:
                st.success(res_ls)
            else:
                st.error(res_ls)
            st.markdown(f"**正確答案：** {ls_answer}")
            if ls_trans:
                st.info(f"📖 中文翻譯：{ls_trans}")

    elif is_listen_phon:
        # ── 聽力音標題 ──────────────────────────────────────────────────────
        lp_qid     = q.get("題目ID", "")
        lp_num     = str(q.get("總編號", "")).strip()
        lp_correct = str(q.get("KK符號", "")).strip().strip("[]").strip()
        lp_opts    = q.get("_lp_opts", [])  # [{"KK符號":..., "總編號":...}, ...]
        lp_correct_opt = q.get("_lp_correct_opt", "A")

        # 音檔 key：總編號補零2位 + "-" + KK符號，例如 "01-p"
        audio_index = load_audio_file_index()
        try:
            file_key = f"{int(lp_num):02d}-{lp_correct}".lower()
        except:
            file_key = f"{lp_num}-{lp_correct}".lower()
        file_id     = audio_index.get(file_key, "")
        # 若找不到，也嘗試純數字補零
        if not file_id:
            try:
                alt_key = f"{int(lp_num):02d}".lower()
                file_id = audio_index.get(alt_key, "")
            except:
                pass
        if file_id:
            st.markdown("**🎧 請聆聽音檔，選出正確的 KK 音標：**")
            # 優先用預載快取（下一題按鈕預先載入）
            _lp_cache_key = f"lp_audio_{st.session_state.q_idx}_{lp_qid}"
            if not st.session_state.get(_lp_cache_key):
                try:
                    import requests as _req_lp, base64 as _b64_lp
                    _r = _req_lp.get(get_audio_url(file_id), timeout=8)
                    if _r.status_code == 200:
                        st.session_state[_lp_cache_key] = _b64_lp.b64encode(_r.content).decode()
                except:
                    pass
            if st.session_state.get(_lp_cache_key):
                import base64 as _b64_lp2
                st.audio(_b64_lp2.b64decode(st.session_state[_lp_cache_key]), format="audio/mp3")
            else:
                st.audio(get_audio_url(file_id))
        else:
            st.warning(f"⚠️ 找不到音檔：{lp_num}（key={file_key}）")

        already_lp = st.session_state.get("show_analysis", False)
        opt_cols   = st.columns(2)
        for oi, opt_row in enumerate(lp_opts):
            opt_sym = str(opt_row.get("KK符號", "")).strip()
            opt_label = ["A","B","C","D"][oi]
            opt_btn_key = f"lp_opt_{st.session_state.q_idx}_{oi}"
            col = opt_cols[oi % 2]
            # 顯示結果時加上顏色
            if already_lp:
                if opt_label == lp_correct_opt:
                    col.success(f"**{opt_label}）{opt_sym}** ✅")
                else:
                    col.markdown(f"**{opt_label}）{opt_sym}**")
            else:
                if col.button(f"{opt_label}）{opt_sym}", key=opt_btn_key, use_container_width=True):
                    is_lp_ok = (opt_label == lp_correct_opt)
                    try:
                        import time as _tlp
                        sb_lp  = get_supabase()
                        en_lp  = _to_en_logs({
                            "時間":    get_now().strftime("%Y-%m-%d %H:%M:%S"),
                            "姓名":    st.session_state.user_name,
                            "分組":    st.session_state.group_id,
                            "題目ID":  lp_qid,
                            "結果":    "✅" if is_lp_ok else "❌",
                            "學生答案": opt_sym,
                            "分數":    "",
                            "任務名稱": st.session_state.get("current_task_name", ""), "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))
                        })
                        sb_lp.table("logs").insert(en_lp).execute()
                        _tlp.sleep(0.3)
                        st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                        _load_logs_cached.clear()
                    except Exception as _e_lp:
                        st.error(f"寫入失敗：{_e_lp}")
                    st.session_state.update({
                        "current_res":  "✅ 正確！" if is_lp_ok else f"❌ 錯誤！正確答案：{lp_correct}",
                        "show_analysis": True
                    })
                    st.rerun()

        if already_lp:
            res = st.session_state.get("current_res", "")
            if "✅" in res:
                st.success(res)
            else:
                st.error(res)
            lp_analysis = str(q.get("解析") or "").strip()
            if lp_analysis:
                st.info(f"📝 {lp_analysis}")

    elif is_reading_mcq:
        # ── 閱讀單句題 ──────────────────────────────────────────────────────
        rm_passage = str(q.get("答案") or "").strip()
        rm_question = str(q.get("題目") or "").strip()
        rm_correct  = str(q.get("正確選項列出") or "").strip().upper()
        rm_analysis = str(q.get("解析") or "").strip()

        # 顯示閱讀文章/句子
        if rm_passage:
            st.markdown(
                f"<div style='font-size:1.1rem; padding:14px 16px; "
                f"background:var(--color-background-secondary); border-radius:8px; "
                f"margin-bottom:12px; white-space:pre-wrap;'>{rm_passage}</div>",
                unsafe_allow_html=True
            )
        # 顯示題目
        st.markdown(f"**{rm_question}**")

        # 選項按鈕 A-D（隨機排列）
        _rm_answered = st.session_state.get('show_analysis', False)
        _rm_order_key = f"rm_order_{st.session_state.q_idx}"
        if _rm_order_key not in st.session_state:
            import random as _rrm
            _rm_ord = ["A","B","C","D"]
            _rrm.shuffle(_rm_ord)
            st.session_state[_rm_order_key] = _rm_ord
        rm_order = st.session_state[_rm_order_key]
        rm_cols = st.columns(2)
        for _i, _opt in enumerate(rm_order):
            _opt_text = str(q.get(f"選項{_opt}") or "").strip()
            if _opt_text:
                _btn_label = f"({_opt}) {_opt_text}"
                if rm_cols[_i % 2].button(_btn_label, key=f"rm_{_opt}",
                                           use_container_width=True,
                                           disabled=_rm_answered):
                    _is_ok = (_opt.upper() == rm_correct.upper()) if rm_correct else False
                    st.session_state.update({
                        "current_res": "✅ 正確！" if _is_ok else f"❌ 錯誤！正確答案：{rm_correct}",
                        "show_analysis": True
                    })
                    try:
                        import time as _time
                        sb_w   = get_supabase()
                        en_row = _to_en_logs({
                            "時間":    get_now().strftime("%Y-%m-%d %H:%M:%S"),
                            "姓名":    st.session_state.user_name,
                            "分組":    st.session_state.group_id,
                            "題目ID":  q.get('題目ID', 'N/A'),
                            "結果":    "練習" if st.session_state.get("practice_mode") else ("✅" if _is_ok else "❌"),
                            "學生答案": _opt,
                            "分數":    "",
                            "任務名稱": st.session_state.get("current_task_name", ""), "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))
                        })
                        sb_w.table("logs").insert(en_row).execute()
                        _time.sleep(0.3)
                        st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                        _load_logs_cached.clear()
                    except Exception as e:
                        st.error(f"❌ 寫入失敗：{e}")
                    st.rerun()

        if _rm_answered:
            st.warning(st.session_state.get('current_res', ''))
            if rm_analysis:
                st.info(f"📝 解析：{rm_analysis}")

    elif is_reading:
        st.markdown("#### 🎤 請朗讀以下英文句子：")
        read_text = str(q.get("朗讀句子") or q.get("英文句子") or q.get("英文答案") or "").strip()
        st.markdown(
            f"<div style='font-size:1.5rem; font-weight:600; padding:16px; "
            f"background:var(--color-background-secondary); border-radius:8px; "
            f"letter-spacing:0.03em;'>{read_text}</div>",
            unsafe_allow_html=True
        )
        st.write("")

        # 若已有評分，先顯示分數、TTS 和重錄提示
        if st.session_state.get('show_analysis') and is_reading:
            st.warning(st.session_state.current_res)

            # 播放學生版和標準版
            tts_stu = st.session_state.get('tts_student')
            tts_std = st.session_state.get('tts_standard')
            stt_shown = st.session_state.get('stt_text_shown', '')

            if tts_stu or tts_std:
                import base64, io
                if tts_stu:
                    st.markdown(f"**🎤 AI 認為你說的內容：** `{stt_shown}`")
                    st.audio(io.BytesIO(base64.b64decode(tts_stu)), format="audio/mpeg")
                if tts_std:
                    st.markdown("**📢 標準發音：**")
                    st.audio(io.BytesIO(base64.b64decode(tts_std)), format="audio/mpeg")

            if st.session_state.get('show_analysis') and is_reading:
                st.caption("👇 如想提高成績，可重新錄音（系統自動評分）")
            else:
                st.caption("👇 點擊下方按鈕開始錄音")

        # 放大錄音按鈕的 CSS
        st.markdown("""
            <style>
            [data-testid="stAudioInput"] {
                margin: 8px 0 16px 0;
            }
            </style>
        """, unsafe_allow_html=True)

        # 麥克風一直顯示（不管有沒有評分過）
        audio_data = st.audio_input("🎙️ 錄音", key=f"audio_{st.session_state.q_idx}")

        if audio_data:
            _scored_key = f"audio_scored_{st.session_state.q_idx}"
            try:
                _audio_hash = hash(audio_data.getvalue()[:200])
            except:
                _audio_hash = id(audio_data)
            if st.session_state.get(_scored_key) != _audio_hash:
                # 新的錄音，自動評分
                st.session_state[_scored_key] = _audio_hash
                with st.spinner("🔄 評分中，請稍候..."):
                    try:
                        import openai
                        openai.api_key = st.secrets["OPENAI_API_KEY"]

                        # Step 1：Whisper STT
                        audio_data.seek(0)
                        transcript = openai.audio.transcriptions.create(
                            model="whisper-1",
                            file=("audio.wav", audio_data, "audio/wav"),
                            language="en"
                        )
                        stt_text = transcript.text.strip()
                        # 去除標點再比對，避免影響評分
                        read_text_clean = re.sub(r'[.,?!:;\'\"()\-]', '', read_text).strip()
                        stt_text_clean  = re.sub(r'[.,?!:;\'\"()\-]', '', stt_text).strip()

                        # Step 2：GPT-4o-mini 評分
                        client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                        score_resp = client.chat.completions.create(
                            model="gpt-4o-mini",
                            max_tokens=10,
                            messages=[{
                                "role": "user",
                                "content": (
                                    f"You are an English pronunciation evaluator for students.\n"
                                    f"Standard sentence: \"{read_text_clean}\"\n"
                                    f"Student said (transcribed): \"{stt_text_clean}\"\n"
                                    f"Ignore punctuation differences when comparing. "
                                    f"Score accuracy and completeness from 0 to 100. "
                                    f"Reply with ONLY a single integer, nothing else."
                                )
                            }]
                        )
                        score_raw = score_resp.choices[0].message.content.strip()
                        score = max(0, min(100, int(re.sub(r'[^0-9]', '', score_raw) or '0')))

                        if score >= 90:
                            result_display = f"✅ 優秀！{score} 分"
                        elif score >= 70:
                            result_display = f"🟡 不錯！{score} 分"
                        elif score >= 50:
                            result_display = f"🟠 需加強 {score} 分"
                        else:
                            result_display = f"❌ 請再試試 {score} 分"

                        # TTS：產生學生版和標準版音檔，存為 base64 避免 rerun 後 bytes 失效
                        import base64
                        tts_stu_raw = client.audio.speech.create(
                            model="tts-1", voice="alloy", input=stt_text
                        ).content if stt_text else None

                        tts_std_raw = client.audio.speech.create(
                            model="tts-1", voice="nova", input=read_text
                        ).content if read_text else None

                        st.session_state.update({
                            "current_res":    result_display,
                            "show_analysis":  True,
                            "tts_student":    base64.b64encode(tts_stu_raw).decode() if tts_stu_raw else None,
                            "tts_standard":   base64.b64encode(tts_std_raw).decode() if tts_std_raw else None,
                            "stt_text_shown": stt_text
                        })

                        # 寫入 Log（每次送出都記一筆）
                        log_data = pd.DataFrame([{
                            "時間":    get_now().strftime("%Y-%m-%d %H:%M:%S"),
                            "姓名":    st.session_state.user_name,
                            "分組":    st.session_state.group_id,
                            "題目ID":  q.get('題目ID', 'N/A'),
                            "結果":    "🎤 朗讀",
                            "學生答案": stt_text,
                            "分數":    score,
                            "任務名稱": st.session_state.get("current_task_name", ""), "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))
                        }])
                        st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                        append_to_sheet("logs", log_data)
                        _load_logs_cached.clear()
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ 評分失敗：{e}")

    elif is_vocab:
        # ── 單字重組題型 ──────────────────────────────────────────────────
        import random as _random, string as _string

        word     = str(q.get("英文單字") or "").strip()
        meaning  = str(q.get("中文意思") or "").strip()
        _word_parts = word.strip().split()

        if not word:
            st.error(f"⚠️ 拼單字題目無英文單字，題目欄位：{list(q.keys())[:10]}")
            st.stop()
        task_mode    = q.get("_vocab_mode", "自選")
        use_timer    = int(q.get("_vocab_timer", 0) or 0)
        extra_letters= int(q.get("_vocab_extra", 0)) if q.get("_vocab_extra") is not None else 0


        st.markdown(f"<div style=\'font-size:1.3rem;font-weight:600;padding:12px;background:var(--color-background-secondary);border-radius:8px;\'>📖 {meaning}</div>", unsafe_allow_html=True)

        st.write("")

        # 若進入題目時 show_analysis 殘留但尚未作答，強制清除
        _kb_key = f"vocab_kb_{st.session_state.q_idx}"
        _ans_key_check = f"vocab_ans_{st.session_state.q_idx}"
        _has_ans = bool(st.session_state.get(_kb_key, "")) or bool(st.session_state.get(_ans_key_check, []))
        if st.session_state.get("show_analysis") and not _has_ans:
            st.session_state["show_analysis"]    = False
            st.session_state["current_res"]      = ""
            st.session_state["vocab_start_time"] = None
            st.session_state["vocab_q_idx"]      = None
            st.rerun()

        # 限時倒數
        if use_timer > 0:
            if st.session_state.get("vocab_q_idx") != st.session_state.q_idx or not st.session_state.get("vocab_start_time"):
                st.session_state["vocab_start_time"] = get_now().timestamp()
                st.session_state["vocab_q_idx"] = st.session_state.q_idx
            _vst = st.session_state.get("vocab_start_time") or get_now().timestamp()
            elapsed = get_now().timestamp() - _vst
            remain  = max(0, use_timer - int(elapsed))
            st.markdown(f"⏱️ 剩餘時間：**{remain} 秒**")
            if remain == 0 and not st.session_state.get("show_analysis"):
                st.session_state.update({"current_res": f"⏰ 時間到！答案是：{word}", "show_analysis": True})
                _timeout_ans = "".join(st.session_state.get(f"vocab_ans_{st.session_state.q_idx}", [])) or st.session_state.get(f"vocab_kb_{st.session_state.q_idx}", "")
                st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                append_to_sheet("logs", pd.DataFrame([{"時間": get_now().strftime("%Y-%m-%d %H:%M:%S"), "姓名": st.session_state.user_name, "分組": st.session_state.group_id, "題目ID": q.get("題目ID","N/A"), "結果": "❌", "學生答案": _timeout_ans, "分數": "", "任務名稱": st.session_state.get("current_task_name",""), "作答秒數": st.session_state.get(f"_q_start_time_{st.session_state.q_idx}") and round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))}]))
                _load_logs_cached.clear()
                st.rerun()

        # 模式切換
        if task_mode in ("自選", "學生自選"):
            _vm_default = st.session_state.get("vocab_mode_global", "🔤 拆字母")
            if _vm_default not in ["🔤 拆字母", "⌨️ 鍵盤"]:
                _vm_default = "🔤 拆字母"
            vocab_mode = st.radio(
                "輸入模式",
                ["🔤 拆字母", "⌨️ 鍵盤"],
                horizontal=True,
                key="vocab_mode_global",
                disabled=st.session_state.get("show_analysis", False),
                index=["🔤 拆字母", "⌨️ 鍵盤"].index(_vm_default)
            )
            # 模式切換時清除另一模式的輸入記錄
            _prev_mode = st.session_state.get("_vocab_prev_mode")
            if _prev_mode and _prev_mode != vocab_mode:
                _q = st.session_state.q_idx
                if vocab_mode == "⌨️ 鍵盤":
                    # 切換到鍵盤：清除字母池答案
                    st.session_state[f"vocab_ans_{_q}"] = []
                    st.session_state[f"vocab_used_{_q}"] = []
                else:
                    # 切換到字母池：清除鍵盤答案
                    st.session_state[f"vocab_kb_{_q}"] = ""
            st.session_state["_vocab_prev_mode"] = vocab_mode
        else:
            vocab_mode = "🔤 拆字母" if task_mode == "拆字母" else "⌨️ 鍵盤"
        if not vocab_mode:
            vocab_mode = "🔤 拆字母"

        # 初始化字母池（pool_key 含干擾字數，設定改變時自動重建）
        pool_key = f"vocab_pool_{st.session_state.q_idx}_{extra_letters}"
        if pool_key not in st.session_state:
            # 清除同題目舊的 pool（不同干擾字數的）
            for _k in [k for k in st.session_state if k.startswith(f"vocab_pool_{st.session_state.q_idx}_")]:
                if _k != pool_key:
                    del st.session_state[_k]
            _clean_word = _clean_vocab(word)
            # 多單字提示：顯示每個字的字母數
            _word_parts = word.strip().split()
            if len(_word_parts) > 1:
                _hint = " + ".join([f"{len(_clean_vocab(p))}字母" for p in _word_parts])
                st.caption(f"💡 提示：共 {len(_word_parts)} 個字（{_hint}），字母池已去除空格")
            letters = list(_clean_word)
            _random.shuffle(letters)
            candidates = [c for c in _string.ascii_uppercase if c not in _clean_word]
            extra = _random.sample(candidates, min(extra_letters, len(candidates)))
            all_letters = letters + extra
            _random.shuffle(all_letters)
            st.session_state[pool_key] = all_letters
        letter_pool = st.session_state[pool_key]

        ans_key_v = f"vocab_ans_{st.session_state.q_idx}"
        if ans_key_v not in st.session_state:
            st.session_state[ans_key_v] = []

        # ── 拆字母模式 ────────────────────────────────────────────────────
        if "拆字母" in vocab_mode:
            current_ans = st.session_state[ans_key_v]
            # 答案顯示區
            if current_ans:
                letters_html = "".join([
                    f"<span style='display:inline-block;padding:4px 10px;margin:2px;background:#4a90d9;color:white;border-radius:6px;font-size:1.3rem;font-weight:700;'>{c.lower()}</span>"
                    for c in current_ans
                ])
                ans_display = letters_html
            else:
                ans_display = "<span style='color:#aaa;font-size:1rem;'>點選下方字母</span>"
            st.markdown(f"<div style='padding:10px;min-height:50px;background:#f0f4ff;border-radius:8px;'>{ans_display}</div>", unsafe_allow_html=True)

            bc1, bc2, bc3 = st.columns(3)
            if bc1.button("⬅️ 退回一步", use_container_width=True, key=f"vb_back_{st.session_state.q_idx}",
                          disabled=st.session_state.get("show_analysis", False)):
                if current_ans:
                    _removed = st.session_state[ans_key_v].pop()
                    # 只有非空格才從 vocab_used 移除
                    if _removed != ' ':
                        used_st = st.session_state.get(f"vocab_used_{st.session_state.q_idx}", [])
                        if used_st:
                            used_st.pop()
                        st.session_state[f"vocab_used_{st.session_state.q_idx}"] = used_st
                    st.rerun()
            if bc2.button("🗑️ 全部清除", use_container_width=True, key=f"vb_clear_{st.session_state.q_idx}",
                          disabled=st.session_state.get("show_analysis", False)):
                st.session_state[ans_key_v] = []
                st.session_state[f"vocab_used_{st.session_state.q_idx}"] = []
                st.rerun()
            # 多字單字才顯示空格鍵
            if len(_word_parts) > 1:
                if bc3.button("␣ 空格", use_container_width=True, key=f"vb_space_{st.session_state.q_idx}",
                              disabled=st.session_state.get("show_analysis", False)):
                    st.session_state[ans_key_v].append(' ')
                    st.rerun()

            if not st.session_state.get("show_analysis"):
                used_indices = set(st.session_state.get(f"vocab_used_{st.session_state.q_idx}", []))
                # 固定 8 欄，字母位置不移動，已選走的顯示灰色佔位
                NUM_COLS = 8
                cols_v = st.columns(NUM_COLS)
                for i, ltr in enumerate(letter_pool):
                    col = cols_v[i % NUM_COLS]
                    if i in used_indices:
                        col.button("·", key=f"vl_{st.session_state.q_idx}_{i}",
                                   use_container_width=True, disabled=True)
                    else:
                        if col.button(ltr.lower(), key=f"vl_{st.session_state.q_idx}_{i}",
                                      use_container_width=True):
                            st.session_state[ans_key_v].append(ltr)
                            used_st = st.session_state.get(f"vocab_used_{st.session_state.q_idx}", [])
                            used_st.append(i)
                            st.session_state[f"vocab_used_{st.session_state.q_idx}"] = used_st
                            st.rerun()

                # 選完正確字母數後自動對答（不計空格）
                if word and len([c for c in current_ans if c != ' ']) >= len(_clean_vocab(word)) and not st.session_state.get("show_analysis"):
                    is_ok = _clean_vocab("".join(current_ans)) == _clean_vocab(word)
                    st.session_state.update({"current_res": "✅ 正確！" if is_ok else f"❌ 錯誤！正確答案：{word}", "show_analysis": True})
                    st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                    append_to_sheet("logs", pd.DataFrame([{"時間": get_now().strftime("%Y-%m-%d %H:%M:%S"), "姓名": st.session_state.user_name, "分組": st.session_state.group_id, "題目ID": q.get("題目ID","N/A"), "結果": "練習" if st.session_state.get("practice_mode") else ("✅" if is_ok else "❌"), "學生答案": "".join(current_ans), "任務名稱": st.session_state.get("current_task_name",""), "作答秒數": st.session_state.get(f"_q_start_time_{st.session_state.q_idx}") and round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))}]))
                    _load_logs_cached.clear()
                    st.rerun()

        # ── 鍵盤模式 ──────────────────────────────────────────────────────
        else:
            kb_ans = st.session_state.get(f"vocab_kb_{st.session_state.q_idx}", "")
            if not st.session_state.get("show_analysis"):
                # 實體鍵盤輸入框（自動 focus）
                _phys_key = f"vocab_phys_{st.session_state.q_idx}"
                _phys_val = st.text_input(
                    "輸入答案後按 Enter",
                    key=_phys_key,
                    placeholder="在這裡輸入英文，按 Enter 直接送出...",
                )
                # 自動 focus：用 components.v1.html 注入 JS
                import streamlit.components.v1 as _components
                _components.html(
                    """<script>
                    window.parent.document.querySelectorAll('input[type="text"]').forEach(function(el, i, arr){
                        if(i === arr.length - 1) { el.focus(); el.select(); }
                    });
                    </script>""",
                    height=0
                )
                if _phys_val:
                    # 第一次 Enter：直接轉大寫並送出（不需要第二次）
                    _phys_upper = _clean_vocab(_phys_val)
                    is_ok = _phys_upper == _clean_vocab(word)
                    st.session_state[f"vocab_kb_{st.session_state.q_idx}"] = _phys_val.upper()
                    st.session_state.update({
                        "current_res": "✅ 正確！" if is_ok else f"❌ 錯誤！正確答案：{word}",
                        "show_analysis": True
                    })
                    _log_result = "練習" if st.session_state.get("practice_mode") else ("✅" if is_ok else "❌")
                    append_to_sheet("logs", pd.DataFrame([{
                        "時間": get_now().strftime("%Y-%m-%d %H:%M:%S"),
                        "姓名": st.session_state.user_name,
                        "分組": st.session_state.group_id,
                        "題目ID": q.get("題目ID","N/A"),
                        "結果": _log_result,
                        "學生答案": _phys_val.upper(),
                        "任務名稱": st.session_state.get("current_task_name",""), "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))
                    }]))
                    st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                    _load_logs_cached.clear()
                    st.rerun()

                # 顯示已輸入的答案（螢幕鍵盤累積）
                if kb_ans:
                    st.markdown(f"<div style='font-size:1.4rem;letter-spacing:0.1em;padding:10px;background:#f0f4ff;border-radius:8px;'>{kb_ans}</div>", unsafe_allow_html=True)

                _kb_row0, _kb_row1 = st.columns([3, 1])
                if _kb_row1.button("🗑️ 清除", key=f"kb_clear_{st.session_state.q_idx}", use_container_width=True):
                    st.session_state[f"vocab_kb_{st.session_state.q_idx}"] = ""
                    st.rerun()
                keyboard_rows = [list("qwertyuiop"), list("asdfghjkl"), list("zxcvbnm")]
                for row in keyboard_rows:
                    kb_cols = st.columns(len(row))
                    for i, k in enumerate(row):
                        if kb_cols[i].button(k, key=f"kb_{st.session_state.q_idx}_{k}{i}", use_container_width=True):
                            st.session_state[f"vocab_kb_{st.session_state.q_idx}"] = st.session_state.get(f"vocab_kb_{st.session_state.q_idx}", "") + k.upper()
                            st.rerun()
                # 多字單字才顯示空格鍵
                if len(_word_parts) > 1:
                    if st.button("␣  空格", use_container_width=True, key=f"kb_space_{st.session_state.q_idx}"):
                        st.session_state[f"vocab_kb_{st.session_state.q_idx}"] = st.session_state.get(f"vocab_kb_{st.session_state.q_idx}", "") + " "
                        st.rerun()
                kb_current = st.session_state.get(f"vocab_kb_{st.session_state.q_idx}", "")
                if word and len(kb_current) >= len(_clean_vocab(word)) and len(kb_current) > 0:
                    if st.button("✅ 檢查答案", type="primary", use_container_width=True, key=f"kb_check_{st.session_state.q_idx}"):
                        is_ok = _clean_vocab(kb_current) == _clean_vocab(word)
                        st.session_state.update({"current_res": "✅ 正確！" if is_ok else f"❌ 錯誤！正確答案：{word}", "show_analysis": True})
                        _log_result = "練習" if st.session_state.get("practice_mode") else ("✅" if is_ok else "❌")
                        st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                        append_to_sheet("logs", pd.DataFrame([{"時間": get_now().strftime("%Y-%m-%d %H:%M:%S"), "姓名": st.session_state.user_name, "分組": st.session_state.group_id, "題目ID": q.get("題目ID","N/A"), "結果": _log_result, "學生答案": kb_current, "任務名稱": st.session_state.get("current_task_name",""), "作答秒數": st.session_state.get(f"_q_start_time_{st.session_state.q_idx}") and round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))}]))
                        _load_logs_cached.clear()
                        st.rerun()

        # 答對後播放 TTS（自然聲音 + 男聲）
        if st.session_state.get("show_analysis") and is_vocab:
            res = st.session_state.get("current_res", "")
            tts_key_f = f"vocab_tts_f_{st.session_state.q_idx}"
            tts_key_m = f"vocab_tts_m_{st.session_state.q_idx}"
            if "✅" in res:
                st.success(res)
                # 快速答題模式：不載入 TTS，直接顯示對錯結果
                if not _quick_mode:
                    if not st.session_state.get(tts_key_f) or not st.session_state.get(tts_key_m):
                        try:
                            import openai as _oai, base64 as _b64
                            _client = _oai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                            if not st.session_state.get(tts_key_f):
                                tts_f = _client.audio.speech.create(model="tts-1", voice="nova", input=word).content
                                st.session_state[tts_key_f] = _b64.b64encode(tts_f).decode()
                            if not st.session_state.get(tts_key_m):
                                tts_m = _client.audio.speech.create(model="tts-1", voice="onyx", input=word).content
                                st.session_state[tts_key_m] = _b64.b64encode(tts_m).decode()
                            st.rerun()
                        except:
                            pass
                    if st.session_state.get(tts_key_f) or st.session_state.get(tts_key_m):
                        import base64 as _b64, io as _io
                        st.markdown(f"**🔊 {word}**")
                    _tc1, _tc2 = st.columns(2)
                    if st.session_state.get(tts_key_f):
                        _tc1.caption("🎵 自然聲音")
                        _audio_f = st.session_state[tts_key_f]
                        _tc1.markdown(f'''<audio controls playbackRate="0.5" style="width:100%">
                            <source src="data:audio/mpeg;base64,{_audio_f}" type="audio/mpeg">
                        </audio>
                        <script>
                        document.querySelectorAll("audio").forEach(a => {{ a.playbackRate = 0.5; }});
                        </script>''', unsafe_allow_html=True)
                    if st.session_state.get(tts_key_m):
                        _tc2.caption("🎵 男聲")
                        _audio_m = st.session_state[tts_key_m]
                        _tc2.markdown(f'''<audio controls style="width:100%">
                            <source src="data:audio/mpeg;base64,{_audio_m}" type="audio/mpeg">
                        </audio>
                        <script>
                        document.querySelectorAll("audio").forEach(a => {{ a.playbackRate = 0.5; }});
                        </script>''', unsafe_allow_html=True)
            else:
                st.warning(res)


    elif is_mcq:
        mcq_q   = str(q.get('單選題目') or q.get('中文題目') or '【無資料】')
        ans_key = str(q.get("單選答案") or "").strip()
        already_answered = st.session_state.get('show_analysis', False) and not st.session_state.get('practice_mode', False) and not _race_mode

        # 解析選項（從獨立欄位或題目文字）
        mcq_full    = str(q.get('單選題目') or q.get('中文題目') or '')
        parsed_opts = {}
        for opt in ["A", "B", "C", "D"]:
            col_val = str(q.get(f"選項{opt}") or "").strip()
            if col_val and col_val not in ('nan', ''):
                parsed_opts[opt] = col_val
            else:
                next_opts = [o for o in ["A","B","C","D"] if o > opt]
                if next_opts:
                    pattern = rf'\({opt}\)\s*(.*?)\s*\({next_opts[0]}\)'
                else:
                    pattern = rf'\({opt}\)\s*(.*?)$'
                m = re.search(pattern, mcq_full, re.DOTALL)
                parsed_opts[opt] = m.group(1).strip() if m else ""

        # 只顯示題目本文（不含選項），選項另外顯示在下方
        _q_body = re.split(r'\s*\(A\)', mcq_full)[0].strip()
        st.markdown(
            f"<div style='font-size:1.1rem; font-weight:600; padding:8px 0; white-space:pre-wrap;'>"
            f"題目：{_q_body}</div>",
            unsafe_allow_html=True
        )

        cols = st.columns(4)
        # 建立顯示用的打亂選項（每題進入固定，換題重洗）
        _mcq_order_key = f"mcq_order_{st.session_state.q_idx}"
        if _mcq_order_key not in st.session_state:
            import random as _rmc
            _orig_order = [o for o in ["A","B","C","D"] if parsed_opts.get(o,"")]
            _rmc.shuffle(_orig_order)
            st.session_state[_mcq_order_key] = _orig_order
        mcq_order = st.session_state[_mcq_order_key]

        # 建立「顯示標籤→原始選項」對照
        _display_labels = ["A","B","C","D"]
        _disp_to_orig   = {_display_labels[i]: mcq_order[i] for i in range(len(mcq_order))}
        _correct_display = next((d for d, o in _disp_to_orig.items() if o.upper() == ans_key.upper()), ans_key)
        _correct_text    = parsed_opts.get(ans_key.upper(), "")

        # 顯示選項在題目下方（2欄）
        _n_cols = st.session_state.get('mcq_cols', 2)
        _opt_cols = st.columns(_n_cols)
        for i, orig_opt in enumerate(mcq_order):
            disp_label = _display_labels[i]
            opt_text   = parsed_opts.get(orig_opt, "")
            btn_label  = f"({disp_label}) {opt_text}" if opt_text else disp_label
            if _opt_cols[i % _n_cols].button(btn_label, key=f"mcq_{disp_label}",
                              use_container_width=True,
                              disabled=already_answered):
                # 防止重複寫入（同一題同一次只寫一次）
                _mcq_written_key = f"mcq_written_{st.session_state.q_idx}"
                if st.session_state.get(_mcq_written_key):
                    st.rerun()
                    break
                st.session_state[_mcq_written_key] = True
                is_ok = (orig_opt.upper() == ans_key.upper())
                _err_msg = f"❌ 錯誤！正確答案：({_correct_display}) {_correct_text}"
                # 競賽模式：不顯示對錯，直接跳下一題
                if _race_mode:
                    st.session_state.update({
                        "current_res": "✅" if is_ok else "❌",
                        "show_analysis": False
                    })
                st.session_state.update({
                    "current_res": "✅ 正確！" if is_ok else _err_msg,
                    "show_analysis": True
                })
                # 答錯：把此題加到 quiz_list 末尾重考（避免重複加）
                if not is_ok:
                    _qid_now = q.get('題目ID','')
                    _quiz    = st.session_state.get('quiz_list', [])
                    _already_appended = any(
                        r.get('題目ID') == _qid_now and r.get('_retry', False)
                        for r in _quiz
                    )
                    if not _already_appended and _qid_now:
                        _retry_q = dict(q)
                        _retry_q['_retry'] = True
                        _quiz.append(_retry_q)
                        st.session_state['quiz_list'] = _quiz
                # 先寫入再 rerun，確保寫入完成
                write_ok = False
                write_err = ""
                try:
                    import time as _time
                    sb_w   = get_supabase()
                    en_row = _to_en_logs({
                        "時間":    get_now().strftime("%Y-%m-%d %H:%M:%S"),
                        "姓名":    st.session_state.user_name,
                        "分組":    st.session_state.group_id,
                        "題目ID":  q.get('題目ID', 'N/A'),
                        "結果":    "練習" if st.session_state.get("practice_mode") else ("✅" if is_ok else "❌"),
                        "學生答案": f"原始({orig_opt})→顯示({disp_label}) {parsed_opts.get(orig_opt, '')}",
                        "分數":    "",
                        "任務名稱": st.session_state.get("current_task_name", ""),
                        "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time())),
                    })
                    sb_w.table("logs").insert(en_row).execute()
                    _time.sleep(0.5)  # 等 Supabase 確認寫入
                    write_ok = True
                    st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
                    _load_logs_cached.clear()
                except Exception as e:
                    write_err = str(e)
                if not write_ok:
                    st.error(f"❌ 寫入失敗：{write_err}")
                else:
                    st.rerun()
    else:
        # 題目標題（重組題，用 HTML 保留原始空格）
        reorg_q = str(q.get('重組中文題目') or q.get('中文題目') or '【無資料】')
        st.markdown(
            f"<div style='font-size:1.1rem; font-weight:600; padding:8px 0; white-space:pre-wrap;'>"
            f"題目：{reorg_q}</div>",
            unsafe_allow_html=True
        )
        ans_key = str(q.get("重組英文答案") or q.get("英文答案") or "").strip()

        # 重組題介面
        st.info(" ".join(st.session_state.ans) if st.session_state.ans else "請依序點選單字按鈕...")

        _reorder_done = st.session_state.get("show_analysis", False)
        c_ctrl = st.columns(2)
        if c_ctrl[0].button("⬅️ 🟠 退回一步", use_container_width=True, disabled=_reorder_done):
            if st.session_state.ans:
                st.session_state.ans.pop()
                st.session_state.used_history.pop()
                st.rerun()
        if c_ctrl[1].button("🗑️ 🟠 全部清除", use_container_width=True, disabled=_reorder_done):
            st.session_state.update({"ans": [], "used_history": []})
            st.rerun()

        # 單字切分：數字+字母+縮寫視為一字，標點不列入
        # he's / I'm / it's / What's → 一個按鍵；90 → 一個按鍵；逗號句號 → 不顯示
        tk = re.findall(r"[A-Za-z0-9]+(?:['\u2018\u2019][A-Za-z0-9]+)*", ans_key)
        # 只在 shuf 不存在時初始化（不在答題途中強制重算）
        if not st.session_state.get('shuf'):
            st.session_state.shuf = tk.copy()
            random.shuffle(st.session_state.shuf)
        # shuf 和 tk 不一致時（題目不同），才重算
        elif set(st.session_state.shuf) != set(tk):
            st.session_state.shuf = tk.copy()
            st.session_state.ans  = []
            st.session_state.used_history = []
            random.shuffle(st.session_state.shuf)

        bs = st.columns(3)
        for i, t in enumerate(st.session_state.shuf):
            if i not in st.session_state.get('used_history', []):
                if bs[i % 3].button(t, key=f"qb_{i}", use_container_width=True, disabled=_reorder_done):
                    st.session_state.ans.append(t)
                    st.session_state.used_history.append(i)
                    st.rerun()

        if len(st.session_state.ans) == len(tk) and not st.session_state.show_analysis:
            # 全部選完自動對答
            is_ok = clean_string_for_compare("".join(st.session_state.ans)) == clean_string_for_compare(ans_key)
            st.session_state.update({
                "current_res": "✅ 正確！" if is_ok else f"❌ 錯誤！正確答案：{ans_key}",
                "show_analysis": True
            })
            log_data = pd.DataFrame([{
                "時間": get_now().strftime("%Y-%m-%d %H:%M:%S"),
                "姓名": st.session_state.user_name,
                "分組": st.session_state.group_id,
                "題目ID": q.get('題目ID', 'N/A'),
                "結果": "練習" if st.session_state.get("practice_mode") else ("✅" if is_ok else "❌"),
                "學生答案": " ".join(st.session_state.get("ans", [])),
                "任務名稱": st.session_state.get("current_task_name", ""), "作答秒數": round(__import__("time").time() - st.session_state.get(f"_q_start_time_{st.session_state.q_idx}", __import__("time").time()))
            }])
            st.session_state['answered_count'] = st.session_state.get('answered_count', 0) + 1
            append_to_sheet("logs", log_data)
            _load_logs_cached.clear()
            st.rerun()

    if st.session_state.get('show_analysis') and not is_reading and not is_reading_mcq and not is_listen_phon and not is_listen_sent:
        st.warning(st.session_state.current_res)
        # 重組題：顯示 TTS（男聲 + 自然聲音，0.8倍速）
        if not is_mcq and not is_vocab:
            _reorder_ans = str(q.get('重組英文答案') or q.get('英文答案') or '').strip()
            if _reorder_ans and not _quick_mode:
                _tts_f_key = f"reorder_tts_f_{st.session_state.q_idx}"
                _tts_m_key = f"reorder_tts_m_{st.session_state.q_idx}"
                if not st.session_state.get(_tts_f_key) or not st.session_state.get(_tts_m_key):
                    try:
                        import openai as _oai_r, base64 as _b64_r
                        _cli_r = _oai_r.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                        if not st.session_state.get(_tts_f_key):
                            _tts_f = _cli_r.audio.speech.create(model="tts-1", voice="nova", input=_reorder_ans).content
                            st.session_state[_tts_f_key] = _b64_r.b64encode(_tts_f).decode()
                        if not st.session_state.get(_tts_m_key):
                            _tts_m = _cli_r.audio.speech.create(model="tts-1", voice="onyx", input=_reorder_ans).content
                            st.session_state[_tts_m_key] = _b64_r.b64encode(_tts_m).decode()
                        st.rerun()
                    except:
                        pass
                if st.session_state.get(_tts_f_key) or st.session_state.get(_tts_m_key):
                    import base64 as _b64_r
                    st.markdown(f"**🔊 {_reorder_ans}**")
                    _tc1, _tc2 = st.columns(2)
                    if st.session_state.get(_tts_f_key):
                        _tc1.caption("🎵 自然聲音")
                        _tc1.markdown(f'<audio controls style="width:100%"><source src="data:audio/mpeg;base64,{st.session_state[_tts_f_key]}" type="audio/mpeg"></audio><script>document.querySelectorAll("audio").forEach(a=>{{a.playbackRate=0.8;}});</script>', unsafe_allow_html=True)
                    if st.session_state.get(_tts_m_key):
                        _tc2.caption("🎵 男聲")
                        _tc2.markdown(f'<audio controls style="width:100%"><source src="data:audio/mpeg;base64,{st.session_state[_tts_m_key]}" type="audio/mpeg"></audio><script>document.querySelectorAll("audio").forEach(a=>{{a.playbackRate=0.8;}});</script>', unsafe_allow_html=True)
        # 單選題：答題後一律顯示解析
        if is_mcq:
            mcq_analysis = str(q.get('解析') or q.get('單選解析') or '').strip()
            if mcq_analysis:
                st.info(f"📝 解析：{mcq_analysis}")
    st.divider()
    _show_retry = _practice_mode and st.session_state.get('show_analysis', False)
    if _show_retry:
        c_nav = st.columns(3)
    else:
        c_nav = st.columns(2)

    def _clear_q():
        q_idx = st.session_state.q_idx
        st.session_state.update({
            "ans": [], "used_history": [], "shuf": [], "show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None,
            "tts_student": None, "tts_standard": None, "stt_text_shown": "",
        })
        # 清除計時器（用 pop 讓 key 不存在，下題重新計時）
        st.session_state.pop(f"_q_start_time_{q_idx}", None)
        # 清除選項順序快取和錄音評分快取
        for _ok in [f"mcq_order_{q_idx}", f"rm_order_{q_idx}", f"audio_scored_{q_idx}", f"mcq_written_{q_idx}",
                    f"vocab_tts_f_{q_idx}", f"vocab_tts_m_{q_idx}",
                    f"reorder_tts_f_{q_idx}", f"reorder_tts_m_{q_idx}"]:
            st.session_state.pop(_ok, None)
        # 清除該題目的所有 vocab pool（含新格式 vocab_pool_{q_idx}_{extra}）
        for k in list(st.session_state.keys()):
            if k.startswith(f"vocab_pool_{q_idx}") or k.startswith(f"ls_tts_{q_idx}") or k in [
                f"vocab_ans_{q_idx}", f"vocab_used_{q_idx}",
                f"vocab_kb_{q_idx}", f"vocab_tts_{q_idx}",
                f"ls_ans_{q_idx}", f"ls_used_{q_idx}", f"ls_shuf_{q_idx}"
            ]:
                st.session_state.pop(k, None)


    # 快速答題模式：顯示對錯 1 秒後自動跳下一題
    if _quick_mode and st.session_state.get('show_analysis'):
        if st.session_state.get('_quick_shown'):
            # 已顯示結果，執行跳題
            st.session_state.pop('_quick_shown', None)
            _clear_q()
            if st.session_state.q_idx + 1 < len(st.session_state.quiz_list):
                st.session_state.q_idx += 1
                st.session_state.update({"show_analysis": False, "current_res": "", "vocab_start_time": None, "vocab_q_idx": None})
            else:
                st.session_state.update({"quiz_loaded": False, "range_confirmed": False, "quick_mode": False})
            st.rerun()
        else:
            # 剛答完：標記，用 time.sleep(1) 讓畫面顯示結果後再跳
            st.session_state['_quick_shown'] = True
            import time as _tq; _tq.sleep(1)
            st.rerun()

    # 練習模式對答後用3欄，其他用2欄
    # 所有題型都禁止回到上一題（練習模式例外）
    if st.session_state.q_idx > 0:
        if _practice_mode:
            if c_nav[0].button("⬅️ 上一題", use_container_width=True, key="prev_q_btn"):
                _clear_q()
                _prev_idx = st.session_state.q_idx - 1
                for _ok in [
                    f"mcq_order_{_prev_idx}", f"rm_order_{_prev_idx}",
                    f"audio_scored_{_prev_idx}", f"mcq_written_{_prev_idx}",
                    f"ls_ans_{_prev_idx}", f"ls_used_{_prev_idx}", f"ls_shuf_{_prev_idx}",
                    f"vocab_ans_{_prev_idx}", f"vocab_used_{_prev_idx}", f"ls_tts_{_prev_idx}"
                ]:
                    st.session_state.pop(_ok, None)
                st.session_state.q_idx = _prev_idx
                st.session_state.update({
                    "show_analysis": False, "current_res": "",
                    "ans": [], "used_history": [], "shuf": [],
                    "tts_student": None, "stt_text_shown": ""
                })
                st.rerun()
        else:
            c_nav[0].button("⬅️ 上一題", use_container_width=True, disabled=True)

    # 練習模式：對答後顯示「再練習一次」
    if _show_retry:
        if c_nav[1].button("🔁 再練習一次", use_container_width=True, key="retry_q_btn"):
            _clear_q()
            st.session_state.update({
                "show_analysis": False, "current_res": "",
                "ans": [], "used_history": [], "shuf": [],
                "tts_student": None, "stt_text_shown": ""
            })
            st.rerun()
        nxt_col = c_nav[2]
    else:
        nxt_col = c_nav[1]

    nxt_label = "下一題 ➡️" if st.session_state.q_idx + 1 < len(st.session_state.quiz_list) else ("🏆 查看成績" if _race_mode else "🏁 結束練習")
    # Enter 鍵觸發下一題（非快速答題模式）
    if st.session_state.get("show_analysis") and not _quick_mode:
        import streamlit.components.v1 as _cv1_nxt
        _cv1_nxt.html("""<script>
        window.parent.document.addEventListener('keydown', function _nxt(e){
            if(e.key === 'Enter' && !e.repeat){
                var btns = window.parent.document.querySelectorAll('button[kind="primary"]');
                for(var b of btns){
                    if(b.innerText.includes('下一題') || b.innerText.includes('結束練習') || b.innerText.includes('查看成績')){
                        b.click(); break;
                    }
                }
            }
        });
        </script>""", height=0)
    # 快速答題模式：不顯示下一題按鈕（自動跳題）
    if _quick_mode:
        nxt_col.empty()
    elif nxt_col.button(nxt_label, type="primary", use_container_width=True):
        if st.session_state.q_idx + 1 < len(st.session_state.quiz_list):
            next_idx = st.session_state.q_idx + 1
            # 競賽模式：答完自動跳下一題（不等 show_analysis）
            if _race_mode:
                st.session_state.q_idx += 1
                _clear_q()
                st.rerun()
            # 預先載入下一題聽力音檔
            next_q = st.session_state.quiz_list[next_idx]
            if next_q.get('_type') == 'listen_phon':
                _nx_num = str(next_q.get('總編號', '')).strip()
                _nx_sym = str(next_q.get('KK符號', '')).strip()
                _nx_qid = next_q.get('題目ID', '')
                try:
                    _nx_key = f"{int(_nx_num):02d}-{_nx_sym}".lower()
                except:
                    _nx_key = f"{_nx_num}-{_nx_sym}".lower()
                _nx_data_key = f"lp_audio_{next_idx}_{_nx_qid}"
                if not st.session_state.get(_nx_data_key):
                    try:
                        import requests as _req_nx, base64 as _b64_nx
                        _nx_idx = load_audio_file_index()
                        _nx_fid = _nx_idx.get(_nx_key, "")
                        if _nx_fid:
                            _nx_r = _req_nx.get(get_audio_url(_nx_fid), timeout=8)
                            if _nx_r.status_code == 200:
                                st.session_state[_nx_data_key] = _b64_nx.b64encode(_nx_r.content).decode()
                    except:
                        pass
            st.session_state.q_idx += 1
            _clear_q()
            st.rerun()
        else:
            # 競賽模式：顯示成績和排名
            if _race_mode:
                _race_elapsed = time.time() - (st.session_state.get('race_start_time') or time.time())
                _race_min = int(_race_elapsed // 60)
                _race_sec = int(_race_elapsed % 60)
                _race_logs = _get_df_l()
                _task_name = st.session_state.get('current_task_name', '')
                _user      = st.session_state.user_name
                _quiz_ids  = set(q.get('題目ID','') for q in st.session_state.get('quiz_list', []))

                # 本次作答統計（用 race_start_time 篩選本次）
                _race_start = st.session_state.get('race_start_time') or 0
                _my_logs_all = _race_logs[
                    (_race_logs['姓名'] == _user) &
                    (_race_logs['題目ID'].isin(_quiz_ids))
                ] if not _race_logs.empty else pd.DataFrame()
                # 本次：只算 race_start_time 之後的記錄
                if not _my_logs_all.empty and '時間' in _my_logs_all.columns and _race_start:
                    try:
                        import datetime as _dt
                        _race_start_dt = _dt.datetime.fromtimestamp(_race_start)
                        _my_logs = _my_logs_all[pd.to_datetime(_my_logs_all['時間']) >= _race_start_dt]
                    except:
                        _my_logs = _my_logs_all
                else:
                    _my_logs = _my_logs_all

                _total    = len(_quiz_ids)
                _answered = len(set(_my_logs['題目ID'].tolist())) if not _my_logs.empty else 0
                _correct  = len(_my_logs[_my_logs['結果'].fillna('').str.contains('✅', na=False)]) if not _my_logs.empty else 0
                _wrong    = _answered - _correct
                _acc      = f"{int(_correct/_answered*100)}%" if _answered else "0%"
                _race_no  = st.session_state.get('race_attempt', 1)

                st.markdown(f"## 🏆 競賽完成！（第 {_race_no} 次）")
                rc1, rc2, rc3, rc4 = st.columns(4)
                rc1.metric("⏱ 作答時間", f"{_race_min}分{_race_sec:02d}秒")
                rc2.metric("📝 題數", f"{_answered}/{_total}")
                rc3.metric("✅ 答對", _correct)
                rc4.metric("🎯 正確率", _acc)

                # 排名計算（每人每次分開，以 race_no 區分）
                if not _race_logs.empty:
                    _all_stus_logs = _race_logs[_race_logs['題目ID'].isin(_quiz_ids)].copy()
                    # 每人按時間分組成多次參賽（每次間隔超過5分鐘算新一次）
                    _rank_data = []
                    for _stu, _sg in _all_stus_logs.groupby('姓名'):
                        if '時間' not in _sg.columns: continue
                        _sg = _sg.sort_values('時間')
                        try:
                            _times = pd.to_datetime(_sg['時間'])
                            _gaps  = _times.diff().dt.total_seconds().fillna(9999)
                            _attempt_no = (_gaps > 300).cumsum() + 1
                            _sg = _sg.copy()
                            _sg['參賽次'] = _attempt_no
                        except:
                            _sg['參賽次'] = 1

                        for _ano, _ag in _sg.groupby('參賽次'):
                            _s_correct = len(_ag[_ag['結果'].fillna('').str.contains('✅', na=False)])
                            _s_ans     = len(set(_ag['題目ID'].tolist()))
                            _s_acc     = _s_correct / _total if _total else 0
                            try:
                                _t_sorted = pd.to_datetime(_ag['時間']).sort_values()
                                _s_time   = (_t_sorted.iloc[-1] - _t_sorted.iloc[0]).total_seconds() if len(_t_sorted) > 1 else 9999
                            except:
                                _s_time = 9999
                            _rank_data.append({
                                '姓名': _stu,
                                '次數': int(_ano),
                                '答題數': _s_ans,
                                '答對數': _s_correct,
                                '正確率_num': _s_acc,
                                '作答秒數': _s_time,
                            })

                    if _rank_data:
                        _rank_df = pd.DataFrame(_rank_data).sort_values(
                            ['正確率_num', '作答秒數'], ascending=[False, True]
                        ).reset_index(drop=True)
                        _rank_df.index += 1
                        _rank_df['正確率'] = _rank_df['正確率_num'].apply(lambda x: f"{int(x*100)}%")
                        _rank_df['作答時間'] = _rank_df['作答秒數'].apply(
                            lambda x: f"{int(x//60)}分{int(x%60):02d}秒" if x < 9000 else "—"
                        )
                        _rank_df = _rank_df[['姓名','次數','答題數','答對數','正確率','作答時間']]

                        _my_rows = _rank_df[_rank_df['姓名'] == _user]
                        if not _my_rows.empty:
                            st.success(f"🥇 本次正確率排名：第 **{_my_rows.index[0]}** 名 / 共 {len(_rank_df)} 筆")

                        st.markdown("**📊 班級排名（含多次參賽）**")
                        st.dataframe(_rank_df, use_container_width=True, hide_index=False)

                # 按鈕
                _btn1, _btn2 = st.columns(2)
                if _btn1.button("🔁 再次參賽", type="primary", use_container_width=True):
                    st.session_state.update({
                        "quiz_loaded": False, "range_confirmed": False,
                        "race_mode": True,
                        "race_attempt": st.session_state.get('race_attempt', 1) + 1,
                        "race_start_time": None,
                        "show_analysis": False, "current_res": "",
                        "ans": [], "used_history": [], "shuf": [],
                    })
                    st.rerun()
                if _btn2.button("🏁 返回主選單", use_container_width=True):
                    st.session_state.update({
                        "quiz_loaded": False, "range_confirmed": False,
                        "race_mode": False, "race_attempt": 1,
                    })
                    st.rerun()
            else:
                st.session_state.update({"quiz_loaded": False, "range_confirmed": False})
                st.rerun()

    if st.button("🏁 🔴 結束作答 (返回主選單)", use_container_width=True):
        st.session_state.update({"quiz_loaded": False, "range_confirmed": False})
        st.rerun()

    show_version_caption()
