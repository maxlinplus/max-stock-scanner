import streamlit as st
import requests
from bs4 import BeautifulSoup
import time
import re
import os
from datetime import datetime, timedelta, timezone

# --- 財經套件 ---
import yfinance as yf
import pandas as pd

# --- 頁面設定 ---
st.set_page_config(
    page_title="PTT 股市戰情室",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

TW_TZ = timezone(timedelta(hours=8))

def get_tw_time_str():
    return datetime.now(TW_TZ).strftime("%Y-%m-%d_%H-%M-%S")

# --- 檔案處理 ---
KEY_FILE = "api_key.txt"

def load_key():
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except: return ""
    return ""

def save_key(key):
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key)
    except: pass

# ==========================================
# 1. 技術面模組 (yfinance)
# ==========================================
def calculate_technical_indicators(ticker_symbol):
    try:
        stock_id = f"{ticker_symbol}.TW" if not ticker_symbol.endswith(".TW") else ticker_symbol
        stock = yf.Ticker(stock_id)
        df = stock.history(period="3mo")
        
        if df.empty or len(df) < 20:
            return "❌ 無法獲取股價資料 (可能是代號錯誤)"

        # --- 計算指標 ---
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        
        # RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # KD (9)
        low_min = df['Low'].rolling(window=9).min()
        high_max = df['High'].rolling(window=9).max()
        df['RSV'] = (df['Close'] - low_min) / (high_max - low_min) * 100
        df['K'] = df['RSV'].ewm(com=2).mean()
        df['D'] = df['K'].ewm(com=2).mean()

        t = df.iloc[-1]
        # 加入當下抓取時間
        fetch_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
        
        y_info = ""
        kd_sig = ""
        
        if len(df) > 1:
            y = df.iloc[-2]
            change = t['Close'] - y['Close']
            pct = (change / y['Close']) * 100
            
            vol_change = t['Volume'] - y['Volume']
            vol_str = f"增加 {int(vol_change/1000)}" if vol_change > 0 else f"減少 {int(abs(vol_change)/1000)}"
            
            y_info = f"""
            - 漲跌: {change:.2f} ({pct:.2f}%)
            - 量能: 較昨日{vol_str}張
            """
            
            if y['K'] < y['D'] and t['K'] > t['D']: kd_sig = "🔥 黃金交叉 (轉強訊號)"
            elif y['K'] > y['D'] and t['K'] < t['D']: kd_sig = "⚠️ 死亡交叉 (轉弱訊號)"
        else:
            y_info = "(無昨日資料)"

        report = f"""
        【官方技術數據 (抓取時間: {fetch_time})】
        1. 價格與量能：
           - 收盤價: {t['Close']:.2f}
           {y_info}
           - 今日成交量: {int(t['Volume']/1000)} 張

        2. 均線狀態：
           - MA5 (週線): {t['MA5']:.2f} ({'站上' if t['Close'] > t['MA5'] else '跌破'})
           - MA20 (月線): {t['MA20']:.2f}
           - MA60 (季線): {t['MA60']:.2f}

        3. 技術指標：
           - RSI (14): {t['RSI']:.2f} ({'過熱' if t['RSI']>70 else '超賣' if t['RSI']<30 else '中性'})
           - KD (9): K={t['K']:.2f}, D={t['D']:.2f}
           - 訊號: {kd_sig if kd_sig else '無特殊交叉'}
        """
        return report

    except Exception as e:
        return f"❌ 技術指標計算錯誤: {str(e)}"

# ==========================================
# 2. PTT 爬蟲模組 (推文完整版)
# ==========================================
def get_ptt_soup(url):
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.ptt.cc/'}
    cookies = {'over18': '1'}
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        if response.status_code == 200:
            return BeautifulSoup(response.text, 'html.parser')
    except: pass
    return None

def extract_ptt_timestamp(url):
    match = re.search(r'M\.(\d+)', url)
    return int(match.group(1)) if match else 0

