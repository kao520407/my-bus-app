import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="雙北公車智慧看板-診斷版", layout="wide")
st.title("🚌 雙北公車即時智慧看板")

# --- 1. 金鑰檢查 (增加容錯命名) ---
def get_tdx_config():
    keys = ["TDX_CLIENT_ID", "TD_CLIENT_ID", "CLIENT_ID", "TDX_CLIENT_SECRET", "TD_CLIENT_SECRET", "CLIENT_SECRET"]
    cid = next((st.secrets[k] for k in keys[:3] if k in st.secrets), None)
    csec = next((st.secrets[k] for k in keys[3:] if k in st.secrets), None)
    return cid, csec

cid, csec = get_tdx_config()
if not cid:
    st.error("❌ Secrets 設定錯誤，請確認 TDX_CLIENT_ID 與 TDX_CLIENT_SECRET 已填寫。")
    st.stop()

# --- 2. 核心功能 ---
@st.cache_data(ttl=60)
def get_token():
    try:
        url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        res = requests.post(url, data={'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': csec}, timeout=10)
        return res.json().get('access_token')
    except: return None

def get_api_data(token, endpoint):
    headers = {'authorization': f'Bearer {token}'}
    combined = []
    for city in ["Taipei", "NewTaipei"]:
        url = f"https://tdx.transportdata.tw/api/basic/v2/Bus/{endpoint}/City/{city}?$format=JSON"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            # --- 新增診斷代碼 ---
            if r.status_code != 200:
                st.error(f"📡 API 呼叫失敗! 城市: {city}, 代碼: {r.status_code}")
                st.write(f"錯誤詳情: {r.text}") 
            # ------------------
            if r.status_code == 200:
                combined.extend(r.json())
        except Exception as e:
            st.warning(f"連線異常: {e}")
            continue
    return pd.DataFrame(combined)
        except: continue
    return pd.DataFrame(combined)

# --- 3. 主流程 ---
token = get_token()
if token:
    search_query = st.sidebar.text_input("🔍 搜尋站牌名稱", "政大").strip()
    
    # 清除快取的按鈕 (非常重要！)
    if st.sidebar.button("🔄 強制刷新資料"):
        st.cache_data.clear()
        st.rerun()

    df_stops = get_api_data(token, "Stop")
    df_eta = get_api_data(token, "EstimatedTimeOfArrival")

    if df_stops.empty:
        st.warning("📡 API 回傳為空，請確認 TDX 帳號狀態。")
    else:
        # 自動尋找欄位，完全不寫死名稱
        name_col = next((c for c in df_stops.columns if 'StopName' in c), None)
        # 尋找任何包含 ID 的欄位做匹配
        s_id = next((c for c in df_stops.columns if 'ID' in c.upper()), None)
        e_id = next((c for c in df_eta.columns if 'ID' in c.upper()), None)

        if name_col and s_id:
            df_stops['Zh_Name'] = df_stops[name_col].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
            df_filtered = df_stops[df_stops['Zh_Name'].str.contains(search_query)].copy()

            if not df_filtered.empty:
                pos = df_filtered.iloc[0]['StopPosition']
                m = folium.Map(location=[pos['PositionLat'], pos['PositionLon']], zoom_start=16)

                for name, group in df_filtered.groupby('Zh_Name'):
                    g_pos = group.iloc[0]['StopPosition']
                    # 匹配即時動態
                    this_etas = df_eta[df_eta[e_id].isin(group[s_id].unique())] if e_id is not None else pd.DataFrame()
                    # 在發送請求後，加入這兩行來抓出真正的錯誤原因
                        response = requests.get(api_url, headers=headers)
                        if response.status_code != 200:
                        st.error(f"API 錯誤碼: {response.status_code}")
                        st.write(f"錯誤訊息: {response.text}") # 這行會告訴我們為什麼 TDX 不給資料
                        # 修改這部分，確保它能抓到錯誤
                        if df_stops.empty:
                        st.error("📡 站點資料抓取失敗，請檢查 API 權限或金鑰格式。")
                        # 如果你想看更細節的錯誤，請確認前面的 get_api_data 函式內有加上 print 或 st.write
                    html = f"<b>{name}</b><hr>"
                    if not this_etas.empty:
                        this_etas['R'] = this_etas['RouteName'].apply(lambda x: x.get('Zh_tw', '') if isinstance(x, dict) else str(x))
                        for _, r in this_etas.sort_values('EstimateTime').drop_duplicates(subset=['R', 'Direction']).iterrows():
                            sec = r.get('EstimateTime')
                            status = "進站中" if not pd.isna(sec) and sec <= 30 else f"{int(sec//60)}分" if not pd.isna(sec) else "未發車"
                            html += f"<div>{r['R']}: {status}</div>"
                    
                    folium.Marker([g_pos['PositionLat'], g_pos['PositionLon']], popup=folium.Popup(html, max_width=250)).add_to(m)
                st_folium(m, width="100%", height=600)
            else:
                st.info(f"找不到「{search_query}」")
        else:
            # 這裡會顯示欄位名稱，請拍下這部分
            st.error("⚠️ 欄位匹配失敗，請檢查下方欄位清單")
            st.write("站點資料欄位:", list(df_stops.columns))
            st.write("ETA 資料欄位:", list(df_eta.columns))
else:
    st.error("🔑 API 金鑰驗證失敗，請檢查 ID 與 Secret。")
