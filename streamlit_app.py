import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium

# --- 1. 頁面設定 ---
st.set_page_config(page_title="雙北公車智慧看板", layout="wide")
st.title("🚌 雙北公車即時智慧看板")

# --- 2. 安全取得 API 金鑰 ---
try:
    CLIENT_ID = st.secrets["TD_CLIENT_ID"] if "TD_CLIENT_ID" in st.secrets else st.secrets["TDX_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["TD_CLIENT_SECRET"] if "TD_CLIENT_SECRET" in st.secrets else st.secrets["TDX_CLIENT_SECRET"]
except:
    st.error("❌ 找不到 API 金鑰，請檢查 Secrets 設定。")
    st.stop()

# --- 3. 工具函式 ---
@st.cache_data(ttl=60)
def get_token():
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    payload = {'grant_type': 'client_credentials', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}
    r = requests.post(auth_url, data=payload)
    return r.json().get('access_token')

def get_bus_data(token, endpoint):
    headers = {'authorization': f'Bearer {token}'}
    combined = []
    # 增加一個簡單的過濾器，確保只抓取必要的欄位，減輕 API 負擔
    for city in ["Taipei", "NewTaipei"]:
        url = f"https://tdx.transportdata.tw/api/basic/v2/Bus/{endpoint}/City/{city}?$format=JSON"
        try:
            res = requests.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list): combined.extend(data)
        except: continue
    return pd.DataFrame(combined)

# --- 4. 主程式 ---
token = get_token()
if token:
    with st.sidebar:
        st.header("🔍 搜尋站點")
        search_query = st.text_input("請輸入站牌名稱", "政大")
        refresh = st.button("🔄 手動更新動態")

    with st.spinner("🔄 資料同步中..."):
        df_stops = get_bus_data(token, "Stop")
        df_eta = get_bus_data(token, "EstimatedTimeOfArrival")

    # --- 診斷區：如果資料為空，顯示偵錯資訊 ---
    if df_stops.empty:
        st.error("📡 站點資料抓取失敗（回傳為空），請確認 API 金鑰權限是否正常。")
    elif 'StopName' not in df_stops.columns:
        st.warning("⚠️ 抓取到了資料，但裡面沒有站名欄位。")
        st.write("目前資料有的欄位：", list(df_stops.columns))
    else:
        # 成功抓到資料，開始處理邏輯
        df_stops['Name_Zh'] = df_stops['StopName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else '')
        df_filtered = df_stops[df_stops['Name_Zh'].str.contains(search_query.strip())].copy()

        if not df_filtered.empty:
            # 兼容性 UID 檢查
            uid_col = next((c for c in ['StopUID', 'StopID'] if c in df_stops.columns), None)
            
            # 建立地圖
            avg_lat = df_filtered['StopPosition'].apply(lambda x: x['PositionLat']).mean()
            avg_lon = df_filtered['StopPosition'].apply(lambda x: x['PositionLon']).mean()
            m = folium.Map(location=[avg_lat, avg_lon], zoom_start=17, tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', attr='Google')

            for name, group in df_filtered.groupby('Name_Zh'):
                lat = group['StopPosition'].apply(lambda x: x['PositionLat']).mean()
                lon = group['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                
                # 抓取該站 ETA
                this_etas = pd.DataFrame()
                if uid_col and uid_col in df_eta.columns:
                    uids = group[uid_col].tolist()
                    this_etas = df_eta[df_eta[uid_col].isin(uids)].copy()

                html_content = f'<div style="width:250px;"><b style="font-size:16px;">{name}</b><hr>'
                if not this_etas.empty:
                    this_etas['Route_Name'] = this_etas['RouteName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
                    unique = this_etas.sort_values('EstimateTime').drop_duplicates(subset=['Route_Name', 'Direction'])
                    for _, r in unique.iterrows():
                        sec = r.get('EstimateTime')
                        dest = r.get('DestinationName', {}).get('Zh_tw', '即時動態') if isinstance(r.get('DestinationName'), dict) else '即時動態'
                        # 時間格式化
                        if pd.isna(sec): status, color = "未發車", "#999"
                        elif sec <= 30: status, color = "進站中", "red"
                        elif sec <= 90: status, color = "將到站", "orange"
                        else: status, color = f"{int(sec//60)}分", "green"
                        
                        html_content += f'<div style="display:flex;justify-content:space-between;margin-bottom:5px;"><span>{r["Route_Name"]} 往 {dest}</span><b style="color:{color};">{status}</b></div>'
                else:
                    html_content += '<p style="color:#666;">無即時動態</p>'
                html_content += '</div>'
                
                folium.Marker([lat, lon], popup=folium.Popup(html_content, max_width=300), icon=folium.Icon(color='orange', icon='bus', prefix='fa')).add_to(m)

            st_folium(m, width=None, height=600, use_container_width=True)
        else:
            st.info(f"🔎 找不到與「{search_query}」相關的站牌。")
