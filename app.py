import streamlit as st
import os
import subprocess
import sys
import asyncio
import re
import pandas as pd
from datetime import datetime

# --- [1. 서버에서 에러 안 나게 브라우저 설치하는 부분] ---
@st.cache_resource
def install_browser():
    try:
        if not os.path.exists(".browser_installed"):
            # 권한 에러 방지를 위해 꼭 필요한 것만 설치하도록 수정했어!
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            with open(".browser_installed", "w") as f:
                f.write("done")
    except Exception as e:
        st.error(f"브라우저 엔진 설치 중 오류가 났어: {e}")

# 시작하자마자 설치 실행!
install_browser()

from playwright.async_api import async_playwright

# 윈도우 환경(내 컴퓨터) 대응
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

st.set_page_config(page_title="Dealstock v4.5 Pro", layout="wide")

# --- [2. 화면 예쁘게 꾸미기 (CSS)] ---
st.markdown("""
    <style>
    .fixed-header { position: sticky; top: 0; background-color: white; z-index: 999; display: flex; padding: 10px; font-weight: bold; border-bottom: 2px solid #ff4b4b; text-align: center; font-size: 0.9em; }
    .deal-row { border-bottom: 1px solid #eee; padding: 15px 5px; display: flex; align-items: center; }
    .tag { background-color: #f0f2f6; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; color: #555; margin-right: 4px; }
    .fire-text { color: #ff4b4b; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [3. 상세 내용 분석 (민심/품절)] ---
async def analyze_post(context, url):
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=10000)
        content = await page.inner_text('body')
        await page.close()
        
        is_soldout = any(w in content for w in ['품절', '종료', '끝났', '다 나갔'])
        
        tags = []
        if any(w in content for w in ['싸다', '역대급', '최저가']): tags.append("💰 가격대박")
        if any(w in content for w in ['지름', '탑승', '삼']): tags.append("🛒 무지성구매")
        if not tags: tags.append("💬 관망중")
        
        return is_soldout, tags[:2]
    except:
        try: await page.close()
        except: pass
        return False, ["⚪ 분석대기"]

# --- [4. 핫딜 긁어오는 핵심 엔진] ---
async def run_crawling():
    async with async_playwright() as p:
        # 서버 환경에서도 잘 돌아가게 옵션 추가
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://www.fmkorea.com/?mid=hotdeal", wait_until="networkidle", timeout=20000)
            raw_text = await page.inner_text('body')
            links = await page.eval_on_selector_all('a', 'elements => elements.map(e => ({ "text": e.innerText.trim(), "href": e.getAttribute("href") }))')
            
            real_links = []
            found_marker = False
            for l in links:
                if "핫딜게시판 통합공지사항" in (l['text'] or ""): found_marker = True
                if found_marker and re.match(r'^/\d+$', l['href'] or ""):
                    if not real_links or real_links[-1] != l['href']: real_links.append(l['href'])
            
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            start_idx = 0
            for i, line in enumerate(lines):
                if "쇼핑몰:" in line:
                    start_idx = max(0, i - 1)
                    break
            
            deals = []
            link_ptr = 0
            refined = lines[start_idx:start_idx+60]
            for i in range(len(refined)):
                line = refined[i]
                if "[" in line and "]" in line and not any(k in line for k in ["쇼핑몰:", "인기", "공지"]):
                    if link_ptr < len(real_links):
                        c_match = re.search(r'\[(\d+)\]$', line)
                        deals.append({
                            "title": re.sub(r'\[\d+\]$', '', line).strip(),
                            "comments": int(c_match.group(1)) if c_match else 0,
                            "info": refined[i+1] if i+1 < len(refined) and "쇼핑몰:" in refined[i+1] else "",
                            "link": f"https://www.fmkorea.com{real_links[link_ptr]}"
                        })
                        link_ptr += 1
            
            # 상위 10개 정밀 분석 실행
            tasks = [analyze_post(context, d['link']) for d in deals[:10]]
            results = await asyncio.gather(*tasks)
            for i, (soldout, tags) in enumerate(results):
                deals[i]['soldout'] = soldout
                deals[i]['tags'] = tags
            
            await browser.close()
            return deals
        except Exception as e:
            st.error(f"데이터 긁어오다가 에러 났어: {e}")
            await browser.close()
            return None

# --- [5. 우리 눈에 보이는 화면 구성] ---
st.title("🔥 Dealstock v4.5: Market Terminal")

if st.button('🚀 실시간 데이터 동기화'):
    with st.spinner('시장의 민심을 분석하는 중... 잠시만 기다려줘!'):
        data = asyncio.run(run_crawling())
        if data:
            st.session_state['v45_report'] = data

if 'v45_report' in st.session_state:
    st.markdown("""
        <div class="fixed-header">
            <div style="flex: 4; text-align: left;">종목 / 태그</div>
            <div style="flex: 1.5;">화력지수</div>
            <div style="flex: 1.5;">분석의견</div>
        </div>
    """, unsafe_allow_html=True)

    for i, d in enumerate(st.session_state['v45_report']):
        fire_score = min(100, (d['comments'] / 50) * 100)
        fire_icons = "🔥" * (1 if fire_score < 30 else 2 if fire_score < 70 else 3)
        
        soldout_label = '<span style="color:red; font-weight:bold;">[종료]</span> ' if d.get('soldout') else ''
        tags_html = "".join([f'<span class="tag">{t}</span>' for t in d.get('tags', [])])
        
        st.markdown(f"""
            <div class="deal-row">
                <div style="flex: 4; text-align: left;">
                    <div style="font-weight: bold; font-size: 1em;">
                        {soldout_label}<a href="{d['link']}" target="_blank" style="text-decoration:none; color:#1f1f1f;">{d['title']}</a>
                    </div>
                    <div style="margin-top: 5px;">{tags_html}</div>
                    <div style="font-size: 0.8em; color: #888; margin-top: 3px;">{d['info']}</div>
                </div>
                <div style="flex: 1.5; text-align: center;">
                    <span class="fire-text">{fire_icons}</span><br>
                    <span style="font-size: 0.8em; color: #999;">{fire_score:.1f}pt</span>
                </div>
                <div style="flex: 1.5; text-align: center; font-size: 0.85em; font-weight: bold;">
                    { "🔴 매도" if d.get('soldout') else "🟢 매수" if fire_score > 60 else "⚪ 관망" }
                </div>
            </div>
        """, unsafe_allow_html=True)
