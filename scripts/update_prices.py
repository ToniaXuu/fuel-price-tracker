#!/usr/bin/env python3
"""
成品油价格数据更新脚本
======================
从多个数据源获取国内成品油调价记录，自动更新 data.json。

数据来源（按优先级）:
  1. 商务部全国石油市场管理系统 (oilsyggs.mofcom.gov.cn)
  2. 东方财富数据中心 (data.eastmoney.com)
  3. 团友网油价频道 (tuanyou.net)

转换公式:
  92#汽油: 1吨 ≈ 1250升  (NDRC 标准换算)
  95#汽油: 92#变动 × 1.073
  98#汽油: 92#变动 × 1.12
  0#柴油: 按柴油吨价独立换算 (1吨 ≈ 1240升)

用法:
  python update_prices.py              # 自动检测并更新
  python update_prices.py --dry-run    # 仅检查，不写入
  python update_prices.py --force      # 强制全量刷新
"""

import json
import os
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

# Windows 控制台 UTF-8 编码兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ============ 配置 ============

# data.json 路径（相对于脚本目录或项目根目录）
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_FILE = PROJECT_ROOT / "data.json"

# NDRC 标准换算系数
CONVERSION = {
    "92": 1250,    # 92# 汽油：1吨 ≈ 1250升
    "95": 1170,    # 95# 汽油：1吨 ≈ 1170升
    "98": 1120,    # 98# 汽油：1吨 ≈ 1120升
    "diesel": 1240, # 0#柴油：1吨 ≈ 1240升
}

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 东方财富 API
EASTMONEY_API = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get"
    "?reportName=RPT_ECONOMY_OIL_ADJUST"
    "&columns=ALL"
    "&pageNumber=1"
    "&pageSize=30"
    "&sortColumns=ADJUST_DATE"
    "&sortTypes=-1"
    "&source=WEB"
    "&client=WEB"
)

# MOFCOM 列表页
MOFCOM_LIST_URL = "https://oilsyggs.mofcom.gov.cn/oil/gzdt/page{page}.html"


# ============ 工具函数 ============

def load_existing_data():
    """加载现有 data.json"""
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_data(data):
    """保存 data.json"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存: {DATA_FILE}")


def get_last_date(prices):
    """获取 prices 数组中最后一条记录的日期"""
    if not prices:
        return None
    return max(p["date"] for p in prices)


def format_date_short(date_str):
    """2026-01-06 → 1月6日"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.month}月{d.day}日"


def parse_chinese_date(text):
    """从中文文本解析日期，返回 YYYY-MM-DD"""
    # 匹配: 2026年6月18日 或 2026年06月18日
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


# ============ 数据源 1: MOFCOM 商务部 ============

def fetch_mofcom_adjustments(last_known_date):
    """
    从商务部网站获取调价记录。
    返回: [(date_str, gas_amount, diesel_amount), ...]
    """
    try:
        import requests
    except ImportError:
        print("⚠️ 需要安装 requests 库: pip install requests")
        return []

    adjustments = []
    for page in range(1, 4):  # 最多查3页
        url = MOFCOM_LIST_URL.format(page=page)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = "utf-8"
        except Exception as e:
            print(f"⚠️ MOFCOM 第{page}页请求失败: {e}")
            break

        # 提取所有公告链接和日期
        # 格式: <a href="...">2026年X月X日国内成品油价格...</a>
        entries = re.findall(
            r'href="(/oil/gzdt/\d+/\d+/\w+\.html)"[^>]*>([^<]*?(\d{4})年(\d{1,2})月(\d{1,2})日[^<]*)</a>',
            resp.text
        )

        for href, title, year, month, day in entries:
            date_str = f"{year}-{int(month):02d}-{int(day):02d}"

            # 跳过已存在的日期
            if last_known_date and date_str <= last_known_date:
                continue

            # 判断类型
            if "上调" in title or "涨" in title:
                adj_type = "up"
            elif "下调" in title or "降" in title or "下跌" in title:
                adj_type = "down"
            else:
                adj_type = "up"  # 默认，需从详情页确认

            # 获取详情页
            detail_url = f"https://oilsyggs.mofcom.gov.cn{href}"
            try:
                detail_resp = requests.get(detail_url, headers=HEADERS, timeout=15)
                detail_resp.encoding = "utf-8"
                gas_amt, diesel_amt = parse_mofcom_detail(detail_resp.text)
            except Exception:
                gas_amt, diesel_amt = None, None

            # 如果详情页解析失败，先记录基础信息
            if gas_amt is not None and diesel_amt is not None:
                print(f"  📅 {date_str}: 汽油 {gas_amt:+d}元/吨, 柴油 {diesel_amt:+d}元/吨 [{adj_type}]")
                adjustments.append((date_str, adj_type, gas_amt, diesel_amt))
            else:
                print(f"  ⚠️ {date_str}: 无法解析详情页 ({title})")

        # 如果本页没有新数据，停止翻页
        has_new = any(
            parse_chinese_date(title)
            for _, title, _, _, _ in re.findall(
                r'href="(/oil/gzdt/\d+/\d+/\w+\.html)"[^>]*>([^<]*)</a>',
                resp.text
            )
            if parse_chinese_date(title) and (not last_known_date or parse_chinese_date(title) > last_known_date)
        )
        if not has_new:
            break

    return adjustments


