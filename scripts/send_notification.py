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
TANK_SIZE = 50  # 标准家用油箱 50L

LAT = 36.65
LON = 117.00
TZ = "Asia/Shanghai"


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ========================== 天气 ==========================

def fetch_weather():
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

        t_max = int(daily["temperature_2m_max"][0])
        t_min = int(daily["temperature_2m_min"][0])
        code = daily["weathercode"][0]
        rain_pct = daily.get("precipitation_probability_max", [0])[0]

        weather_map = {
            0: "☀️ 晴", 1: "🌤 少云", 2: "⛅ 多云", 3: "☁️ 阴",
            45: "🌫 雾", 48: "🌫 雾凇", 51: "🌧 小雨", 53: "🌧 中雨",
            55: "🌧 大雨", 61: "🌧 阵雨", 63: "🌧 中阵雨", 65: "🌧 大阵雨",
            71: "🌨 小雪", 73: "🌨 中雪", 75: "🌨 大雪",
            80: "🌦 阵雨", 81: "🌦 中阵雨", 82: "🌦 大阵雨",
            95: "⛈ 雷暴", 96: "⛈ 雷暴+冰雹", 99: "⛈ 强雷暴+冰雹"
        }
        weather_text = weather_map.get(code, f"🌡 未知({code})")
        return dict(date=daily["time"][0], weather=weather_text,
                    temp_max=t_max, temp_min=t_min, rain_pct=rain_pct)
    except Exception as e:
        print(f"  ⚠️ 天气获取失败: {e}")
        return None


# ========================== 推送 ==========================

def send_serverchan(sendkey, title, content):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    resp = requests.post(url, data={"title": title, "desp": content}, timeout=15)
    r = resp.json()
    if r.get("code") == 0:
        print("  ✅ 微信通知发送成功")
    else:
        print(f"  ⚠️ 微信通知失败: {r.get('message', resp.text)}")


def send_dingtalk(webhook, title, text):
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    secret = os.environ.get("DINGTALK_SECRET", "")
    url = webhook
    if secret:
        ts, sign = _dingtalk_sign(secret)
        url = f"{webhook}&timestamp={ts}&sign={sign}"
    resp = requests.post(url, json=payload, timeout=15)
    r = resp.json()
    if r.get("errcode") == 0:
        print("  ✅ 钉钉通知发送成功")
    else:
        print(f"  ⚠️ 钉钉通知失败: {r.get('errmsg', resp.text)}")


def _dingtalk_sign(secret):
    ts = str(round(time.time() * 1000))
    h = hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()
    return ts, urllib.parse.quote_plus(base64.b64encode(h))


# ========================== 工具函数 ==========================

def format_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.month}月{d.day}日"


def today_cn():
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{now.month}月{now.day}日 {weekdays[now.weekday()]}"


def now_time_cn():
    return datetime.now().strftime("%H:%M")


def add_working_days(start_str, n):
    start = datetime.strptime(start_str, "%Y-%m-%d")
    days_added = 0
    cur = start
    while days_added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days_added += 1
    return cur.strftime("%Y-%m-%d")


