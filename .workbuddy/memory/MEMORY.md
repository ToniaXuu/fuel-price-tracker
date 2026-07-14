# fuel-price-tracker 项目约定

## 架构
- 纯静态页面，数据驱动，无需服务器/数据库
- `data.json` 为唯一数据源，`index.html` 通过 fetch 加载
- GitHub Actions 每日定时爬取并自动更新 data.json

## 数据结构 (data.json)
- `meta`: year, lastUpdated, city, province, basePrice92
- `prices[]`: round, date(YYYY-MM-DD), type(up/down/flat), gas, diesel, p92, p95, p98, pDiesel

## 油价换算公式 (NDRC 标准)
- 92#: 1吨 ≈ 1250升
- 95#: 92#变动 × 1.073
- 98#: 92#变动 × 1.12
- 0#柴油: 1吨 ≈ 1240升

## 数据源优先级
1. 商务部 oilsyggs.mofcom.gov.cn（官方）
2. 东方财富 data.eastmoney.com
3. 团友网 tuanyou.net

## 部署方式
- GitHub Pages 托管 index.html + data.json
- GitHub Actions 自动维护数据
