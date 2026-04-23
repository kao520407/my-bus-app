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
    # 嘗試所有可能的 Secrets 命名方式
    cid = next((st.secrets[k] for k in ["TDX_CLIENT_ID", "TD_CLIENT_ID", "CLIENT_ID"] if k in st.secrets), None)
    csec = next((st.secrets[k] for k in ["TDX_CLIENT_SECRET", "TD_CLIENT_SECRET", "CLIENT_SECRET"] if k in st.secrets), None)
    if not cid or not csec: raise KeyError
except:
    st.error("❌ 找不到 API 金鑰，請在 Secrets 中設定 TDX_CLIENT_ID 與 TDX_CLIENT_SECRET。")
    st.stop()

# --- 3. 工具函式 ---
@st.cache_data(ttl=60)
def get_token():
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    payload = {'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': csec}
    r = requests.post(auth_url, data=payload)
    return r.json().get('access_token')

def get_bus_data(token, endpoint):
    headers = {'authorization': f'Bearer {token}'}
    combined = []
    for city in ["Taipei", "NewTaipei"]:
        url = f"https://tdx.transportdata.tw/api/basic/v2/Bus/{endpoint}/City/{city}?$format=JSON"
        try:
            res = requests.get(url, headers=headers)
            if res.status_code == 200 and isinstance(res.json(), list):
                combined.extend(res.json())
        except: continue
    return pd.DataFrame(combined)

# --- 4. 主程式 ---
token = get_token()
if token:
    with st.sidebar:
        st.header("🔍 搜尋站點")
        search_query = st.text_input("請輸入站牌名稱", "政大").strip()
        st.info("💡 若搜尋不到，請確認站名是否完全正確。")

    with st.spinner("🔄 資料同步中..."):
        df_stops = get_bus_data(token, "Stop")
        df_eta = get_bus_data(token, "EstimatedTimeOfArrival")

    # 檢查是否抓到資料
    if df_stops.empty:
        st.error("📡 無法從 API 取得站點資料，請檢查金鑰。")
    else:
        # 1. 處理站名
        name_col = next((c for c in df_stops.columns if 'StopName' in c), None)
        if name_col:
            df_stops['Name_Zh'] = df_stops[name_col].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else '')
            df_filtered = df_stops[df_stops['Name_Zh'].str.contains(search_query)].copy()
            
            if not df_filtered.empty:
                # 2. 找出 UID 欄位 (強制相容各種大小寫)
                # 在 Stop 資料中找 ID 欄位
                s_uid_col = next((c for c in df_filtered.columns if 'UID' in c.upper() or 'ID' in c.upper()), None)
                # 在 ETA 資料中找 ID 欄位
                e_uid_col = next((c for c in df_eta.columns if 'UID' in c.upper() or 'ID' in c.upper()), None)

                avg_lat = df_filtered['StopPosition'].apply(lambda x: x['PositionLat']).mean()
                avg_lon = df_filtered['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                m = folium.Map(location=[avg_lat, avg_lon], zoom_start=17, tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', attr='Google')

                for name, group in df_filtered.groupby('Name_Zh'):
                    lat = group['StopPosition'].apply(lambda x: x['PositionLat']).mean()
                    lon = group['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                    
                    # 匹配即時動態
                    this_etas = pd.DataFrame()
                    if s_uid_col and e_uid_col:
                        uids = group[s_uid_col].tolist()
                        this_etas = df_eta[df_eta[e_uid_col].isin(uids)].copy()

                    html = f'<div style="width:250px;"><b>{name}</b><hr>'
                    if not this_etas.empty:
                        # 處理路線名
                        this_etas['RName'] = this_etas['RouteName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
                        unique = this_etas.sort_values('EstimateTime').drop_duplicates(subset=['RName', 'Direction'])
                        for _, r in unique.iterrows():
                            sec = r.get('EstimateTime')
                            dest = r.get('DestinationName', {}).get('Zh_tw', '即時動態') if isinstance(r.get('DestinationName'), dict) else '即時動態'
                            t, c = ("進站中", "red") if not pd.isna(sec) and sec <= 30 else (f"{int(sec//60)}分", "green") if not pd.isna(sec) else ("未發車", "#999")
                            html += f'<div style="display:flex;justify-content:space-between;font-size:13px;"><span>{r["RName"]} 往 {dest}</span><b style="color:{c};">{t}</b></div>'
                    else:
                        html += '<p style="color:#666;font-size:12px;">暫無動態資訊</p>'
                    html += '</div>'
                    folium.Marker([lat, lon], popup=folium.Popup(html, max_width=300), icon=folium.Icon(color='orange', icon='bus', prefix='fa')).add_to(m)

                st_folium(m, width=None, height=600, use_container_width=True)
            else:
                st.warning(f"🔎 找不到「{search_query}」站牌資料。")
        else:
            st.error("⚠️ API 資料格式異常（找不到 StopName 欄位）。")