def parse_mofcom_detail(html):
    """
    解析 MOFCOM 详情页，提取调价金额。
    格式: "国内汽、柴油（标准品）价格每吨分别上调75元、70元"
          或 "国内汽、柴油价格每吨分别提高75元和70元"
    """
    # 模式1: "分别上调/下调 XXX元、YYY元"
    m = re.search(r"分别(上调|下调|提高|降低)\s*(\d+)\s*元\s*[、，,]\s*(\d+)\s*元", html)
    if m:
        direction = -1 if m.group(1) in ("下调", "降低") else 1
        gas = int(m.group(2)) * direction
        diesel = int(m.group(3)) * direction
        return gas, diesel

    # 模式2: "分别提高/降低 XXX元和YYY元"
    m = re.search(r"分别(提高|降低|上调|下调)\s*(\d+)\s*元\s*和\s*(\d+)\s*元", html)
    if m:
        direction = -1 if m.group(1) in ("下调", "降低") else 1
        gas = int(m.group(2)) * direction
        diesel = int(m.group(3)) * direction
        return gas, diesel

    # 模式3: "汽、柴油价格不作调整" → 搁浅
    if "不作调整" in html or "不调整" in html or "未调整" in html:
        return 0, 0

    # 模式4: "汽、柴油价格每吨分别...上调/下调"
    m = re.search(r"每吨.*?(上调|下调|提高|降低)\s*(\d+)\s*元", html)
    if m:
        direction = -1 if m.group(1) in ("下调", "降低") else 1
        amt = int(m.group(2)) * direction
        return amt, amt  # 汽柴油同幅度（近似）

    return None, None


# ============ 数据源 2: 东方财富 ============

def fetch_eastmoney_adjustments(last_known_date):
    """从东方财富 API 获取调价记录"""
    try:
        import requests
    except ImportError:
        return []

    try:
        resp = requests.get(EASTMONEY_API, headers=HEADERS, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"⚠️ 东方财富 API 请求失败: {e}")
        return []

    if not data.get("success") or not data.get("result"):
        # 尝试备用 API 参数
        alt_api = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get"
            "?reportName=RPT_ECONOMY_OIL"
            "&columns=ALL"
            "&pageNumber=1"
            "&pageSize=30"
            "&sortColumns=SEQ"
            "&sortTypes=-1"
            "&source=WEB"
            "&client=WEB"
        )
        try:
            resp2 = requests.get(alt_api, headers=HEADERS, timeout=15)
            data = resp2.json()
        except Exception:
            return []

    if not data.get("success") or not data.get("result"):
        return []

    adjustments = []
    records = data["result"].get("data", [])

    for rec in records:
        date_str = rec.get("ADJUST_DATE") or rec.get("REPORT_DATE") or ""
        date_str = date_str[:10]  # 取 YYYY-MM-DD

        if last_known_date and date_str <= last_known_date:
            continue

        gas_change = rec.get("GASOLINE_CHANGE") or rec.get("GAS_CHANGE") or 0
        diesel_change = rec.get("DIESEL_CHANGE") or 0

        # 尝试从其他字段推断
        if gas_change == 0 and diesel_change == 0:
            # 检查是否有其他格式的数据
            gas_price = rec.get("GASOLINE_PRICE") or rec.get("GAS_PRICE") or 0
            # 如果有价格但没有变动，可能是搁浅
            continue

        adj_type = "up" if gas_change > 0 else "down" if gas_change < 0 else "flat"

        print(f"  📅 {date_str}: 汽油 {gas_change:+d}元/吨, 柴油 {diesel_change:+d}元/吨 [{adj_type}]")
        adjustments.append((date_str, adj_type, int(gas_change), int(diesel_change)))

    return adjustments


