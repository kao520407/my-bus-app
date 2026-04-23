import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium

# --- 1. 頁面設定 ---
st.set_page_config(page_title="雙北公車智慧看板", layout="wide")

st.title("🚌 雙北公車即時智慧看板")
st.markdown("輸入站牌名稱，即時掌握去回程公車動態與完整路線。")

# --- 2. 安全取得 API 金鑰 ---
try:
    CLIENT_ID = st.secrets["TDX_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["TDX_CLIENT_SECRET"]
except:
    st.error("❌ 找不到 API 金鑰，請在 Secrets 中設定。")
    st.stop()

# --- 3. 工具函式 ---
@st.cache_data(ttl=3600)
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
        res = requests.get(url, headers=headers)
        if res.status_code == 200: combined.extend(res.json())
    return pd.DataFrame(combined)

# --- 4. 側邊欄搜尋 ---
with st.sidebar:
    st.header("🔍 搜尋站點")
    search_query = st.text_input("請輸入站牌名稱（如：福泰里、政大）", "政大")
    st.info("💡 提示：若出現錯誤，請確認站名是否正確。")

# --- 5. 主程式邏輯 ---
token = get_token()
if token:
    with st.spinner("📡 正在抓取資料..."):
        df_stops = get_bus_data(token, "Stop")
        df_eta = get_bus_data(token, "EstimatedTimeOfArrival")
        df_stop_of_route = get_bus_data(token, "StopOfRoute")
    
    # 過濾站點
    df_stops['Name_Zh'] = df_stops['StopName'].apply(lambda x: x['Zh_tw'] if isinstance(x, dict) else "")
    df_filtered = df_stops[df_stops['Name_Zh'].str.contains(search_query.strip())].copy()

    if not df_filtered.empty:
        avg_lat = df_filtered['StopPosition'].apply(lambda x: x['PositionLat']).mean()
        avg_lon = df_filtered['StopPosition'].apply(lambda x: x['PositionLon']).mean()
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=17, tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', attr='Google')

        for name, group in df_filtered.groupby('Name_Zh'):
            all_uids = group['StopUID'].tolist()
            # 關鍵防錯：確保 ETA 有資料才進行 drop_duplicates
            etas = df_eta[df_eta['StopUID'].isin(all_uids)].copy()
            
            if not etas.empty:
                unique_etas = etas.drop_duplicates(subset=['RouteName', 'Direction'])
                lat, lon = group['StopPosition'].apply(lambda x: x['PositionLat']).mean(), group['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                
                # (這部分維持之前的 HTML 產生邏輯...)
                tab_id = f"tab_{name.replace(' ', '')}"
                content_html = {"0": "", "1": ""}
                
                for _, row in unique_etas.iterrows():
                    d_code = str(row['Direction'])
                    route = row['RouteName']['Zh_tw']
                    sec = row.get('EstimateTime')
                    dest = row.get('DestinationName', {}).get('Zh_tw', '即時動態')
                    t, b, f = ("進站中", "#fff5f5", "#e53e3e") if not pd.isna(sec) and sec <= 30 else (f"{int(sec//60)} 分", "#f0fff4", "#38a169") if not pd.isna(sec) else ("未發車", "#f7fafc", "#a0aec0")

                    row_html = f'<details style="margin-bottom:8px;border:1px solid #e2e8f0;border-radius:8px;"><summary style="padding:10px;cursor:pointer;display:flex;justify-content:space-between;outline:none;"><div><b>{route}</b><br><small>往 {dest}</small></div><div style="background:{b};color:{f};padding:4px 10px;border-radius:12px;">{t}</div></summary><div style="padding:10px;font-size:11px;border-top:1px solid #eee;">'
                    
                    # 路線細節防錯
                    r_stops = df_stop_of_route[(df_stop_of_route['RouteUID'] == row['RouteUID']) & (df_stop_of_route['Direction'] == row['Direction'])]
                    if not r_stops.empty:
                        for s in r_stops.iloc[0]['Stops']:
                            s_n = s['StopName']['Zh_tw']
                            row_html += f"<div>• {s_n}</div>"
                    row_html += "</div></details>"
                    if d_code in content_html: content_html[d_code] += row_html

                final_html = f'<div style="width:300px;"><div style="background:#2c3e50;color:#fff;padding:10px;text-align:center;">{name}</div><div style="padding:10px;background:#f4f7f6;">{content_html["0"]}{content_html["1"]}</div></div>'
                folium.Marker([lat, lon], popup=folium.Popup(final_html, max_width=350), icon=folium.Icon(color='orange', icon='bus', prefix='fa')).add_to(m)

        st_folium(m, width=None, height=600, use_container_width=True)
    else:
        st.warning(f"🔎 找不到與「{search_query}」相關的站牌資料。")
