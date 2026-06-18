#!/usr/bin/env python3
"""
调价通知脚本 — 微信 + 钉钉双通道推送

用法:
  python send_notification.py

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

# 文件路径
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_FILE = PROJECT_ROOT / "data.json"
PAGE_URL = "https://ToniaXuu.github.io/fuel-price-tracker/"

# 钉钉加签密钥（可选，安全设置有加签时需要）
DINGTALK_SECRET = os.environ.get("DINGTALK_SECRET", "")


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def format_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.month}月{d.day}日"


# ============ Server酱（微信）============

def send_serverchan(sendkey, title, content):
    """通过 Server酱 推送到微信"""
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    resp = requests.post(url, data={"title": title, "desp": content}, timeout=15)
    result = resp.json()
    if result.get("code") == 0:
        print("  ✅ 微信通知发送成功")
    else:
        print(f"  ⚠️ 微信通知失败: {result.get('message', resp.text)}")


# ============ 钉钉机器人 ============

def _dingtalk_sign(secret):
    """生成钉钉机器人加签"""
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode("utf-8")
    string_to_sign = f"{timestamp}\n{secret}"
    string_to_sign_enc = string_to_sign.encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign


def send_dingtalk(webhook, markdown_title, markdown_text):
    """通过钉钉机器人发送 Markdown 消息"""
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": markdown_title,
            "text": markdown_text
        }
    }

    url = webhook
    if DINGTALK_SECRET:
        ts, sign = _dingtalk_sign(DINGTALK_SECRET)
        url = f"{webhook}&timestamp={ts}&sign={sign}"

    resp = requests.post(url, json=payload, timeout=15)
    result = resp.json()
    if result.get("errcode") == 0:
        print("  ✅ 钉钉通知发送成功")
    else:
        print(f"  ⚠️ 钉钉通知失败: {result.get('errmsg', resp.text)}")


# ============ 构建消息 ============

def build_messages(prices):
    """根据最新数据构建所有渠道的通知内容"""
    latest = prices[-1]
    prev = prices[-2]

    date_str = format_date(latest["date"])
    type_map = {"up": "🔺 上调", "down": "🔻 下调", "flat": "➖ 搁浅"}
    type_str = type_map.get(latest["type"], "？")

    delta_92 = round(latest["p92"] - prev["p92"], 2)
    delta_95 = round(latest["p95"] - prev["p95"], 2)
    delta_diesel = round(latest["pDiesel"] - prev["pDiesel"], 2)

    arrow = lambda v: "▲" if v > 0 else ("▼" if v < 0 else "—")
    sign = lambda v: "+" if v > 0 else ""

    title = f"🛢️ 油价{type_str} | {date_str} 第{latest['round']}轮"

    if latest["type"] == "flat":
        wechat_content = (
            f"📅 {date_str} · 第{latest['round']}轮 · 搁浅\n\n"
            f"本轮汽、柴油价格不作调整，维持上轮价格。\n\n"
            f"⛽ 92#：{latest['p92']} 元/升\n"
            f"🛢️ 0#柴油：{latest['pDiesel']} 元/升\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
        dingtalk_title = title
        dingtalk_text = (
            f"## 🛢️ 油价{type_str}\n\n"
            f"**{date_str} · 第{latest['round']}轮**\n\n"
            f"本轮汽、柴油价格不作调整，维持上轮价格。\n\n"
            f"- ⛽ 92#：**{latest['p92']}** 元/升\n"
            f"- 🛢️ 0#柴油：**{latest['pDiesel']}** 元/升\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )
    else:
        gas_ton = abs(latest["gas"])
        diesel_ton = abs(latest["diesel"])
        wechat_content = (
            f"📅 {date_str} · 第{latest['round']}轮\n"
            f"{type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n\n"
            f"⛽ 92#：{prev['p92']} → {latest['p92']} 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"⛽ 95#：{prev['p95']} → {latest['p95']} 元/升（{arrow(delta_95)} {sign(delta_95)}{delta_95}）\n"
            f"🛢️ 0#柴油：{prev['pDiesel']} → {latest['pDiesel']} 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）\n\n"
            f"🔗 [查看详情]({PAGE_URL})"
        )
        dingtalk_title = title
        dingtalk_text = (
            f"## 🛢️ 油价{type_str}\n\n"
            f"**{date_str} · 第{latest['round']}轮**\n\n"
            f"{type_str} {gas_ton}元/吨（汽油）/ {diesel_ton}元/吨（柴油）\n\n"
            f"- ⛽ 92#：~~{prev['p92']}~~ → **{latest['p92']}** 元/升（{arrow(delta_92)} {sign(delta_92)}{delta_92}）\n"
            f"- ⛽ 95#：~~{prev['p95']}~~ → **{latest['p95']}** 元/升（{arrow(delta_95)} {sign(delta_95)}{delta_95}）\n"
            f"- 🛢️ 0#柴油：~~{prev['pDiesel']}~~ → **{latest['pDiesel']}** 元/升（{arrow(delta_diesel)} {sign(delta_diesel)}{delta_diesel}）\n\n"
            f"[📊 查看详情]({PAGE_URL})"
        )

    return title, wechat_content, dingtalk_title, dingtalk_text


# ============ 主流程 ============

def main():
    data = load_data()
    prices = data.get("prices2026") or data.get("prices", [])
    if len(prices) < 2:
        print("⚠️ 数据不足，跳过通知")
        return

    title, wechat_content, dt_title, dt_text = build_messages(prices)

    # 1) 微信（Server酱）
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "")
    if sendkey:
        print(f"📤 [微信] {title}")
        send_serverchan(sendkey, title, wechat_content)
    else:
        print("⏭️ 未配置 SERVERCHAN_SENDKEY，跳过微信通知")

    # 2) 钉钉
    dingtalk_webhook = os.environ.get("DINGTALK_WEBHOOK", "")
    if dingtalk_webhook:
        print(f"📤 [钉钉] {dt_title}")
        send_dingtalk(dingtalk_webhook, dt_title, dt_text)
    else:
        print("⏭️ 未配置 DINGTALK_WEBHOOK，跳过钉钉通知")


if __name__ == "__main__":
    main()
