import streamlit as st
import requests
from bs4 import BeautifulSoup
import time
import re
import os
from datetime import datetime

# --- 頁面設定 ---
st.set_page_config(
    page_title="PTT 股市反指標觀測站",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 檔案處理 (自動記憶功能) ---
KEY_FILE = "api_key.txt"

def load_key():
    """從檔案讀取 Key"""
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except:
            return ""
    return ""

def save_key(key):
    """將 Key 寫入檔案"""
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key)
    except:
        pass

# --- 核心函數 ---
def get_soup(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.ptt.cc/bbs/Stock/index.html',
            'Connection': 'keep-alive'
        }
        cookies = {'over18': '1'}
        response = requests.get(url, cookies=cookies, headers=headers, timeout=10)
        if response.status_code != 200: return None
        return BeautifulSoup(response.text, 'html.parser')
    except: return None

def extract_timestamp(url):
    match = re.search(r'M\.(\d+)', url)
    return int(match.group(1)) if match else 0

def parse_article(url):
    soup = get_soup(url)
    if not soup: return None
    try:
        meta = soup.find_all('span', class_='article-meta-value')
        if not meta or len(meta) < 4: return None
        
        author = meta[0].text.strip()
        title = meta[2].text.strip()
        date = meta[3].text.strip()
        main_content = soup.find(id="main-content")
        
        pushes = main_content.find_all('div', class_='push')
        p_cnt = sum(1 for p in pushes if '推' in p.text)
        b_cnt = sum(1 for p in pushes if '噓' in p.text)
        
        for t in main_content.find_all(['div', 'span'], class_=['article-meta-tag', 'article-meta-value', 'push', 'richcontent']): 
            t.decompose()
        
        content = main_content.get_text().strip()[:5000]
        formatted_text = f"\n{'='*30}\n📄 標題: {title}\n📅 時間: {date}\n👤 作者: {author}\n📊 互動: 推 {p_cnt} | 噓 {b_cnt}\n\n{content}\n"
        return formatted_text, title, date
    except: return None

