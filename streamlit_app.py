import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="雙北公車看板-終極修復版", layout="wide")
st.title("🚌 雙北公車即時看板")

# --- 1. 金鑰檢查 ---
def get_config():
    # 嘗試抓取所有可能的金鑰命名
    cid = next((st.secrets[k] for k in ["TDX_CLIENT_ID", "TD_CLIENT_ID", "CLIENT_ID"] if k in st.secrets), None)
    csec = next((st.secrets[k] for k in ["TDX_CLIENT_SECRET", "TD_CLIENT_SECRET", "CLIENT_SECRET"] if k in st.secrets), None)
    return cid, csec

cid, csec = get_config()
if not cid:
    st.error("❌ 在 Secrets 中找不到 API 金鑰，請確認設定。")
    st.stop()

# --- 2. 核心功能 ---
@st.cache_data(ttl=60)
def get_token():
    try:
        url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        res = requests.post(url, data={'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': csec}, timeout=10)
        return res.json().get('access_token')
    except Exception as e:
        st.error(f"Token 取得失敗: {e}")
        return None

def get_data(token, endpoint):
    headers = {'authorization': f'Bearer {token}'}
    combined = []
    for city in ["Taipei", "NewTaipei"]:
        url = f"https://tdx.transportdata.tw/api/basic/v2/Bus/{endpoint}/City/{city}?$format=JSON"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                combined.extend(r.json())
        except: continue
    return pd.DataFrame(combined)

# --- 3. 主流程 ---
token = get_token()
if token:
    search_query = st.sidebar.text_input("🔍 搜尋站牌", "政大").strip()
    
    with st.spinner("正在與雙北交通局同步資料..."):
        df_stops = get_data(token, "Stop")
        df_eta = get_data(token, "EstimatedTimeOfArrival")

    if df_stops.empty:
        st.warning("📡 抓不到站點資料，請檢查 TDX 帳號權限。")
    else:
        # --- 動態欄位偵測 (解決 KeyError) ---
        # 尋找包含 'Name' 的欄位來當站名
        name_col = next((c for c in df_stops.columns if 'StopName' in c), None)
        # 尋找包含 'ID' 的欄位來做串接 (不限制大小寫)
        s_id = next((c for c in df_stops.columns if 'ID' in c.upper()), None)
        e_id = next((c for c in df_eta.columns if 'ID' in c.upper()), None)

        if name_col and s_id:
            # 轉換站名為字串
            df_stops['Zh_Name'] = df_stops[name_col].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
            df_filtered = df_stops[df_stops['Zh_Name'].str.contains(search_query)].copy()

            if not df_filtered.empty:
                # 建立地圖
                pos = df_filtered.iloc[0]['StopPosition']
                m = folium.Map(location=[pos['PositionLat'], pos['PositionLon']], zoom_start=17)

                for name, group in df_filtered.groupby('Zh_Name'):
                    g_pos = group.iloc[0]['StopPosition']
                    
                    # 匹配即時動態 (使用動態偵測到的 ID)
                    this_etas = pd.DataFrame()
                    if e_id and not df_eta.empty:
                        uids = group[s_id].unique().tolist()
                        this_etas = df_eta[df_eta[e_id].isin(uids)].copy()

                    html = f'<div style="width:200px;"><b>{name}</b><hr>'
                    if not this_etas.empty:
                        # 處理路線名稱 (轉為字串避免 Hash 錯誤)
                        this_etas['Route'] = this_etas['RouteName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
                        unique_eta = this_etas.sort_values('EstimateTime').drop_duplicates(subset=['Route', 'Direction'])
                        for _, r in unique_eta.iterrows():
                            sec = r.get('EstimateTime')
                            status = "進站中" if not pd.isna(sec) and sec <= 30 else f"{int(sec//60)}分" if not pd.isna(sec) else "未發車"
                            html += f'<div>{r["Route"]}: <span style="color:red;">{status}</span></div>'
                    else:
                        html += '暫無動態資訊'
                    html += '</div>'
                    folium.Marker([g_pos['PositionLat'], g_pos['PositionLon']], popup=folium.Popup(html, max_width=300)).add_to(m)

                st_folium(m, width="100%", height=600)
            else:
                st.info(f"找不到「{search_query}」。")
        else:
            # 如果欄位還是對不上，直接印出結構供開發者檢查
            st.error("⚠️ 資料格式解析失敗")
            st.write("站點資料欄位：", list(df_stops.columns))
            st.write("動態資料欄位：", list(df_eta.columns))
