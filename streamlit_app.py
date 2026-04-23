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
# 在部署到 Streamlit Cloud 時，請在 Settings > Secrets 加入以下內容：
# TDX_CLIENT_ID = "你的ID"
# TDX_CLIENT_SECRET = "你的SECRET"
try:
    CLIENT_ID = st.secrets["TDX_CLIENT_ID"]
    CLIENT_SECRET = st.secrets["TDX_CLIENT_SECRET"]
except:
    st.error("❌ 找不到 API 金鑰，請在 Secrets 中設定。")
    st.stop()

# --- 3. 工具函式 ---
@st.cache_data(ttl=3600) # 快取 1 小時，避免頻繁請求基礎資料
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
    refresh_button = st.button("🔄 重新整理即時動態")

# --- 5. 主程式邏輯 ---
token = get_token()
if token:
    with st.spinner("📡 正在同步雙北公車即時資料..."):
        df_stops = get_bus_data(token, "Stop")
        df_eta = get_bus_data(token, "EstimatedTimeOfArrival")
        df_stop_of_route = get_bus_data(token, "StopOfRoute")
    
    df_stops['Name_Zh'] = df_stops['StopName'].apply(lambda x: x['Zh_tw'])
    df_filtered = df_stops[df_stops['Name_Zh'].str.contains(search_query.strip())].copy()

    if not df_filtered.empty:
        # 計算地圖中心
        avg_lat = df_filtered['StopPosition'].apply(lambda x: x['PositionLat']).mean()
        avg_lon = df_filtered['StopPosition'].apply(lambda x: x['PositionLon']).mean()
        
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=17, tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', attr='Google')

        for name, group in df_filtered.groupby('Name_Zh'):
            lat, lon = group['StopPosition'].apply(lambda x: x['PositionLat']).mean(), group['StopPosition'].apply(lambda x: x['PositionLon']).mean()
            all_uids = group['StopUID'].tolist()
            etas = df_eta[df_eta['StopUID'].isin(all_uids)].copy()
            unique_etas = etas.drop_duplicates(subset=['RouteName', 'Direction'])

            # 建立分頁 HTML (使用我們先前開發的穩定版 ID 邏輯)
            tab_id = f"tab_{name.replace(' ', '')}"
            content_html = {"0": "", "1": ""}
            
            for _, row in unique_etas.iterrows():
                d_code = str(row['Direction'])
                route = row['RouteName']['Zh_tw']
                sec = row.get('EstimateTime')
                dest = row.get('DestinationName', {}).get('Zh_tw', '即時動態')
                
                # 樣式定義
                if pd.isna(sec): t, b, f = "未發車", "#f7fafc", "#a0aec0"
                elif sec <= 30: t, b, f = "進站中", "#fff5f5", "#e53e3e"
                elif sec <= 90: t, b, f = "將到站", "#fffaf0", "#dd6b20"
                else: t, b, f = f"{int(sec//60)} 分", "#f0fff4", "#38a169"

                row_html = f"""
                <details style="margin-bottom: 8px; border: 1px solid #e2e8f0; border-radius: 8px; background:#fff;">
                    <summary style="padding: 10px; cursor: pointer; list-style: none; display: flex; align-items: center; justify-content: space-between; outline:none;">
                        <div><span style="font-weight: bold; color: #2b6cb0; font-size:15px;">{route}</span><br><span style="font-size: 11px; color: #718096;">往 {dest}</span></div>
                        <div style="background: {b}; color: {f}; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold;">{t}</div>
                    </summary>
                    <div style="padding: 10px; background: #fafafa; border-top: 1px solid #eee; font-size: 11px;">
                        <div style="border-left: 2px solid #cbd5e0; padding-left: 10px;">
                """
                # 路線細節抓取
                r_stops = df_stop_of_route[(df_stop_of_route['RouteUID'] == row['RouteUID']) & (df_stop_of_route['Direction'] == row['Direction'])]
                if not r_stops.empty:
                    for s in r_stops.iloc[0]['Stops']:
                        s_n = s['StopName']['Zh_tw']
                        o_e = df_eta[(df_eta['RouteUID'] == row['RouteUID']) & (df_eta['StopUID'] == s['StopUID'])]
                        s_t = f" ({int(o_e.iloc[0].get('EstimateTime')//60)}分)" if not o_e.empty and not pd.isna(o_e.iloc[0].get('EstimateTime')) else ""
                        row_html += f"<div style='margin-bottom: 2px; color: {'#e53e3e; font-weight: bold' if s_n == name else '#4a5568'};'>• {s_n}{s_t}</div>"
                
                row_html += "</div></div></details>"
                if d_code in content_html: content_html[d_code] += row_html

            # 最終 HTML 封裝
            final_html = f"""
            <style>
                .tabs-{tab_id} {{ display: flex; flex-direction: column; width: 300px; font-family: sans-serif; }}
                .tab-nav {{ display: flex; background: #2c3e50; border-radius: 8px 8px 0 0; overflow: hidden; }}
                .tab-nav label {{ flex: 1; padding: 12px; text-align: center; color: #ccc; cursor: pointer; font-size: 14px; border-bottom: 3px solid transparent; }}
                .tab-content {{ display: none; padding: 10px; background: #f4f7f6; max-height: 350px; overflow-y: auto; }}
                #t0-{tab_id}:checked ~ .tab-nav label[for="t0-{tab_id}"] {{ color: #ffce00; border-bottom: 3px solid #ffce00; font-weight: bold; }}
                #t1-{tab_id}:checked ~ .tab-nav label[for="t1-{tab_id}"] {{ color: #ffce00; border-bottom: 3px solid #ffce00; font-weight: bold; }}
                #t0-{tab_id}:checked ~ #c0-{tab_id} {{ display: block; }}
                #t1-{tab_id}:checked ~ #c1-{tab_id} {{ display: block; }}
            </style>
            <div class="tabs-{tab_id}">
                <div style="background: #2c3e50; color: #fff; padding: 10px; text-align: center; font-weight: bold; font-size: 16px;">{name}</div>
                <input type="radio" name="nav-{tab_id}" id="t0-{tab_id}" style="display:none" checked>
                <input type="radio" name="nav-{tab_id}" id="t1-{tab_id}" style="display:none">
                <div class="tab-nav">
                    <label for="t0-{tab_id}">去程 (方向 0)</label>
                    <label for="t1-{tab_id}">回程 (方向 1)</label>
                </div>
                <div id="c0-{tab_id}" class="tab-content">{content_html['0'] if content_html['0'] else "<p style='text-align:center;color:#999;margin-top:20px;'>無即時資料</p>"}</div>
                <div id="c1-{tab_id}" class="tab-content">{content_html['1'] if content_html['1'] else "<p style='text-align:center;color:#999;margin-top:20px;'>無即時資料</p>"}</div>
            </div>
            """
            folium.Marker([lat, lon], popup=folium.Popup(final_html, max_width=350), icon=folium.Icon(color='orange', icon='bus', prefix='fa')).add_to(m)
        
        # 在 Streamlit 中顯示地圖
        st_folium(m, width=None, height=600, use_container_width=True)
    else:
        st.warning("🔎 找不到站牌，請重新輸入關鍵字")
