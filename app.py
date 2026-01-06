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
        except: return ""
    return ""

def save_key(key):
    """將 Key 寫入檔案"""
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key)
    except: pass

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
        
        # --- 抓取推文 (含時間，抓取全部) ---
        pushes = main_content.find_all('div', class_='push')
        
        p_cnt = sum(1 for p in pushes if '推' in p.text)
        b_cnt = sum(1 for p in pushes if '噓' in p.text)
        
        comments_list = []
        for p in pushes:
            try:
                tag = p.find('span', class_='push-tag').text.strip()
                user = p.find('span', class_='push-userid').text.strip()
                content = p.find('span', class_='push-content').text.strip().replace(': ', '')
                
                # 抓取 IP/時間
                ip_time_span = p.find('span', class_='push-ipdatetime')
                ip_time = ip_time_span.text.strip() if ip_time_span else ""
                
                comments_list.append(f"[{ip_time}] {tag} {user}: {content}")
            except: continue

        # 清理主文 HTML
        for t in main_content.find_all(['div', 'span'], class_=['article-meta-tag', 'article-meta-value', 'push', 'richcontent']): 
            t.decompose()
        
        body_content = main_content.get_text().strip()
        
        # 組合全文：標題 + 內文 + 所有推文 (無限制)
        comments_text = "\n".join(comments_list)
        
        formatted_text = f"\n{'='*30}\n📄 標題: {title}\n📅 時間: {date}\n👤 作者: {author}\n📊 互動: 推 {p_cnt} | 噓 {b_cnt}\n\n[內文]:\n{body_content}\n\n[完整推文 ({len(comments_list)}則)]:\n{comments_text}\n"
        return formatted_text, title, date
    except: return None

# --- AI 呼叫函數 (自動備援 + 長時間等待) ---
def find_valid_model(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'models' in data:
                valid_models = [m['name'].replace('models/', '') for m in data['models'] if 'generateContent' in m.get('supportedGenerationMethods', [])]
                
                # 優先使用 Pro，若無則用 Flash
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
    
    # 設定超長 timeout (300秒)，因為 50 篇文章 + 全推文 資料量很大
    timeout = 300
    
    response = requests.post(url, headers=headers, json=data, timeout=timeout)
    if response.status_code == 200:
        return response.json()['candidates'][0]['content']['parts'][0]['text'], model_name
    else:
        # 如果 Pro 爆了 (429)，自動降級嘗試 Flash
        if response.status_code == 429 and "flash" not in model_name:
            fallback_model = "gemini-1.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{fallback_model}:generateContent?key={api_key}"
            response = requests.post(url, headers=headers, json=data, timeout=timeout)
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text'], fallback_model
        
        raise Exception(f"API Error {response.status_code}: {response.text}")

# --- 網頁介面邏輯 ---

with st.sidebar:
    st.header("⚙️ 參數設定")
    saved_key = load_key()
    api_key_input = st.text_input("Gemini API Key", value=saved_key, type="password")
    if api_key_input and api_key_input != saved_key:
        save_key(api_key_input)
        st.toast("💾 API Key 已儲存", icon="✅")
    st.session_state.api_key = api_key_input

    keyword_input = st.text_input("股票代號 (空白隔開)", value="2330 台積電")
    
    # --- 您的要求：上限 50，預設 10 ---
    limit_count = st.number_input("下載篇數", min_value=1, max_value=50, value=10)
    
    st.divider()
    if saved_key:
        st.caption("✅ 目前已載入自動儲存的 Key")

st.title("🛡️ PTT 股市反指標觀測站 (V20 終極版)")
st.markdown("已啟用 **全推文抓取** 與 **50篇大量分析** 模式。")

if "scraped_data" not in st.session_state: st.session_state.scraped_data = ""
if "logs" not in st.session_state: st.session_state.logs = []

if st.button("🚀 開始搜尋 & 下載", use_container_width=True):
    st.session_state.logs = [] 
    st.session_state.scraped_data = ""
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    keywords = keyword_input.split()
    links = set()
    
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
        st.success(f"🎉 下載完成！已抓取 {len(full_text)} 字元 (含所有推文)。")

if st.session_state.logs:
    with st.expander("📋 查看已抓取的文章列表", expanded=True):
        for log in st.session_state.logs: st.text(log)

if st.session_state.scraped_data:
    st.divider()
    st.subheader("🛠️ 下一步操作")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("🤖 呼叫 Gemini 進行分析", type="primary", use_container_width=True):
            if not st.session_state.api_key:
                st.warning("請先輸入 API Key")
            else:
                with st.spinner("🧠 資料量較大，AI 正在閱讀並分析 (可能需時 1-3 分鐘)..."):
                    try:
                        # 將 token 限制放寬到 20 萬字，確保能吃下 50 篇的全推文
                        prompt = f"""
                        角色設定：你是一位精通台股散戶心理學與行為金融學的資深交易員。
                        任務：分析以下 PTT 股板討論內容 (這是完整的推文串，請特別注意情緒的連續變化與多空論戰)。
                        
                        請輸出簡潔報告：
                        1. 【情緒溫度計】 (0-100分)：0=極度恐慌(買點)，100=極度狂熱(賣點)。
                        2. 【散戶共識】：大家現在主要在看多還是看空？有無反串？
                        3. 【反指標操作建議】：基於「人多的地方不要去」原則，現在適合進場、出場還是觀望？
                        4. 【關鍵證據】：引用 1-2 則最具代表性的推文 (請包含時間點)。

                        資料內容：
                        {st.session_state.scraped_data[:200000]}
                        """
                        result, model_used = call_gemini_api(st.session_state.api_key, prompt)
                        
                        st.divider()
                        st.subheader(f"📊 分析報告 (使用模型: {model_used})")
                        st.markdown(result)
                    except Exception as e:
                        st.error(f"分析失敗: {str(e)}")

    with col2:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_kw = re.sub(r'[\\/*?:"<>|]', "_", keyword_input.replace(" ", "_"))
        st.download_button(
            label="📥 下載完整文字檔 (.txt)",
            data=st.session_state.scraped_data,
            file_name=f"ptt_{safe_kw}_{timestamp}.txt",
            mime="text/plain",
            use_container_width=True
        )

st.divider()
st.caption("Powered by Streamlit & Google Gemini API")