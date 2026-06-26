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


def now_time_cn():
    """当前精确时间，如 09:05"""
    return datetime.now().strftime("%H:%M")


def add_working_days(start_str, n):
    """从 start_date 起算 n 个工作日后的日期"""
    start = datetime.strptime(start_str, "%Y-%m-%d")
    days_added = 0
    current = start
    while days_added < n:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0-4 周一至周五
            days_added += 1
    return current.strftime("%Y-%m-%d")


def build_calendar_info(prices, latest):
    """构建日历信息：上一轮、当前轮、下一轮"""
    idx = next((i for i, p in enumerate(prices) if p["round"] == latest["round"]), -1)
    prev_entry = prices[idx - 1] if idx > 0 else None
    # 下一轮调价日 ≈ 当前轮日期 + 10个工作日
    next_date = add_working_days(latest["date"], 10)

    prev_str = f"第{prev_entry['round']}轮 {format_date(prev_entry['date'])}" if prev_entry else "—"
    current_str = f"第{latest['round']}轮 {format_date(latest['date'])}"
    next_str = format_date(next_date)

    return prev_str, current_str, next_str


def build_daily_report(prices, has_change, weather):
    """构建每日油价+天气通知"""
    latest = prices[-1]
    prev = prices[-2] if len(prices) >= 2 else latest
    date_str = format_date(latest["date"])
    today = today_cn()
    now_time = now_time_cn()
    today_iso = datetime.now().strftime("%Y-%m-%d")
    yesterday_iso = (datetime.now().replace(day=datetime.now().day - 1) if datetime.now().day > 1
                     else datetime.now().replace(month=datetime.now().month - 1, day=28)).strftime("%Y-%m-%d")

    # 判断最近一次调价是否"新鲜"（数据条目日期为今天或昨天）
    recent_change = latest["date"] in (today_iso, yesterday_iso) and latest["type"] != "flat"

    # ---- 日历信息 ----
    prev_round, cur_round, next_date = build_calendar_info(prices, latest)

    # ---- 当前时间 + 轮次状态 ----
    time_status = f"🕐 {today} {now_time}\n📌 当前处于 {cur_round} 周期内"

    # ---- 天气 ----
    wx_section_wx = ""
    wx_section_dt = ""
    if weather:
        wx_line = (
            f"☁️ 山东·济南：{weather['weather']}  {weather['temp_min']}°C ~ {weather['temp_max']}°C"
        )
        if weather["rain_pct"] and weather["rain_pct"] > 20:
            wx_line += f"  降水概率 {weather['rain_pct']}%"
        wx_section_wx = f"🌤 天气 | {wx_line}\n\n"
        wx_section_dt = f"🌤 天气 | {wx_line}\n\n"

    # ---- 油价明细 ----
    delta_92 = round(latest["p92"] - prev["p92"], 2)
    delta_95 = round(latest["p95"] - prev["p95"], 2)
    delta_diesel = round(latest["pDiesel"] - prev["pDiesel"], 2)
    arrow = lambda v: "▲" if v > 0 else ("▼" if v < 0 else "—")
    sign = lambda v: "+" if v > 0 else ""
    oil_detail = (
        f"⛽ 92#：**{latest['p92']}** 元/升\n"
        f"⛽ 95#：**{latest['p95']}** 元/升\n"
        f"⛽ 98#：**{latest['p98']}** 元/升\n"
        f"🛢️ 0#柴油：**{latest['pDiesel']}** 元/升"
    )
    oil_detail_plain = (
        f"⛽ 92#：{latest['p92']} 元/升\n"
        f"⛽ 95#：{latest['p95']} 元/升\n"
        f"⛽ 98#：{latest['p98']} 元/升\n"
        f"🛢️ 0#柴油：{latest['pDiesel']} 元/升"
    )

    if has_change and latest["type"] != "flat":
        # 18:00 刚抓到调价公告 → "今晚24时起"
        type_map = {"up": "🔺 上调", "down": "🔻 下调"}
        type_str = type_map.get(latest["type"], "？")
        gas_ton = abs(latest["gas"])
        diesel_ton = abs(latest["diesel"])
        tag = "⏰ 今晚24时生效"
        adj_detail = (
            f"\n📊 变动 | {type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n"
            f"⛽ 92#：{prev['p92']} → {latest['p92']} 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"🛢️ 0#柴油：{prev['pDiesel']} → {latest['pDiesel']} 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）"
        )
        adj_detail_md = (
            f"\n\n📊 **变动明细**\n\n"
            f"{type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n\n"
            f"- ⛽ 92#：~~{prev['p92']}~~ → **{latest['p92']}** 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"- ⛽ 95#：~~{prev['p95']}~~ → **{latest['p95']}** 元/升（{arrow(delta_95)} {sign(delta_95)}{delta_95}）\n"
            f"- 🛢️ 0#柴油：~~{prev['pDiesel']}~~ → **{latest['pDiesel']}** 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）"
        )

        wx_title = f"🛢️ 油价{type_str} | {today}"
        wx_body = (
            f"{time_status}\n\n"
            f"{wx_section_wx}"
            f"📢 **{tag}**\n\n"
            f"{oil_detail_plain}\n"
            f"{adj_detail}\n\n"
            f"📅 上一轮：{prev_round}\n"
            f"📅 下一轮：{next_date}\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
        dt_title = f"🛢️ 油价{type_str} | {tag}"
        dt_body = (
            f"## 🛢️ 油价{type_str}\n\n"
            f"{time_status}\n\n"
            f"> ⏰ **今晚24时生效**\n\n"
            f"---\n\n"
            f"### 当前价格\n\n"
            f"{oil_detail}\n"
            f"{adj_detail_md}\n\n"
            f"---\n\n"
            f"📅 上一轮：{prev_round}\n\n"
            f"📅 下一轮预计：{next_date}\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )

    elif recent_change:
        # 昨天/今天生效的调价，但数据已落地 → "已下调/上调"
        type_map = {"up": "🔺 已上调", "down": "🔻 已下调"}
        type_str = type_map.get(latest["type"], "？")
        gas_ton = abs(latest["gas"])
        diesel_ton = abs(latest["diesel"])
        adj_detail = (
            f"\n📊 变动 | {type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n"
            f"⛽ 92#：{prev['p92']} → {latest['p92']} 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"🛢️ 0#柴油：{prev['pDiesel']} → {latest['pDiesel']} 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）"
        )
        adj_detail_md = (
            f"\n\n📊 **变动明细**\n\n"
            f"{type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n\n"
            f"- ⛽ 92#：~~{prev['p92']}~~ → **{latest['p92']}** 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"- ⛽ 95#：~~{prev['p95']}~~ → **{latest['p95']}** 元/升（{arrow(delta_95)} {sign(delta_95)}{delta_95}）\n"
            f"- 🛢️ 0#柴油：~~{prev['pDiesel']}~~ → **{latest['pDiesel']}** 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）"
        )

        wx_title = f"🛢️ 油价{type_str} | {today}"
        wx_body = (
            f"{time_status}\n\n"
            f"{wx_section_wx}"
            f"{oil_detail_plain}\n"
            f"{adj_detail}\n\n"
            f"📅 上一轮：{prev_round}\n"
            f"📅 下一轮：{next_date}\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
        dt_title = wx_title
        dt_body = (
            f"## 🛢️ 油价{type_str}\n\n"
            f"{time_status}\n\n"
            f"---\n\n"
            f"### 现行价格\n\n"
            f"{oil_detail}\n"
            f"{adj_detail_md}\n\n"
            f"---\n\n"
            f"📅 上一轮：{prev_round}\n\n"
            f"📅 下一轮预计：{next_date}\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )

    else:
        # 日常油价播报
        wx_title = f"⛽ 今日油价 | {today}"
        wx_body = (
            f"{time_status}\n\n"
            f"{wx_section_wx}"
            f"{oil_detail_plain}\n\n"
            f"📅 上一轮：{prev_round}\n"
            f"📅 下一轮预计：{next_date}\n\n"
            f"— 以上为济南地区最高零售价 —\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
        dt_title = wx_title
        dt_body = (
            f"## ⛽ 今日油价 · 济南\n\n"
            f"{time_status}\n\n"
            f"---\n\n"
            f"### 现行价格\n\n"
            f"{oil_detail}\n\n"
            f"---\n\n"
            f"📅 上一轮：{prev_round}\n\n"
            f"📅 下一轮预计：{next_date}\n\n"
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
