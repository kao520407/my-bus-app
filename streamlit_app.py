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
    CLIENT_ID = st.secrets["TDX_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["TDX_CLIENT_SECRET"]
except:
    st.error("❌ 找不到 API 金鑰，請在 Secrets 中設定。")
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
    for city in ["Taipei", "NewTaipei"]:
        url = f"https://tdx.transportdata.tw/api/basic/v2/Bus/{endpoint}/City/{city}?$format=JSON"
        try:
            res = requests.get(url, headers=headers)
            if res.status_code == 200:
                combined.extend(res.json())
        except: continue
    return pd.DataFrame(combined)

# --- 4. 主程式 ---
token = get_token()
if token:
    with st.sidebar:
        st.header("🔍 搜尋站點")
        search_query = st.text_input("請輸入站牌名稱", "政大")
        st.info("💡 站點資料載入中，請稍候...")

    with st.spinner("🔄 正在讀取雙北即時公車資訊..."):
        df_stops = get_bus_data(token, "Stop")
        df_eta = get_bus_data(token, "EstimatedTimeOfArrival")

    # --- 關鍵修正：安全檢查欄位 ---
    if not df_stops.empty and 'StopName' in df_stops.columns:
        # 提取站名
        df_stops['Name_Zh'] = df_stops['StopName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else '')
        df_filtered = df_stops[df_stops['Name_Zh'].str.contains(search_query.strip())].copy()

        if not df_filtered.empty:
            # 找出 UID 欄位到底是哪個 (可能是 StopUID 或 StopID)
            uid_col = 'StopUID' if 'StopUID' in df_stops.columns else 'StopID' if 'StopID' in df_stops.columns else None
            
            avg_lat = df_filtered['StopPosition'].apply(lambda x: x['PositionLat']).mean()
            avg_lon = df_filtered['StopPosition'].apply(lambda x: x['PositionLon']).mean()
            m = folium.Map(location=[avg_lat, avg_lon], zoom_start=17, tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', attr='Google')

            for name, group in df_filtered.groupby('Name_Zh'):
                lat = group['StopPosition'].apply(lambda x: x['PositionLat']).mean()
                lon = group['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                
                # 如果找不到 UID 欄位，就顯示警告
                if uid_col and uid_col in df_eta.columns:
                    uids = group[uid_col].tolist()
                    etas = df_eta[df_eta[uid_col].isin(uids)].copy()
                else:
                    etas = pd.DataFrame()

                html_body = f'<div style="width:250px;font-family:sans-serif;"><div style="background:#2c3e50;color:#ffce00;padding:8px;text-align:center;font-weight:bold;">{name}</div>'
                
                if not etas.empty:
                    # 統一將路線名轉文字
                    etas['RouteName_Zh'] = etas['RouteName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
                    unique_etas = etas.sort_values('EstimateTime').drop_duplicates(subset=['RouteName_Zh', 'Direction'])
                    
                    for _, row in unique_etas.iterrows():
                        r_name = row['RouteName_Zh']
                        dest = row.get('DestinationName', {}).get('Zh_tw', '即時動態') if isinstance(row.get('DestinationName'), dict) else '即時動態'
                        sec = row.get('EstimateTime')
                        
                        if pd.isna(sec): t, c = "未發車", "#9ca3af"
                        elif sec <= 30: t, c = "進站中", "#dc2626"
                        elif sec <= 90: t, c = "將到站", "#ea580c"
                        else: t, c = f"{int(sec//60)}分", "#16a34a"

                        html_body += f'''
                        <div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #eee;align-items:center;">
                            <div><b>{r_name}</b><br><small style="color:#666;">往 {dest}</small></div>
                            <div style="color:{c};font-weight:bold;">{t}</div>
                        </div>'''
                else:
                    html_body += '<div style="padding:20px;text-align:center;color:#999;">目前無即時班次</div>'
                
                html_body += '</div>'
                folium.Marker([lat, lon], popup=folium.Popup(html_body, max_width=300), icon=folium.Icon(color='orange', icon='bus', prefix='fa')).add_to(m)

            st_folium(m, width=None, height=600, use_container_width=True)
        else:
            st.warning(f"🔎 找不到「{search_query}」相關站牌。")
    else:
        st.error("📡 無法讀取站點欄位，請檢查 API 回傳資料。")