def parse_ptt_article(url):
    soup = get_ptt_soup(url)
    if not soup: return None
    try:
        meta = soup.find_all('span', class_='article-meta-value')
        if not meta or len(meta) < 4: return None
        
        author = meta[0].text.strip()
        title = meta[2].text.strip()
        date = meta[3].text.strip()
        main = soup.find(id="main-content")
        
        pushes = main.find_all('div', class_='push')
        p_cnt = sum(1 for p in pushes if '推' in p.text)
        b_cnt = sum(1 for p in pushes if '噓' in p.text)
        
        comments_list = []
        for p in pushes:
            try:
                tag = p.find('span', class_='push-tag').text.strip()
                user = p.find('span', class_='push-userid').text.strip()
                content = p.find('span', class_='push-content').text.strip().replace(': ', '')
                ip_time_span = p.find('span', class_='push-ipdatetime')
                raw_time = ip_time_span.text.strip() if ip_time_span else ""
                clean_time = " ".join(raw_time.split()) 
                if not clean_time: clean_time = "No_Time"
                
                comments_list.append(f"[{clean_time}] {tag} {user} : {content}")
            except: continue

        for t in main.find_all(['div', 'span'], class_=['article-meta-tag', 'article-meta-value', 'push', 'richcontent']): 
            t.decompose()
        
        content = main.get_text().strip()
        comments_text = "\n".join(comments_list)
        
        full_text = f"\n{'='*40}\n[PTT] 標題: {title}\n作者: {author}\n時間: {date}\n互動: 推{p_cnt}/噓{b_cnt}\n\n[內文]:\n{content}\n\n[推文紀錄 ({len(comments_list)}則)]:\n{comments_text}\n"
        
        return full_text, title, date
    except: return None

