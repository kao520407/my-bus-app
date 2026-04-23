import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="雙北公車智慧看板", layout="wide")
st.title("🚌 雙北公車即時智慧看板")

# --- 1. 金鑰處理 ---
cid = next((st.secrets[k] for k in ["TDX_CLIENT_ID", "TD_CLIENT_ID"] if k in st.secrets), None)
csec = next((st.secrets[k] for k in ["TDX_CLIENT_SECRET", "TD_CLIENT_SECRET"] if k in st.secrets), None)

if not cid:
    st.error("❌ Secrets 中找不到金鑰設定。")
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
                combined.extend(res.json())
        except: continue
    return pd.DataFrame(combined)

# --- 3. 主程式 ---
token = get_token()
if token:
    search_query = st.sidebar.text_input("🔍 輸入站牌名稱", "政大").strip()
    
    with st.spinner("同步公車資料中..."):
        df_stops = get_bus_data(token, "Stop")
        df_eta = get_bus_data(token, "EstimatedTimeOfArrival")

    if df_stops.empty:
        st.warning("📡 目前抓不到站點資料，請檢查 API 金鑰狀態。")
    else:
        # --- 診斷與容錯處理 ---
        # 尋找站名欄位
        name_col = next((c for c in df_stops.columns if 'StopName' in c), None)
        # 尋找 ID 欄位 (不再寫死名稱)
        s_id = next((c for c in df_stops.columns if 'ID' in c.upper()), None)
        e_id = next((c for c in df_eta.columns if 'ID' in c.upper()), None)

        if name_col and s_id:
            # 轉換站名為純文字
            df_stops['Name_Zh'] = df_stops[name_col].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
            df_filtered = df_stops[df_stops['Name_Zh'].str.contains(search_query)].copy()

            if not df_filtered.empty:
                avg_lat = df_filtered['StopPosition'].apply(lambda x: x['PositionLat']).mean()
                avg_lon = df_filtered['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                m = folium.Map(location=[avg_lat, avg_lon], zoom_start=17)

                for name, group in df_filtered.groupby('Name_Zh'):
                    lat = group['StopPosition'].apply(lambda x: x['PositionLat']).mean()
                    lon = group['StopPosition'].apply(lambda x: x['PositionLon']).mean()
                    
                    # 匹配 ETA (安全檢查 ID)
                    this_etas = pd.DataFrame()
                    if e_id and e_id in df_eta.columns:
                        uids = group[s_id].tolist()
                        this_etas = df_eta[df_eta[e_id].isin(uids)].copy()

                    html = f'<div style="width:200px;"><b>{name}</b><hr>'
                    if not this_etas.empty:
                        this_etas['RName'] = this_etas['RouteName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
                        unique = this_etas.sort_values('EstimateTime').drop_duplicates(subset=['RName', 'Direction'])
                        for _, r in unique.iterrows():
                            sec = r.get('EstimateTime')
                            t = "進站中" if not pd.isna(sec) and sec <= 30 else f"{int(sec//60)}分" if not pd.isna(sec) else "未發車"
                            html += f'<div>{r["RName"]}: {t}</div>'
                    else:
                        html += '無即時動態'
                    html += '</div>'
                    folium.Marker([lat, lon], popup=folium.Popup(html, max_width=300)).add_to(m)

                st_folium(m, width="100%", height=600)
            else:
                st.info(f"🔎 找不到與「{search_query}」相關的站牌。")
        else:
            # 這是最後的救命稻草：如果還是不行，印出欄位讓我們分析
            st.error("⚠️ 資料結構解析失敗。")
            st.write("站點資料現有欄位：", list(df_stops.columns))
            st.write("動態資料現有欄位：", list(df_eta.columns))
