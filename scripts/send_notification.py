#!/usr/bin/env python3
"""
每日油价+天气通知 — 微信 + 钉钉双通道

用法:
  python send_notification.py [changed]

环境变量:
  SERVERCHAN_SENDKEY  - Server酱 SendKey
  DINGTALK_WEBHOOK    - 钉钉机器人 Webhook
"""

import json, sys, os, hmac, hashlib, base64, time, urllib.parse
from pathlib import Path
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("⚠️ 需要安装 requests: pip install requests")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_FILE = PROJECT_ROOT / "data.json"
PAGE_URL = "https://ToniaXuu.github.io/fuel-price-tracker/"
TANK_SIZE = 50
LAT, LON, TZ = 36.65, 117.00, "Asia/Shanghai"


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_weather():
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&daily=temperature_2m_max,temperature_2m_min,weathercode&timezone={TZ}&forecast_days=1"
        r = requests.get(url, timeout=10).json()
        d = r.get("daily", {})
        if not d:
            return None
        code = d["weathercode"][0]
        wm = {0: "☀️ 晴", 1: "🌤 少云", 2: "⛅ 多云", 3: "☁️ 阴", 45: "🌫 雾", 51: "🌧 小雨", 53: "🌧 中雨", 61: "🌧 阵雨", 71: "🌨 小雪", 95: "⛈ 雷暴"}
        return dict(temp_max=int(d["temperature_2m_max"][0]), temp_min=int(d["temperature_2m_min"][0]), weather=wm.get(code, "🌡"))
    except Exception as e:
        print(f"  ⚠️ 天气获取失败: {e}")
        return None


def send_serverchan(sendkey, title, content):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    r = requests.post(url, data={"title": title, "desp": content}, timeout=15).json()
    print("  ✅ 微信通知发送成功" if r.get("code") == 0 else f"  ⚠️ 微信通知失败: {r.get('message', '')}")


def send_dingtalk(webhook, title, text):
    secret = os.environ.get("DINGTALK_SECRET", "")
    url = webhook
    if secret:
        ts = str(round(time.time() * 1000))
        h = hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()
        url = f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(base64.b64encode(h))}"
    r = requests.post(url, json={"msgtype": "markdown", "markdown": {"title": title, "text": text}}, timeout=15).json()
    print("  ✅ 钉钉通知发送成功" if r.get("errcode") == 0 else f"  ⚠️ 钉钉通知失败: {r.get('errmsg', '')}")


def fmt_date(s):
    d = datetime.strptime(s, "%Y-%m-%d")
    return f"{d.month}月{d.day}日"


def today_cn():
    now = datetime.now()
    return f"{now.month}月{now.day}日 周{'一二三四五六日'[now.weekday()]}"


def now_time():
    return datetime.now().strftime("%H:%M")


def days_since(date_str):
    return (datetime.now() - datetime.strptime(date_str, "%Y-%m-%d")).days


def next_working_day(start_str, n=10):
    start = datetime.strptime(start_str, "%Y-%m-%d")
    days_added = 0
    cur = start
    while days_added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days_added += 1
    return cur.strftime("%Y-%m-%d")


def streak_info(prices):
    last = prices[-1]
    streak = [last]
    for i in range(len(prices) - 2, -1, -1):
        if prices[i]["type"] == last["type"]:
            streak.insert(0, prices[i])
        else:
            break
    if len(streak) >= 2 and last["type"] == "down":
        return f"近{len(streak)}轮连降，累计 -{abs(round(streak[-1]['p95'] - streak[0]['p95'], 2))} 元"
    elif len(streak) >= 2 and last["type"] == "up":
        return f"近{len(streak)}轮连涨，累计 +{round(streak[-1]['p95'] - streak[0]['p95'], 2)} 元"
    return {"up": "单次上调", "down": "单次下调", "flat": "搁浅"}.get(last["type"], "—")