def days_since(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (datetime.now() - d).days


def detect_streak(prices):
    """检测最近连涨/连降趋势"""
    if len(prices) < 2:
        return "数据不足"
    last = prices[-1]
    streak = [last]
    for i in range(len(prices) - 2, -1, -1):
        if prices[i]["type"] == last["type"]:
            streak.insert(0, prices[i])
        else:
            break
    if len(streak) >= 2 and last["type"] == "down":
        total = round(streak[-1]["p92"] - streak[0]["p92"], 2)
        timespan = f"{format_date(streak[0]['date'])}→{format_date(streak[-1]['date'])}"
        return f"▼ 近{len(streak)}轮连降，累计 -{abs(total)} 元/升（{timespan}）"
    elif len(streak) >= 2 and last["type"] == "up":
        total = round(streak[-1]["p92"] - streak[0]["p92"], 2)
        timespan = f"{format_date(streak[0]['date'])}→{format_date(streak[-1]['date'])}"
        return f"▲ 近{len(streak)}轮连涨，累计 +{total} 元/升（{timespan}）"
    else:
        return f"↔️ 单次{ {'up':'上调','down':'下调','flat':'搁浅'}.get(last['type'],'?') }"


def build_tip(delta_92):
    """根据最近变动给出用车建议"""
    if delta_92 < 0:
        return "💡 92# 下降中，若油箱不急需建议先少量加油，等待下一轮"
    elif delta_92 == 0:
        return "💡 油价暂时稳定，不急于加油可关注下一轮调价"
    else:
        return "💡 92# 上涨趋势中，建议趁周末及时加满"


# ========================== 主消息构建 ==========================

def build_message(prices, has_change, weather):
    latest = prices[-1]
    prev = prices[-2] if len(prices) >= 2 else latest
    today = today_cn()
    now_t = now_time_cn()
    today_iso = datetime.now().strftime("%Y-%m-%d")
    yesterday_iso = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    recent_change = latest["date"] in (today_iso, yesterday_iso) and latest["type"] != "flat"

    # ---- 基础数据 ----
    delta_92 = round(latest["p92"] - prev["p92"], 2)
    delta_95 = round(latest["p95"] - prev["p95"], 2)
    delta_diesel = round(latest["pDiesel"] - prev["pDiesel"], 2)
    ar = lambda v: "▲" if v > 0 else ("▼" if v < 0 else "—")
    sg = lambda v: "+" if v > 0 else ""

    # ---- 轮次日历 ----
    idx = next((i for i, p in enumerate(prices) if p["round"] == latest["round"]), -1)
    pe = prices[idx - 1] if idx > 0 else None
    next_date = add_working_days(latest["date"], 10)
    prev_str = f"第{pe['round']}轮 {format_date(pe['date'])}" if pe else "—"
    cur_str = f"第{latest['round']}轮 {format_date(latest['date'])}"

    # ---- 附加信息 ----
    tank92 = round(latest["p92"] * TANK_SIZE, 2)
    base = 6.67  # 年初92基础价
    ytd = round(latest["p92"] - base, 2)
    days_cnt = days_since(latest["date"])
    streak_text = detect_streak(prices)

    # ---- 天气 ----
    wx_line = ""
    if weather:
        wx_line = f"☁️ {weather['weather']}  {weather['temp_min']}°C ~ {weather['temp_max']}°C"
        if weather["rain_pct"] and weather["rain_pct"] > 20:
            wx_line += f"  降水概率 {weather['rain_pct']}%"

    # ---- 拼接头部 ----
    header = (
        f"🕐 {today} {now_t}\n"
        f"📌 当前处于 {cur_str} 周期内\n"
        f"📅 距上次调价已过 {days_cnt} 天"
    )
    if wx_line:
        header += f"\n🌤 {wx_line}"

    # ---- 价格表 ----
    price_tbl = (
        f"⛽ 92# —— **{latest['p92']}** 元/升\n"
        f"⛽ 95# —— **{latest['p95']}** 元/升\n"
        f"⛽ 98# —— **{latest['p98']}** 元/升\n"
        f"🛢️ 0#柴油 —— **{latest['pDiesel']}** 元/升"
    )
    price_tbl_plain = (
        f"⛽ 92# —— {latest['p92']} 元/升\n"
        f"⛽ 95# —— {latest['p95']} 元/升\n"
        f"⛽ 98# —— {latest['p98']} 元/升\n"
        f"🛢️ 0#柴油 —— {latest['pDiesel']} 元/升"
    )

    # ---- 实用信息 ----
    info = (
        f"💰 加满一箱92#（{TANK_SIZE}L）：**{tank92} 元**\n"
        f"📊 年初至今 92# 累计：**{sg(ytd)}{ytd} 元/升**\n"
        f"🔍 趋势：{streak_text}\n"
        f"💡 {build_tip(delta_92)}"
    )
    info_plain = (
        f"💰 加满一箱92#（{TANK_SIZE}L）：{tank92} 元\n"
        f"📊 年初至今 92# 累计：{sg(ytd)}{ytd} 元/升\n"
        f"🔍 趋势：{streak_text}\n"
        f"💡 {build_tip(delta_92)}"
    )

    # ---- 日历 ----
    cal = f"📅 上一轮：{prev_str}　｜　📅 下一轮预计：{next_date}"

    # ========== 三个分支 ==========

    if has_change and latest["type"] != "flat":
        tm = {"up": "🔺 上调", "down": "🔻 下调"}
        ts = tm.get(latest["type"], "？")
        gt = abs(latest["gas"])
        dt = abs(latest["diesel"])

        change_detail_plain = (
            f"\n【变动明细】\n"
            f"{ts} {gt}元/吨（汽油）/ {dt}元/吨（柴油）\n"
            f"92#：{prev['p92']} → {latest['p92']}（{ar(delta_92)} {sg(delta_92)}{delta_92}）\n"
            f"95#：{prev['p95']} → {latest['p95']}（{ar(delta_95)} {sg(delta_95)}{delta_95}）\n"
            f"0#柴油：{prev['pDiesel']} → {latest['pDiesel']}（{ar(delta_diesel)} {sg(delta_diesel)}{delta_diesel}）"
        )
        change_detail_md = (
            f"\n\n📊 **变动明细**\n\n"
            f"{ts} {gt}元/吨（汽油）/ {dt}元/吨（柴油）\n\n"
            f"- ⛽ 92#：~~{prev['p92']}~~ → **{latest['p92']}**（{ar(delta_92)} {sg(delta_92)}{delta_92}）\n"
            f"- ⛽ 95#：~~{prev['p95']}~~ → **{latest['p95']}**（{ar(delta_95)} {sg(delta_95)}{delta_95}）\n"
            f"- 🛢️ 0#柴油：~~{prev['pDiesel']}~~ → **{latest['pDiesel']}**（{ar(delta_diesel)} {sg(delta_diesel)}{delta_diesel}）"
        )

        wx_title = f"🛢️ 油价{ts} | {today}"
        wx_body = (
            f"{header}\n\n"
            f"⏰ **今晚24时生效**\n\n"
            f"{price_tbl_plain}\n"
            f"{change_detail_plain}\n\n"
            f"{info_plain}\n\n"
            f"{cal}\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
        dt_title = f"🛢️ 油价{ts} | ⏰ 今晚24时生效"
        dt_body = (
            f"## 🛢️ 油价{ts}\n\n"
            f"{header}\n\n"
            f"> ⏰ **今晚24时生效**\n\n"
            f"---\n\n"
            f"### 现行价格\n\n"
            f"{price_tbl}\n"
            f"{change_detail_md}\n\n"
            f"---\n\n"
            f"### 📊 实用信息\n\n"
            f"{info}\n\n"
            f"---\n\n"
            f"{cal}\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )

    elif recent_change:
        tm = {"up": "🔺 已上调", "down": "🔻 已下调"}
        ts = tm.get(latest["type"], "？")
        gt = abs(latest["gas"])
        dt = abs(latest["diesel"])
        tag = "✅ 昨日已生效" if latest["date"] == yesterday_iso else "📢 今日已生效"

        change_detail_plain = (
            f"\n【变动明细】\n"
            f"{ts} {gt}元/吨（汽油）/ {dt}元/吨（柴油）\n"
            f"92#：{prev['p92']} → {latest['p92']}（{ar(delta_92)} {sg(delta_92)}{delta_92}）\n"
            f"95#：{prev['p95']} → {latest['p95']}（{ar(delta_95)} {sg(delta_95)}{delta_95}）\n"
            f"0#柴油：{prev['pDiesel']} → {latest['pDiesel']}（{ar(delta_diesel)} {sg(delta_diesel)}{delta_diesel}）"
        )
        change_detail_md = (
            f"\n\n📊 **变动明细**\n\n"
            f"{ts} {gt}元/吨（汽油）/ {dt}元/吨（柴油）\n\n"
            f"- ⛽ 92#：~~{prev['p92']}~~ → **{latest['p92']}**（{ar(delta_92)} {sg(delta_92)}{delta_92}）\n"
            f"- ⛽ 95#：~~{prev['p95']}~~ → **{latest['p95']}**（{ar(delta_95)} {sg(delta_95)}{delta_95}）\n"
            f"- 🛢️ 0#柴油：~~{prev['pDiesel']}~~ → **{latest['pDiesel']}**（{ar(delta_diesel)} {sg(delta_diesel)}{delta_diesel}）"
        )

        wx_title = f"🛢️ 油价{ts} | {today}"
        wx_body = (
            f"{header}\n\n"
            f"{tag}\n\n"
            f"{price_tbl_plain}\n"
            f"{change_detail_plain}\n\n"
            f"{info_plain}\n\n"
            f"{cal}\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
        dt_title = wx_title
        dt_body = (
            f"## 🛢️ 油价{ts}\n\n"
            f"{header}\n\n"
            f"---\n\n"
            f"### 现行价格\n\n"
            f"{price_tbl}\n"
            f"{change_detail_md}\n\n"
            f"---\n\n"
            f"### 📊 实用信息\n\n"
            f"{info}\n\n"
            f"---\n\n"
            f"{cal}\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )

    else:
        wx_title = f"⛽ 今日油价 | {today}"
        wx_body = (
            f"{header}\n\n"
            f"{price_tbl_plain}\n\n"
            f"{info_plain}\n\n"
            f"{cal}\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
        dt_title = wx_title
        dt_body = (
            f"## ⛽ 今日油价 · 济南\n\n"
            f"{header}\n\n"
            f"---\n\n"
            f"### 现行价格\n\n"
            f"{price_tbl}\n\n"
            f"---\n\n"
            f"### 📊 实用信息\n\n"
            f"{info}\n\n"
            f"---\n\n"
            f"{cal}\n\n"
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
    wx_title, wx_body, dt_title, dt_body = build_message(prices, has_change, weather)

    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "")
    if sendkey:
        print(f"📤 [微信] {wx_title}")
        send_serverchan(sendkey, wx_title, wx_body)
    else:
        print("⏭️ 未配置 SERVERCHAN_SENDKEY")

    webhook = os.environ.get("DINGTALK_WEBHOOK", "")
    if webhook:
        print(f"📤 [钉钉] {dt_title}")
        send_dingtalk(webhook, dt_title, dt_body)
    else:
        print("⏭️ 未配置 DINGTALK_WEBHOOK")


if __name__ == "__main__":
    main()