# ==========================================
# 3. AI 分析模組
# ==========================================
def find_valid_model(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'models' in data:
                valid_models = [m['name'].replace('models/', '') for m in data['models'] if 'generateContent' in m.get('supportedGenerationMethods', [])]
                if "gemini-1.5-pro" in valid_models: return "gemini-1.5-pro"
                if "gemini-1.0-pro" in valid_models: return "gemini-1.0-pro"
                if "gemini-1.5-flash" in valid_models: return "gemini-1.5-flash"
                if valid_models: return valid_models[0]
        return "gemini-1.5-flash" 
    except: return "gemini-1.5-flash"

def call_gemini_api(api_key, prompt):
    model_name = find_valid_model(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    response = requests.post(url, headers=headers, json=data, timeout=120)
    if response.status_code == 200:
        return response.json()['candidates'][0]['content']['parts'][0]['text'], model_name
    else:
        raise Exception(f"API Error {response.status_code}")

# ==========================================
# 4. Streamlit UI
# ==========================================

with st.sidebar:
    st.header("⚙️ 系統設定")
    saved_key = load_key()
    api_key_input = st.text_input("Gemini API Key", value=saved_key, type="password")
    if api_key_input and api_key_input != saved_key:
        save_key(api_key_input)
        st.toast("Key 已儲存", icon="✅")
    st.session_state.api_key = api_key_input

    keyword_input = st.text_input("股票代號 (例: 2330)", value="2330")
    limit_ptt = st.number_input("PTT 篇數", min_value=1, max_value=50, value=15)
    
    st.divider()

st.title("📊 PTT 股市戰情室 (Final Version)")
st.markdown("整合 **官方技術數據** 與 **PTT 散戶情緒**，快速判斷多空。")

# 狀態初始化
if "scraped_data" not in st.session_state: st.session_state.scraped_data = ""
if "tech_report" not in st.session_state: st.session_state.tech_report = ""
if "logs" not in st.session_state: st.session_state.logs = []

# --- 搜尋按鈕 (只負責更新資料，不負責顯示) ---
if st.button("🚀 啟動戰情分析", use_container_width=True):
    # 清空舊資料
    st.session_state.scraped_data = ""
    st.session_state.tech_report = ""
    st.session_state.logs = []
    
    stock_code = re.sub(r"\D", "", keyword_input)
    if not stock_code:
        st.error("請輸入正確代號")
        st.stop()

    # 1. 抓技術指標
    with st.spinner("計算技術指標中..."):
        tech_report = calculate_technical_indicators(stock_code)
        st.session_state.tech_report = tech_report

    # 2. 抓 PTT
    keywords = keyword_input.split()
    all_text_data = ""
    ptt_links = set()
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    status_text.text("搜尋 PTT 中...")
    
    for kw in keywords:
        soup = get_ptt_soup(f"https://www.ptt.cc/bbs/Stock/search?q={kw}")
        if soup:
            divs = soup.find_all('div', class_='title')
            if divs:
                for t in divs:
                    a = t.find('a')
                    if a: ptt_links.add("https://www.ptt.cc" + a['href'])
        time.sleep(0.2)
    
    sorted_links = sorted(list(ptt_links), key=extract_ptt_timestamp, reverse=True)[:limit_ptt]
    
    if not sorted_links:
        st.warning("❌ 找不到相關文章")
    else:
        for i, link in enumerate(sorted_links):
            res = parse_ptt_article(link)
            if res:
                text, title, date = res
                all_text_data += text
                # 存入 logs 以便稍後顯示
                st.session_state.logs.append(f"📄 [{date}] {title}")
            
            progress = (i + 1) / len(sorted_links)
            progress_bar.progress(progress)
            status_text.text(f"下載中... {int(progress*100)}%")
            time.sleep(0.1)
        
        st.session_state.scraped_data = all_text_data
        status_text.success(f"🎉 搜尋完成！")
        time.sleep(1) # 讓使用者看到完成訊息
        status_text.empty() # 清除狀態文字

# --- 顯示區域 (獨立於按鈕之外，確保不會消失) ---
if st.session_state.tech_report or st.session_state.scraped_data:
    col1, col2 = st.columns([1, 1]) 
    
    # 左欄：技術分析
    with col1:
        st.subheader("1. 官方技術診斷")
        st.info(st.session_state.tech_report)

    # 右欄：PTT 列表
    with col2:
        st.subheader(f"2. PTT 輿情列表")
        if st.session_state.logs:
            with st.container(height=400): # 固定高度卷軸，避免頁面太長
                for log in st.session_state.logs:
                    st.text(log)
        else:
            st.warning("無相關 PTT 文章")

    st.divider()
    
    # 底部按鈕區
    btn_col1, btn_col2 = st.columns(2)
    
    with btn_col1:
        if st.button("🧠 AI 戰情官深度解讀", type="primary", use_container_width=True):
            if not st.session_state.api_key:
                st.warning("請先輸入 API Key")
            else:
                with st.spinner("🤖 AI 正在比對「技術訊號」與「散戶情緒 (含推文)」..."):
                    try:
                        prompt = f"""
                        角色：資深操盤手。
                        任務：分析 {keyword_input} 走勢。
                        
                        【資料來源】
                        1. [官方技術面]:
                        {st.session_state.tech_report}
                        
                        2. [PTT 輿情 (含推文爭論)]:
                        {st.session_state.scraped_data[:100000]}
                        
                        請輸出分析報告：
                        1. 【多空溫度計】(0-100分)
                        2. 【技術面診斷】：(引用 MA, RSI, KD, 量能，判斷目前是多頭、空頭還是盤整)。
                        3. 【散戶共識】：(請引用 PTT 推文內容，鄉民目前看多還是看空？有無反串？)。
                        4. 【訊號 vs 輿情】：真實技術指標有支撐鄉民的看法嗎？
                        5. 【操作建議】：基於技術面事實給出建議。
                        """
                        result, model = call_gemini_api(st.session_state.api_key, prompt)
                        st.subheader("📊 戰情分析報告")
                        st.markdown(result)
                    except Exception as e:
                        st.error(str(e))
                        
    with btn_col2:
        timestamp = get_tw_time_str()
        safe_kw = re.sub(r'[\\/*?:"<>|]', "_", keyword_input.replace(" ", "_"))
        
        st.download_button(
            label="📥 下載完整資料 (.txt)",
            data=f"{st.session_state.tech_report}\n\n{'='*20}\n\n{st.session_state.scraped_data}".encode("utf-8-sig"),
            file_name=f"report_{safe_kw}_{timestamp}.txt",
            mime="text/plain",
            use_container_width=True
        )