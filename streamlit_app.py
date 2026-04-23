import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="雙北公車智慧看板", layout="wide")
st.title("🚌 雙北公車即時智慧看板")

# --- 1. 金鑰取得 ---
cid = next((st.secrets[k] for k in ["TDX_CLIENT_ID", "TD_CLIENT_ID"] if k in st.secrets), None)
csec = next((st.secrets[k] for k in ["TDX_CLIENT_SECRET", "TD_CLIENT_SECRET"] if k in st.secrets), None)

if not cid:
    st.error("❌ Secrets 中找不到 TDX_CLIENT_ID")
    st.stop()

# --- 2. 工具函式 ---
@st.cache_data(ttl=60)
def get_token():
    try:
        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        payload = {'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': csec}
        r = requests.post(auth_url, data=payload, timeout=10)
        return r.json().get('access_token')
    except Exception as e:
        st.error(f"Token 取得失敗: {e}")
        return None

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
    with st.sidebar:
        search_query = st.text_input("輸入站牌名稱", "政大").strip()
    
    df_stops = get_bus_data(token, "Stop")
    df_eta = get_bus_data(token, "EstimatedTimeOfArrival")

    # --- 除錯資訊 (這段如果成功跑起來可以刪掉) ---
    if df_stops.empty:
        st.error("📡 API 回傳資料為空，請確認金鑰是否過期或額度已滿。")
    else:
        # 尋找站名欄位
        name_col = next((c for c in df_stops.columns if 'StopName' in c), None)
        # 尋找 ID 欄位
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
                    
                    this_etas = pd.DataFrame()
                    if s_id_col and e_id_col and e_id_col in df_eta.columns:
                        uids = group[s_id_col].tolist()
                        this_etas = df_eta[df_eta[e_id_col].isin(uids)].copy()

                    html = f'<div style="width:200px;"><b>{name}</b><hr>'
                    if not this_etas.empty:
                        this_etas['RName'] = this_etas['RouteName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
                        # 排除 unhashable 問題，先轉字串
                        unique = this_etas.sort_values('EstimateTime').drop_duplicates(subset=['RName', 'Direction'])
                        for _, r in unique.iterrows():
                            sec = r.get('EstimateTime')
                            status = "進站中" if not pd.isna(sec) and sec <= 30 else f"{int(sec//60)}分" if not pd.isna(sec) else "未發車"
                            html += f'<div>{r["RName"]}: <b style="color:red;">{status}</b></div>'
                    else:
                        html += '無即時動態'
                    html += '</div>'
                    folium.Marker([lat, lon], popup=folium.Popup(html, max_width=300)).add_to(m)

                st_folium(m, width="100%", height=600)
            else:
                st.warning(f"找不到「{search_query}」")
        else:
            st.write("診斷資訊：抓到的欄位有：", list(df_stops.columns))

                st_folium(m, width=None, height=600, use_container_width=True)
            else:
                st.warning(f"🔎 找不到「{search_query}」站牌資料。")
        else:
            st.error("⚠️ API 資料格式異常（找不到 StopName 欄位）。")
