#!/usr/bin/env python3
"""
每日油价+天气通知 — 微信 + 钉钉双通道

用法:
  python send_notification.py [changed]   # changed = "true" 表示今日有调价

环境变量:
  SERVERCHAN_SENDKEY  - Server酱 SendKey（微信推送）
  DINGTALK_WEBHOOK    - 钉钉机器人 Webhook
"""

import json, sys, os, hmac, hashlib, base64, time, urllib.parse
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    print("⚠️ 需要安装 requests: pip install requests")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_FILE = PROJECT_ROOT / "data.json"
PAGE_URL = "https://ToniaXuu.github.io/fuel-price-tracker/"

# 山东济南坐标
LAT = 36.65
LON = 117.00
TZ = "Asia/Shanghai"


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ========================== 天气 ==========================

def fetch_weather():
    """通过 Open-Meteo 免费 API 获取济南当日天气（无需 API Key）"""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            f"&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max"
            f"&timezone={TZ}&forecast_days=1"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        daily = data.get("daily", {})
        if not daily:
            return None

        t_max = daily["temperature_2m_max"][0]
        t_min = daily["temperature_2m_min"][0]
        code = daily["weathercode"][0]
        rain_pct = daily.get("precipitation_probability_max", [0])[0]

        # WMO 天气码 → 中文
        weather_map = {
            0: "☀️ 晴", 1: "🌤 少云", 2: "⛅ 多云", 3: "☁️ 阴",
            45: "🌫 雾", 48: "🌫 雾凇", 51: "🌧 小雨", 53: "🌧 中雨",
            55: "🌧 大雨", 61: "🌧 阵雨", 63: "🌧 中阵雨", 65: "🌧 大阵雨",
            71: "🌨 小雪", 73: "🌨 中雪", 75: "🌨 大雪",
            80: "🌦 阵雨", 81: "🌦 中阵雨", 82: "🌦 大阵雨",
            95: "⛈ 雷暴", 96: "⛈ 雷暴+冰雹", 99: "⛈ 强雷暴+冰雹"
        }
        weather_text = weather_map.get(code, f"🌡 未知({code})")

        return {
            "date": daily["time"][0],
            "weather": weather_text,
            "temp_max": int(t_max),
            "temp_min": int(t_min),
            "rain_pct": rain_pct,
        }
    except Exception as e:
        print(f"  ⚠️ 天气获取失败: {e}")
        return None


# ========================== Server酱（微信）==========================

def send_serverchan(sendkey, title, content):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    resp = requests.post(url, data={"title": title, "desp": content}, timeout=15)
    result = resp.json()
    if result.get("code") == 0:
        print("  ✅ 微信通知发送成功")
    else:
        print(f"  ⚠️ 微信通知失败: {result.get('message', resp.text)}")


# ========================== 钉钉 ==========================

def send_dingtalk(webhook, markdown_title, markdown_text):
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": markdown_title, "text": markdown_text}
    }
    secret = os.environ.get("DINGTALK_SECRET", "")
    url = webhook
    if secret:
        ts, sign = _dingtalk_sign(secret)
        url = f"{webhook}&timestamp={ts}&sign={sign}"
    resp = requests.post(url, json=payload, timeout=15)
    result = resp.json()
    if result.get("errcode") == 0:
        print("  ✅ 钉钉通知发送成功")
    else:
        print(f"  ⚠️ 钉钉通知失败: {result.get('errmsg', resp.text)}")


def _dingtalk_sign(secret):
    ts = str(round(time.time() * 1000))
    s = f"{ts}\n{secret}"
    h = hmac.new(secret.encode(), s.encode(), hashlib.sha256).digest()
    return ts, urllib.parse.quote_plus(base64.b64encode(h))


# ========================== 消息构建 ==========================

def format_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.month}月{d.day}日"


def today_cn():
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{now.month}月{now.day}日 {weekdays[now.weekday()]}"