# ============ 数据源 3: 团友网（备用） ============

def fetch_tuanyou_adjustments(last_known_date):
    """从团友网获取最新调价"""
    try:
        import requests
    except ImportError:
        return []

    adjustments = []
    url = "https://www.tuanyou.net/youjia/zuixin/"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"⚠️ 团友网请求失败: {e}")
        return []

    # 解析列表页: "2026年X月X日24时起国内成品油油价按机制下调0.42元/升"
    entries = re.findall(
        r'(\d{4})年(\d{1,2})月(\d{1,2})日24时起[^<]*?(上调|下调)[^<]*?(\d+)\s*元/吨[^<]*?(\d+)\s*元/吨',
        resp.text
    )

    for year, month, day, direction, gas_str, diesel_str in entries:
        date_str = f"{year}-{int(month):02d}-{int(day):02d}"
        if last_known_date and date_str <= last_known_date:
            continue

        gas_amt = int(gas_str) * (-1 if "下调" in direction else 1)
        diesel_amt = int(diesel_str) * (-1 if "下调" in direction else 1)
        adj_type = "down" if gas_amt < 0 else "up"

        print(f"  📅 {date_str}: 汽油 {gas_amt:+d}元/吨, 柴油 {diesel_amt:+d}元/吨 [{adj_type}]")
        adjustments.append((date_str, adj_type, gas_amt, diesel_amt))

    return adjustments


# ============ 核心逻辑：数据合并与计算 ============

def compute_per_liter_prices(prices, new_adj):
    """
    根据最新的元/吨调整额，计算新的元/升零售价。
    prices: 现有数据（用于取上一轮价格）
    new_adj: [(date_str, type, gas_ton, diesel_ton), ...]
    返回新的 price 条目列表
    """
    # 取最后一轮作为基准
    if prices:
        last = prices[-1]
        next_round = last["round"] + 1
        prev_p92 = last["p92"]
        prev_p95 = last["p95"]
        prev_p98 = last["p98"]
        prev_pDiesel = last["pDiesel"]
    else:
        next_round = 1
        prev_p92 = 6.67  # 默认济南基准价
        prev_p95 = 7.16
        prev_p98 = 8.16
        prev_pDiesel = 6.26

    new_entries = []

    for date_str, adj_type, gas_ton, diesel_ton in sorted(new_adj):
        # 计算每升变动
        delta_92 = round(gas_ton / CONVERSION["92"], 2)
        delta_95 = round(delta_92 * 1.073, 2)
        delta_98 = round(delta_92 * 1.12, 2)
        delta_diesel = round(diesel_ton / CONVERSION["diesel"], 2) if diesel_ton != 0 else 0

        new_p92 = round(prev_p92 + delta_92, 2)
        new_p95 = round(prev_p95 + delta_95, 2)
        new_p98 = round(prev_p98 + delta_98, 2)
        new_pDiesel = round(prev_pDiesel + delta_diesel, 2)

        entry = {
            "round": next_round,
            "date": date_str,
            "type": adj_type,
            "gas": gas_ton,
            "diesel": diesel_ton,
            "p92": new_p92,
            "p95": new_p95,
            "p98": new_p98,
            "pDiesel": new_pDiesel,
        }
        new_entries.append(entry)

        # 更新基准
        prev_p92 = new_p92
        prev_p95 = new_p95
        prev_p98 = new_p98
        prev_pDiesel = new_pDiesel
        next_round += 1

    return new_entries


