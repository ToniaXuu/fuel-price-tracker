#!/usr/bin/env python3
"""
微信通知脚本
调价时通过 Server酱 推送通知到微信。

用法:
  python send_notification.py <SENDKEY>

环境变量备选:
  SERVERCHAN_SENDKEY
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    print("⚠️ 需要安装 requests: pip install requests")
    sys.exit(1)

# 文件路径
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_FILE = PROJECT_ROOT / "data.json"
PAGE_URL = "https://ToniaXuu.github.io/fuel-price-tracker/"


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def format_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.month}月{d.day}日"


def send_serverchan(sendkey, title, content):
    """通过 Server酱 发送通知"""
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    resp = requests.post(url, data={"title": title, "desp": content}, timeout=15)
    result = resp.json()
    if result.get("code") == 0:
        print("✅ 微信通知发送成功")
    else:
        print(f"⚠️ 通知发送失败: {result.get('message', resp.text)}")
    return result


def main():
    # 从命令行参数或环境变量获取 SendKey
    sendkey = None
    if len(sys.argv) > 1:
        sendkey = sys.argv[1]
    sendkey = sendkey or os.environ.get("SERVERCHAN_SENDKEY")
    if not sendkey:
        print("❌ 未提供 SendKey，跳过通知")
        sys.exit(0)

    data = load_data()
    prices = data.get("prices2026") or data.get("prices", [])
    if len(prices) < 2:
        print("⚠️ 数据不足，跳过通知")
        return

    latest = prices[-1]
    prev = prices[-2]

    # 构建通知内容
    date_str = format_date(latest["date"])
    type_map = {"up": "🔺 上调", "down": "🔻 下调", "flat": "➖ 搁浅"}
    type_str = type_map.get(latest["type"], "？")

    # 计算每升变动
    delta_92 = round(latest["p92"] - prev["p92"], 2)
    delta_95 = round(latest["p95"] - prev["p95"], 2)
    delta_diesel = round(latest["pDiesel"] - prev["pDiesel"], 2)

    arrow = lambda v: "▲" if v > 0 else ("▼" if v < 0 else "—")
    sign = lambda v: "+" if v > 0 else ""

    title = f"🛢️ 油价{type_str} | {date_str} 第{latest['round']}轮"

    if latest["type"] == "flat":
        content = (
            f"📅 {date_str} · 第{latest['round']}轮 · 搁浅\n\n"
            f"本轮汽、柴油价格不作调整，维持上轮价格。\n\n"
            f"⛽ 92#：{latest['p92']} 元/升\n"
            f"🛢️ 0#柴油：{latest['pDiesel']} 元/升\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
    else:
        gas_ton = abs(latest["gas"])
        diesel_ton = abs(latest["diesel"])
        content = (
            f"📅 {date_str} · 第{latest['round']}轮\n"
            f"{type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n\n"
            f"⛽ 92#：{prev['p92']} → {latest['p92']} 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"⛽ 95#：{prev['p95']} → {latest['p95']} 元/升（{arrow(delta_95)} {sign(delta_95)}{delta_95}）\n"
            f"🛢️ 0#柴油：{prev['pDiesel']} → {latest['pDiesel']} 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )

    print(f"📤 发送通知: {title}")
    send_serverchan(sendkey, title, content)


if __name__ == "__main__":
    main()
