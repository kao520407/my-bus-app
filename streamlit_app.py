import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="雙北公車智慧看板", layout="wide")
st.title("🚌 雙北公車即時智慧看板")

# --- 1. 金鑰檢查 (增加多種命名相容性) ---
def get_secret(key_list):
    for k in key_list:
        if k in st.secrets: return st.secrets[k]
    return None

cid = get_secret(["TDX_CLIENT_ID", "TD_CLIENT_ID", "CLIENT_ID"])
csec = get_secret(["TDX_CLIENT_SECRET", "TD_CLIENT_SECRET", "CLIENT_SECRET"])

if not cid or not csec:
    st.error("❌ 找不到 API 金鑰。請在 Streamlit Secrets 設定 TDX_CLIENT_ID 與 TDX_CLIENT_SECRET。")
    st.stop()

# --- 2. 工具函式 ---
@st.cache_data(ttl=60)
def get_token():
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    payload = {'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': csec}
    try:
        r = requests.post(auth_url, data=payload, timeout=10)
        return r.json().get('access_token')
    except: return None

def get_bus_data(token, endpoint):
    headers = {'authorization': f'Bearer {token}'}
    combined = []
    for city in ["Taipei", "NewTaipei"]:
        url = f"https://tdx.transportdata.tw/api/basic/v2/Bus/{endpoint}/City/{city}?$format=JSON"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list): combined.extend(data)
        except: continue
    return pd.DataFrame(combined)

# --- 3. 主程式 ---
token = get_token()
if token:
    search_query = st.sidebar.text_input("🔍 輸入站牌名稱", "政大").strip()
    
    with st.spinner("正在同步雙北公車動態..."):
        df_stops = get_bus_data(token, "Stop")
        df_eta = get_bus_data(token, "EstimatedTimeOfArrival")

    if df_stops.empty:
        st.warning("📡 目前抓不到站點資料，請確認 TDX 帳號是否正常或稍後再試。")
    else:
        # 自動搜尋站名與 ID 欄位 (解決大小寫不一問題)
        name_col = next((c for c in df_stops.columns if 'StopName' in c), None)
        s_id_col = next((c for c in df_stops.columns if 'ID' in c.upper() or 'UID' in c.upper()), None)
        e_id_col = next((c for c in df_eta.columns if 'ID' in c.upper() or 'UID' in c.upper()), None)

        if name_col:
            df_stops['Name_Zh'] = df_stops[name_col].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
            df_filtered = df_stops[df_stops['Name_Zh'].str.contains(search_query)].copy()

            if not df_filtered.empty:
                # 建立地圖
                avg_lat = df_filtered['StopPosition'].apply(lambda x: x['PositionLat']).mean()
                avg_lon = df_filtered['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                m = folium.Map(location=[avg_lat, avg_lon], zoom_start=17, tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', attr='Google')

                for name, group in df_filtered.groupby('Name_Zh'):
                    lat = group['StopPosition'].apply(lambda x: x['PositionLat']).mean()
                    lon = group['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                    
                    # 匹配動態
                    this_etas = pd.DataFrame()
                    if s_id_col and e_id_col and not df_eta.empty:
                        uids = group[s_id_col].tolist()
                        this_etas = df_eta[df_eta[e_id_col].isin(uids)].copy()

                    html = f'<div style="width:200px;"><b>{name}</b><hr>'
                    if not this_etas.empty:
                        this_etas['RName'] = this_etas['RouteName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
                        unique = this_etas.sort_values('EstimateTime').drop_duplicates(subset=['RName', 'Direction'])
                        for _, r in unique.iterrows():
                            sec = r.get('EstimateTime')
                            dest = r.get('DestinationName', {}).get('Zh_tw', '即時動態') if isinstance(r.get('DestinationName'), dict) else '即時動態'
                            t, c = ("進站中", "red") if not pd.isna(sec) and sec <= 30 else (f"{int(sec//60)}分", "green") if not pd.isna(sec) else ("未發車", "#999")
                            html += f'<div style="display:flex;justify-content:space-between;"><span>{r["RName"]} 往 {dest}</span><b style="color:{c};">{t}</b></div>'
                    else:
                        html += '<p style="color:#666;">暫無動態</p>'
                    html += '</div>'
                    folium.Marker([lat, lon], popup=folium.Popup(html, max_width=300), icon=folium.Icon(color='orange', icon='bus', prefix='fa')).add_to(m)

                st_folium(m, width="100%", height=600)
            else:
                st.info(f"🔎 找不到「{search_query}」，請更換關鍵字搜尋。")
        else:
            st.error("⚠️ 資料結構異常，請聯繫開發者檢查 API。")
else:
    st.error("🔑 API 驗證失敗，請檢查你的 ID 與 Secret 是否填寫正確。")