def find_valid_model(api_key):
    """偵測可用模型 (Pro 優先)"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'models' in data:
                valid_models = [m['name'].replace('models/', '') for m in data['models'] if 'generateContent' in m.get('supportedGenerationMethods', [])]
                # 優先順序
                for m in valid_models:
                    if "gemini-1.5-pro" in m: return m
                for m in valid_models:
                    if "gemini-1.0-pro" in m: return m
                for m in valid_models:
                    if "gemini-1.5-flash" in m: return m
                if valid_models: return valid_models[0]
        return "gemini-1.5-flash" 
    except: return "gemini-1.5-flash"

def call_gemini_api(api_key, prompt):
    model_name = find_valid_model(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    response = requests.post(url, headers=headers, json=data, timeout=60)
    if response.status_code == 200:
        return response.json()['candidates'][0]['content']['parts'][0]['text'], model_name
    else:
        raise Exception(f"API Error {response.status_code}: {response.text}")

# --- 網頁介面邏輯 ---

# 側邊欄：設定區
with st.sidebar:
    st.header("⚙️ 參數設定")
    
    # 自動記憶邏輯
    saved_key = load_key()
    api_key_input = st.text_input("Gemini API Key", value=saved_key, type="password", help="輸入後系統會自動儲存")
    if api_key_input and api_key_input != saved_key:
        save_key(api_key_input)
        st.toast("💾 API Key 已自動儲存！", icon="✅")
    
    st.session_state.api_key = api_key_input

    keyword_input = st.text_input("股票代號 (空白隔開)", value="2330 台積電")
    limit_count = st.number_input("下載篇數", min_value=1, max_value=20, value=5)
    
    st.divider()
    if saved_key:
        st.caption("✅ 目前已載入自動儲存的 Key")
    else:
        st.caption("💡 首次輸入後，系統將自動建立 `api_key.txt` 幫您記住。")

# 主畫面
st.title("📈 PTT 股市反指標觀測站")
st.markdown("結合 **PTT 爬蟲** 與 **Gemini Pro** 模型，自動判讀散戶情緒。")

# 初始化 session state
if "scraped_data" not in st.session_state:
    st.session_state.scraped_data = ""
if "logs" not in st.session_state:
    st.session_state.logs = []

# 按鈕：開始搜尋
if st.button("🚀 開始搜尋 & 下載", use_container_width=True):
    st.session_state.logs = [] 
    st.session_state.scraped_data = ""
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    keywords = keyword_input.split()
    links = set()
    
    # 1. 搜尋連結
    for kw in keywords:
        status_text.text(f"正在搜尋: {kw}...")
        soup = get_soup(f"https://www.ptt.cc/bbs/Stock/search?q={kw}")
        if soup:
            for t in soup.find_all('div', class_='title'):
                a = t.find('a')
                if a: links.add("https://www.ptt.cc" + a['href'])
    
    if not links:
        st.error("❌ 找不到相關文章")
    else:
        # 2. 排序與下載
        sorted_links = sorted(list(links), key=extract_timestamp, reverse=True)[:limit_count]
        status_text.text(f"找到 {len(sorted_links)} 篇，開始下載內容...")
        
        full_text = ""
        for i, link in enumerate(sorted_links):
            res = parse_article(link)
            if res:
                text, title, date = res
                full_text += text
                st.session_state.logs.append(f"✅ [{date}] {title}")
            else:
                st.session_state.logs.append(f"❌ 讀取失敗: {link}")
            
            progress_bar.progress((i + 1) / len(sorted_links))
            time.sleep(0.2)
            
        st.session_state.scraped_data = full_text
        st.success("🎉 爬蟲執行完成！")

# 顯示抓取紀錄
if st.session_state.logs:
    with st.expander("📋 查看已抓取的文章列表", expanded=True):
        for log in st.session_state.logs:
            st.text(log)

# --- 動作區塊：下載與分析 ---
if st.session_state.scraped_data:
    st.divider()
    st.subheader("🛠️ 下一步操作")
    
    # 使用 columns 讓按鈕並排
    col1, col2 = st.columns([1, 1])
    
    with col1:
        # 分析按鈕
        if st.button("🤖 呼叫 Gemini 進行分析", type="primary", use_container_width=True):
            if not st.session_state.api_key:
                st.warning("請先在左側輸入 Gemini API Key")
            else:
                with st.spinner("🧠 AI 正在閱讀文章並分析散戶心理..."):
                    try:
                        prompt = f"""
                        角色設定：你是一位精通台股散戶心理學與行為金融學的資深交易員。
                        任務：分析以下 PTT 股板討論內容。
                        
                        請輸出簡潔報告：
                        1. 【情緒溫度計】 (0-100分)：0=極度恐慌(買點)，100=極度狂熱(賣點)。
                        2. 【散戶共識】：大家現在主要在看多還是看空？理由是什麼？
                        3. 【反指標操作建議】：基於「人多的地方不要去」原則，現在適合進場、出場還是觀望？
                        4. 【關鍵證據】：引用 1-2 則最具代表性的推文或內文。

                        資料內容：
                        {st.session_state.scraped_data[:40000]}
                        """
                        
                        result, model_used = call_gemini_api(st.session_state.api_key, prompt)
                        
                        st.divider()
                        st.subheader(f"📊 分析報告 (使用模型: {model_used})")
                        st.markdown(result)
                        
                    except Exception as e:
                        st.error(f"分析失敗: {str(e)}")

    with col2:
        # 下載按鈕
        # 自動產生檔名: ptt_stock_YYYYMMDD_HHMMSS.txt
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_kw = re.sub(r'[\\/*?:"<>|]', "_", keyword_input.replace(" ", "_"))
        filename = f"ptt_{safe_kw}_{timestamp}.txt"
        
        st.download_button(
            label="📥 下載文字檔 (.txt)",
            data=st.session_state.scraped_data,
            file_name=filename,
            mime="text/plain",
            use_container_width=True
        )

# 頁尾
st.divider()
st.caption("Powered by Streamlit & Google Gemini API")