def build_daily_report(prices, has_change, weather):
    """构建每日油价+天气通知"""
    latest = prices[-1]
    prev = prices[-2] if len(prices) >= 2 else latest
    date_str = format_date(latest["date"])
    today = today_cn()

    # ---- 天气 ----
    wx_section_wx = ""
    wx_section_dt = ""
    if weather:
        wx_line = (
            f"☁️ 山东·济南：{weather['weather']}  {weather['temp_min']}°C ~ {weather['temp_max']}°C"
        )
        if weather["rain_pct"] and weather["rain_pct"] > 20:
            wx_line += f"  降水概率 {weather['rain_pct']}%"
        wx_section_wx = wx_line + "\n\n"
        wx_section_dt = wx_line + "\n\n"

    # ---- 油价 ----
    delta_92 = round(latest["p92"] - prev["p92"], 2)
    delta_95 = round(latest["p95"] - prev["p95"], 2)
    delta_diesel = round(latest["pDiesel"] - prev["pDiesel"], 2)
    arrow = lambda v: "▲" if v > 0 else ("▼" if v < 0 else "—")

    if has_change and latest["type"] != "flat":
        # 有调价 → 强调变动
        type_map = {"up": "🔺 上调", "down": "🔻 下调"}
        type_str = type_map.get(latest["type"], "？")
        gas_ton = abs(latest["gas"])
        diesel_ton = abs(latest["diesel"])
        sign = lambda v: "+" if v > 0 else ""

        wx_title = f"🛢️ 油价{type_str} | {today}"
        wx_body = (
            f"{wx_section_wx}"
            f"📅 {date_str} 调价 · 第{latest['round']}轮\n"
            f"{type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n\n"
            f"⛽ 92#：{prev['p92']} → {latest['p92']} 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"⛽ 95#：{prev['p95']} → {latest['p95']} 元/升（{arrow(delta_95)} {sign(delta_95)}{delta_95}）\n"
            f"🛢️ 0#柴油：{prev['pDiesel']} → {latest['pDiesel']} 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )

        dt_title = wx_title
        dt_body = (
            f"{wx_section_dt}"
            f"## 🛢️ 油价{type_str}\n\n"
            f"**{date_str} 调价 · 第{latest['round']}轮**\n\n"
            f"{type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n\n"
            f"- ⛽ 92#：~~{prev['p92']}~~ → **{latest['p92']}** 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"- ⛽ 95#：~~{prev['p95']}~~ → **{latest['p95']}** 元/升（{arrow(delta_95)} {sign(delta_95)}{delta_95}）\n"
            f"- 🛢️ 0#柴油：~~{prev['pDiesel']}~~ → **{latest['pDiesel']}** 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )
    else:
        # 无调价 → 日常油价播报
        wx_title = f"⛽ 今日油价 | {today}"
        wx_body = (
            f"{wx_section_wx}"
            f"📅 {date_str} 油价（维持上轮不变）\n\n"
            f"⛽ 92#：{latest['p92']} 元/升\n"
            f"⛽ 95#：{latest['p95']} 元/升\n"
            f"⛽ 98#：{latest['p98']} 元/升\n"
            f"🛢️ 0#柴油：{latest['pDiesel']} 元/升\n\n"
            f"— 以上为济南地区最高零售价 —\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )

        dt_title = wx_title
        dt_body = (
            f"{wx_section_dt}"
            f"## ⛽ 今日油价 · 济南\n\n"
            f"**{date_str}** （维持上轮不变）\n\n"
            f"- ⛽ 92#：**{latest['p92']}** 元/升\n"
            f"- ⛽ 95#：**{latest['p95']}** 元/升\n"
            f"- ⛽ 98#：**{latest['p98']}** 元/升\n"
            f"- 🛢️ 0#柴油：**{latest['pDiesel']}** 元/升\n\n"
            f"> 以上为济南地区最高零售价\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )

    return wx_title, wx_body, dt_title, dt_body


# ========================== 主流程 ==========================

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
    wx_title, wx_body, dt_title, dt_body = build_daily_report(prices, has_change, weather)

    # 1) 微信
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "")
    if sendkey:
        print(f"📤 [微信] {wx_title}")
        send_serverchan(sendkey, wx_title, wx_body)
    else:
        print("⏭️ 未配置 SERVERCHAN_SENDKEY")

    # 2) 钉钉
    webhook = os.environ.get("DINGTALK_WEBHOOK", "")
    if webhook:
        print(f"📤 [钉钉] {dt_title}")
        send_dingtalk(webhook, dt_title, dt_body)
    else:
        print("⏭️ 未配置 DINGTALK_WEBHOOK")


if __name__ == "__main__":
    main()
