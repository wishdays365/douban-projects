from crawler import DoubanTop250Spider
from analyzer import generate_beautiful_movie_table
from visualizer_utils import DoubanTop250Visualizer, generate_visual_menu
from app import start_flask_server
from csv_to_json import csv_to_json

import os
import sys
import asyncio
import json
import webbrowser  # 新增：用于自动打开浏览器
import threading  # 新增：用于异步启动Flask服务（避免阻塞）
import time       # 新增：用于延迟打开浏览器（等待服务启动）

# ========== 全局路径配置 ==========
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(ROOT_DIR, "douban_top250.csv")
JSON_FILE = os.path.join(ROOT_DIR, "douban_top250.json")
EXCEL_FILE = os.path.join(ROOT_DIR, "豆瓣Top250电影数据_美化版.xlsx")
WEB_HOST = "127.0.0.1"
WEB_PORT = 5000
WEB_URL = f"http://{WEB_HOST}:{WEB_PORT}"

# ========== Windows异步政策适配 ==========
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ========== 工具函数 ==========
def check_file_exists(file_path, file_type="数据"):
    """检查文件是否存在且非空"""
    if not os.path.exists(file_path):
        print(f"❌ 未找到{file_type}文件：{file_path}")
        return False
    if os.path.getsize(file_path) == 0:
        print(f"❌ {file_type}文件为空！")
        return False
    return True

def load_json_stats():
    """加载JSON数据并展示核心统计（适配新analyzer）"""
    if not check_file_exists(JSON_FILE):
        return
    from analyzer import MovieAnalyzer
    analyzer = MovieAnalyzer(JSON_FILE)
    stats = analyzer.rating_year_analysis()
    genre_top = list(analyzer.genre_analysis().keys())[:3]
    country_top = list(analyzer.country_analysis().keys())[:3]

    print("\n" + "=" * 60)
    print("📋 豆瓣Top250电影核心统计（基于JSON）")
    print("=" * 60)
    print(f"🎯 评分：平均分 {stats['rating_avg']} | 最高分 {stats['rating_max']} | 最低分 {stats['rating_min']}")
    print(f"📅 年份：最早 {stats['year_min']} | 最晚 {stats['year_max']} | 平均 {int(stats['year_avg'])}")
    print(f"🎬 热门类型：{', '.join(genre_top)}")
    print(f"🌍 热门地区：{', '.join(country_top)}")
    print("=" * 60)

def start_flask_in_thread():
    """在子线程中启动Flask服务（避免阻塞主线程）"""
    try:
        start_flask_server(host=WEB_HOST, port=WEB_PORT, debug=False)
    except Exception as e:
        print(f"\n❌ Flask服务启动异常：{str(e)}")

def auto_start_web_service():
    """自动启动Web服务并打开浏览器"""
    # Windows编码适配（避免中文乱码）
    if sys.platform == "win32":
        os.system("chcp 65001 > nul")

    print("\n" + "🎬 豆瓣Top250电影数据分析系统 v2.0 🎬")
    print("=" * 60)
    print("✨ 自动启动Web可视化服务...")
    print("=" * 60)

    # 检查JSON文件（非强制，提示即可）
    if not check_file_exists(JSON_FILE):
        print("ℹ️  提示：未检测到JSON数据文件，可通过Web页面「数据爬取」功能生成")
    
    # 1. 启动Flask服务（子线程）
    print(f"\n🚀 启动Flask Web服务...")
    print(f"🔗 Web服务地址：{WEB_URL}")
    print(f"⚠️  关闭服务请按 Ctrl+C")
    flask_thread = threading.Thread(target=start_flask_in_thread, daemon=True)
    flask_thread.start()

    # 2. 延迟1秒打开浏览器（等待服务启动）
    time.sleep(1)
    print(f"\n🌐 正在打开浏览器访问 {WEB_URL}...")
    try:
        webbrowser.open(WEB_URL, new=2)  # new=2：在新标签页打开
    except Exception as e:
        print(f"⚠️  自动打开浏览器失败，请手动访问：{WEB_URL}")
        print(f"   错误原因：{str(e)}")

    # 3. 主线程保持运行（等待用户中断）
    try:
        while flask_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 用户中断操作，Web服务即将停止...")
        sys.exit(0)