def validate_entry(entry):
    """验证数据条目是否合理"""
    # 价格应在合理范围 (5-12元/升)
    for key in ["p92", "p95", "p98", "pDiesel"]:
        if not (4.0 <= entry[key] <= 15.0):
            return False, f"{key}={entry[key]} 超出合理范围"

    # 价格应该有价格梯度: p98 > p95 > p92
    if not (entry["p98"] >= entry["p95"] >= entry["p92"]):
        return False, "价格梯度异常: 98#≥95#≥92#"

    return True, "OK"


# ============ 主流程 ============

def main(dry_run=False, force=False):
    print("=" * 60)
    print("🛢️  成品油价格数据更新")
    print("=" * 60)

    # 加载现有数据
    existing = load_existing_data()
    if not existing:
        print("⚠️ 未找到 data.json，将创建新文件")
        existing = {
            "meta": {
                "year": datetime.now().year,
                "lastUpdated": datetime.now().strftime("%Y-%m-%d"),
                "city": "济南",
                "province": "山东",
                "basePrice92": 6.67,
                "dataSource": "国家发展和改革委员会 · 山东省发展和改革委员会"
            },
            "prices": []
        }

    prices = existing.get("prices", [])
    last_date = get_last_date(prices)
    print(f"📋 现有记录: {len(prices)} 条，最后日期: {last_date}")

    # 阶段1: 从多个数据源获取新调价记录
    print("\n🔍 阶段1: 获取最新调价记录...")
    all_new = []

    # 数据源1: MOFCOM（官方，最可靠）
    print("\n  [数据源1] 商务部·全国石油市场管理系统")
    mofcom_data = fetch_mofcom_adjustments(last_date if not force else None)
    all_new.extend(mofcom_data)

    # 数据源2: 东方财富（补充）
    if not mofcom_data:
        print("\n  [数据源2] 东方财富数据中心")
        em_data = fetch_eastmoney_adjustments(last_date if not force else None)
        all_new.extend(em_data)

    # 数据源3: 团友网（最后备用）
    if not all_new:
        print("\n  [数据源3] 团友网")
        ty_data = fetch_tuanyou_adjustments(last_date if not force else None)
        all_new.extend(ty_data)

    if not all_new:
        print("\n✅ 没有发现新的调价记录，数据已是最新。")
        return

    # 去重和排序
    seen = set()
    unique_new = []
    for item in all_new:
        date_str = item[0]
        if date_str not in seen:
            seen.add(date_str)
            unique_new.append(item)

    unique_new.sort(key=lambda x: x[0])  # 按日期排序

    print(f"\n📊 发现 {len(unique_new)} 条新记录")

    # 阶段2: 计算每升价格并生成新条目
    print("\n🔢 阶段2: 计算零售价格...")
    new_entries = compute_per_liter_prices(prices, unique_new)

    # 验证
    for entry in new_entries:
        valid, msg = validate_entry(entry)
        if not valid:
            print(f"  ⚠️ 数据验证失败: {entry['date']} - {msg}")
        else:
            print(f"  ✓ {entry['date']}: 92#={entry['p92']}, 95#={entry['p95']}, "
                  f"98#={entry['p98']}, 0#柴油={entry['pDiesel']}")

    if dry_run:
        print("\n🔍 [Dry Run] 不会写入文件。以上为将要添加的数据。")
        return

    # 阶段3: 更新 data.json
    print("\n💾 阶段3: 更新 data.json...")
    prices.extend(new_entries)
    existing["prices"] = prices
    existing["meta"]["lastUpdated"] = new_entries[-1]["date"]
    existing["meta"]["year"] = datetime.strptime(new_entries[-1]["date"], "%Y-%m-%d").year

    save_data(existing)

    print(f"\n🎉 更新完成! 新增 {len(new_entries)} 条记录，共 {len(prices)} 条。")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    main(dry_run=dry_run, force=force)
