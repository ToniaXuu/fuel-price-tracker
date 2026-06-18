# 国内成品油价格趋势 · 济南站

追踪国内成品油（92# / 95# / 98# 汽油 & 0# 柴油）价格调整记录，以济南为基准城市，深度分析油价变动对生活出行的影响。

数据来源：国家发展和改革委员会 / 山东省发展和改革委员会

---

## 架构

纯静态页面 + JSON 数据驱动 + GitHub Actions 自动更新，**不需要服务器和数据库**。

```
data.json  ←── GitHub Actions (每日自动爬取) ←── 商务部/东方财富/团友网
    │
    ▼
index.html (fetch → 动态渲染图表、表格、统计)
    │
    ▼
GitHub Pages (自动部署)
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `index.html` | 主页面，通过 `fetch('./data.json')` 加载数据动态渲染 |
| `data.json` | 油价调整数据（JSON），由 GitHub Actions 自动维护 |
| `scripts/update_prices.py` | 油价数据爬取脚本，支持多数据源 |
| `.github/workflows/update-prices.yml` | GitHub Actions 定时工作流 |

## 数据自动更新

- **频率**：每天北京时间 09:00 自动运行
- **数据源**：商务部官网 ＞ 东方财富 ＞ 团友网（自动降级）
- **逻辑**：检测到新调价 → 计算济南零售价 → 更新 `data.json` → 自动提交
- **手动触发**：在 GitHub Actions 页面手动运行 workflow

### 本地运行

```bash
# 安装依赖
pip install requests beautifulsoup4

# 查看将要更新的数据（不写入）
python scripts/update_prices.py --dry-run

# 执行更新
python scripts/update_prices.py
```

## 部署

推送到 GitHub 后，使用 GitHub Pages 部署 `index.html` + `data.json` 即可。