# ========== 原交互菜单（保留，可选注释） ==========
def main():
    # Windows编码适配（避免中文乱码）
    if sys.platform == "win32":
        os.system("chcp 65001 > nul")

    print("\n" + "🎬 豆瓣Top250电影数据分析系统 v2.0 🎬")
    print("=" * 60)
    print("✨ 新增Web端爬取/检索功能 | 支持多维度可视化")
    print("=" * 60)

    while True:
        print("\n===== 功能菜单 =====")
        print("1. 爬取数据（生成CSV+JSON）")
        print("2. 生成美化版Excel")
        print("3. 生成可视化图表（本地）")
        print("4. 查看数据统计")
        print("5. 启动Web可视化服务（支持Web爬取/检索）")
        print("6. 退出")
        choice = input("请选择操作（1-6）：").strip()

        # 1. 爬取数据
        if choice == "1":
            try:
                pages = int(input("请输入爬取页数（1-10，默认10）：") or 10)
                pages = max(1, min(10, pages))
            except ValueError:
                pages = 10

            print("🚀 启动豆瓣Top250爬虫...（约1-2分钟，请勿中断）")
            try:
                spider = DoubanTop250Spider(pages=pages)
                data = asyncio.run(spider.run())

                if data:
                    spider.save_to_csv(CSV_FILE)
                    csv_to_json(CSV_FILE, JSON_FILE)
                    print(f"✅ 爬取成功！")
                    print(f"📄 CSV文件：{CSV_FILE}")
                    print(f"📄 JSON文件：{JSON_FILE}")
                    load_json_stats()  # 爬取后自动展示统计
                else:
                    print("❌ 爬取失败：未获取到任何数据")
            except Exception as e:
                print(f"❌ 爬取异常：{str(e)}")

        # 2. 生成Excel
        elif choice == "2":
            if check_file_exists(JSON_FILE):
                print("📊 生成美化版Excel表格...")
                generate_beautiful_movie_table(JSON_FILE, EXCEL_FILE)
                print(f"✅ Excel已生成：{EXCEL_FILE}")
            else:
                print("❌ 请先爬取数据生成JSON！")

        # 3. 本地可视化
        elif choice == "3":
            if check_file_exists(JSON_FILE):
                print("📈 启动本地可视化菜单...")
                visualizer = DoubanTop250Visualizer(JSON_FILE)
                generate_visual_menu(visualizer)
            else:
                print("❌ 请先爬取数据生成JSON！")

        # 4. 查看统计
        elif choice == "4":
            print("📋 加载数据统计...")
            load_json_stats()

        # 5. 启动Web服务
        elif choice == "5":
            # 不再强制校验JSON（Web端可爬取）
            if not check_file_exists(JSON_FILE):
                print("ℹ️  提示：未检测到JSON文件，可通过Web页面「数据爬取」功能生成")
            print("\n🌐 启动Web可视化服务...")
            print("🔗 访问地址：http://127.0.0.1:5000")
            print("⚠️  关闭服务请按 Ctrl+C")
            try:
                start_flask_server(host="127.0.0.1", port=5000, debug=False)
            except KeyboardInterrupt:
                print("\n🛑 Web服务已停止")
            except Exception as e:
                print(f"❌ Web服务启动失败：{str(e)}")

        # 6. 退出
        elif choice == "6":
            print("\n👋 程序已退出，感谢使用！")
            print("📌 数据文件保留在当前目录，可再次运行查看")
            break

        # 无效输入
        else:
            print("❌ 无效输入，请选择1-6！")

if __name__ == "__main__":
    try:
        # ========== 核心修改：自动启动Web服务 ==========
        auto_start_web_service()
        
        # 如果需要保留原交互菜单，注释上面一行，取消下面一行注释
        # main()
    except KeyboardInterrupt:
        print("\n\n🛑 程序被用户中断")
    except Exception as e:
        print(f"\n❌ 程序异常退出：{str(e)}")
        input("按回车键退出...")