def build_msg(prices, has_change, weather):
    latest = prices[-1]
    prev = prices[-2] if len(prices) >= 2 else latest
    today = today_cn()
    now_t = now_time()
    today_iso = datetime.now().strftime("%Y-%m-%d")
    yesterday_iso = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    recent = latest["date"] in (today_iso, yesterday_iso) and latest["type"] != "flat"

    # 数据计算
    delta_95 = round(latest["p95"] - prev["p95"], 2)
    tank95 = round(latest["p95"] * TANK_SIZE, 2)
    ytd95 = round(latest["p95"] - 7.16, 2)
    days_cnt = days_since(latest["date"])
    streak = streak_info(prices)
    nxt = next_working_day(latest["date"], 10)
    prev_entry = prices[-2] if len(prices) >= 2 else None
    prev_str = f"第{prev_entry['round']}轮 {fmt_date(prev_entry['date'])}" if prev_entry else "—"
    cur_str = f"第{latest['round']}轮 {fmt_date(latest['date'])}"

    # 天气
    wx = f"☁️ 济南 {weather['weather']} {weather['temp_min']}°C~{weather['temp_max']}°C\n" if weather else ""

    # 建议
    tip = "下降中，若油箱不急需建议先少量加油" if delta_95 < 0 else ("上涨趋势中，建议及时加满" if delta_95 > 0 else "暂时稳定，可关注下一轮")

    # ===== 钉钉 Markdown（清爽分栏）=====
    def price_block():
        return (
            f"| 油品 | 价格 |\n"
            f"|------|------|\n"
            f"| 92# | {latest['p92']} 元/升 |\n"
            f"| 95# | {latest['p95']} 元/升 |\n"
            f"| 98# | {latest['p98']} 元/升 |\n"
            f"| 0#柴油 | {latest['pDiesel']} 元/升 |"
        )

    def info_block():
        sg = "+" if ytd95 > 0 else ""
        return (
            f"💰 **加满一箱95#（{TANK_SIZE}L）**：{tank95} 元\n\n"
            f"📊 **年初至今累计**：{sg}{ytd95} 元/升\n\n"
            f"🔍 **趋势**：{streak}\n\n"
            f"💡 **建议**：{tip}"
        )

    header = f"🕐 {today} {now_t}　|　📌 当前处于 {cur_str} 周期\n\n{wx}📅 距上次调价已过 **{days_cnt}** 天"

    if has_change and latest["type"] != "flat":
        title = f"🛢️ 油价{'🔺上调' if latest['type']=='up' else '🔻下调'} | 今晚24时生效"
        body = (
            f"## {title}\n\n"
            f"{header}\n\n"
            f"---\n\n"
            f"### 现行价格\n\n"
            f"{price_block()}\n\n"
            f"---\n\n"
            f"### 实用信息\n\n"
            f"{info_block()}\n\n"
            f"---\n\n"
            f"📅 上一轮：{prev_str}\n\n"
            f"📅 下一轮预计：{nxt}\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )
    elif recent:
        title = f"🛢️ 油价{'🔺已上调' if latest['type']=='up' else '🔻已下调'} | {today}"
        body = (
            f"## {title}\n\n"
            f"{header}\n\n"
            f"---\n\n"
            f"### 现行价格\n\n"
            f"{price_block()}\n\n"
            f"---\n\n"
            f"### 实用信息\n\n"
            f"{info_block()}\n\n"
            f"---\n\n"
            f"📅 上一轮：{prev_str}\n\n"
            f"📅 下一轮预计：{nxt}\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )
    else:
        title = f"⛽ 今日油价 | {today}"
        body = (
            f"## {title}\n\n"
            f"{header}\n\n"
            f"---\n\n"
            f"### 现行价格\n\n"
            f"{price_block()}\n\n"
            f"---\n\n"
            f"### 实用信息\n\n"
            f"{info_block()}\n\n"
            f"---\n\n"
            f"📅 上一轮：{prev_str}\n\n"
            f"📅 下一轮预计：{nxt}\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )

    return title, body


def main():
    has_change = len(sys.argv) > 1 and sys.argv[1] == "true"
    data = load_data()
    prices = data.get("prices2026") or data.get("prices", [])
    if not prices:
        print("❌ 无油价数据")
        return

    print("🌤 获取天气...")
    weather = fetch_weather()

    print("📝 构建消息...")
    title, body = build_msg(prices, has_change, weather)

    if os.environ.get("SERVERCHAN_SENDKEY"):
        print(f"📤 [微信] {title}")
        send_serverchan(os.environ["SERVERCHAN_SENDKEY"], title, body)

    if os.environ.get("DINGTALK_WEBHOOK"):
        print(f"📤 [钉钉] {title}")
        send_dingtalk(os.environ["DINGTALK_WEBHOOK"], title, body)


if __name__ == "__main__":
    main()
