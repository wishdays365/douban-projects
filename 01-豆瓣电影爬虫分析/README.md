# 01 · 豆瓣电影爬虫分析

**时间**：2025年12月（大一第一学期）  
**版本**：v1 基础版  
**功能**：爬取豆瓣电影 Top250 → 数据分析 → Flask Web 可视化

## 技术栈

- 爬虫：Requests + BeautifulSoup4
- 后端：Flask
- 前端：Jinja2 + ECharts
- 数据：CSV / JSON

## 模块

| 文件 | 功能 |
|------|------|
| `crawler.py` | 豆瓣 Top250 爬虫 |
| `analyzer.py` | 数据分析（演员合作/类型分布） |
| `app.py` | Flask Web 主应用 |
| `main.py` | 入口 |
| `csv_to_json.py` | 数据格式转换 |
| `visualizer_utils.py` | 可视化工具 |
| `table_utils.py` | 表格渲染 |
