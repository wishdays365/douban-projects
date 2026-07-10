from crawler import DoubanTop250Spider
from analyzer import generate_beautiful_movie_table
from visualizer_utils import DoubanTop250Visualizer, generate_visual_menu
from app import start_flask_server
from expiry_manager import DataExpiryManager  # 新增

import os
import sys
import asyncio
import json
import webbrowser  
import threading  
import time       
from log_config import setup_logging
import toml

# ========== 全局配置 ==========
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(ROOT_DIR, "douban_data_v2.json")
EXCEL_FILE = os.path.join(ROOT_DIR, "豆瓣Top250电影数据_美化版.xlsx")

# 从 config.toml 加载配置
WEB_HOST = "127.0.0.1"
WEB_PORT = 7594
OPEN_BROWSER = True
try:
    cfg_path = os.path.join(ROOT_DIR, "config.toml")
    if os.path.exists(cfg_path):
        _cfg = toml.load(cfg_path)
        _server = _cfg.get("server", {})
        WEB_HOST = _server.get("host", WEB_HOST)
        WEB_PORT = int(_server.get("port", WEB_PORT))
        OPEN_BROWSER = bool(_server.get("open_browser", OPEN_BROWSER))
except Exception:
    pass

WEB_URL = f"http://{WEB_HOST}:{WEB_PORT}"

# 检测是否应该尝试打开浏览器（避免在无显示/服务器环境中打开）
def _can_open_browser() -> bool:
    """返回是否可以打开浏览器：
    - 遵循 `OPEN_BROWSER` 配置
    - 在 Linux 上若无 DISPLAY/WAYLAND_DISPLAY 或运行在 SSH/CI 环境则不打开
    - 可通过环境变量 `NO_BROWSER=1` 强制禁止打开
    """
    if not OPEN_BROWSER:
        return False
    # 强制禁止的环境变量
    if os.environ.get("NO_BROWSER") in ("1", "true", "True"):
        return False
    # 常见 CI 或远程 SSH 场景
    if os.environ.get("CI") or os.environ.get("SSH_CONNECTION"):
        return False
    # macOS/Windows 通常可以打开（视具体环境），Linux 需 DISPLAY 或 WAYLAND
    if sys.platform.startswith("linux"):
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            return True
        return False
    # 其他平台默认允许
    return True

# 初始化日志
logger = setup_logging(os.path.join(ROOT_DIR, "config.toml"))
# expiry_manager = DataExpiryManager() # 不再需要全局实例

# ========== Windows异步政策适配 ==========
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ========== 自动爬取核心逻辑 ==========
def auto_crawl_if_needed(pages=10, force=False):
    """自动检查并爬取过期数据"""
    expiry_mgr = DataExpiryManager(ROOT_DIR)
    
    # 如果不是强制爬取，且数据未过期，则跳过
    if not force and not expiry_mgr.is_data_expired():
        logger.info("数据仍在保质期内，无需重新爬取")
        return False

    if not expiry_mgr.acquire_crawl_lock():
        logger.info("已有爬取任务正在运行（锁文件存在），跳过本次自动爬取")
        return False

    try:
        logger.info(f"启动爬虫检查（{pages}页）...")
        spider = DoubanTop250Spider(pages=pages)
        asyncio.run(spider.run())
        logger.info("爬虫运行结束")
        return True
    except Exception as e:
        logger.error(f"爬取过程出错: {e}")
        return False
    finally:
        expiry_mgr.release_crawl_lock()

def background_crawl_monitor():
    """后台爬取监控线程（每30分钟检查一次）"""
    while True:
        try:
            auto_crawl_if_needed(10)
        except Exception as e:
            logger.exception(f"后台爬取监控异常：{e}")
        # 每30分钟检查一次
        time.sleep(1800)

# ========== 工具函数 ==========
def check_file_exists(file_path, file_type="数据"):
    """检查文件是否存在且非空"""
    if not os.path.exists(file_path):
        logger.warning(f"未找到{file_type}文件：{file_path}")
        return False
    if os.path.getsize(file_path) == 0:
        logger.warning(f"{file_type}文件为空！")
        return False
    return True

def load_json_stats():
    """加载JSON数据并展示核心统计"""
    if not check_file_exists(JSON_FILE):
        return
    from analyzer import MovieAnalyzer
    analyzer = MovieAnalyzer(JSON_FILE)
    stats = analyzer.rating_year_analysis()
    genre_top = list(analyzer.genre_analysis().keys())[:3]
    country_top = list(analyzer.country_analysis().keys())[:3]

    logger.info("\n" + "=" * 60)
    logger.info("豆瓣Top250电影核心统计（基于JSON）")
    logger.info("=" * 60)
    logger.info(f"评分：平均分 {stats['rating_avg']} | 最高分 {stats['rating_max']} | 最低分 {stats['rating_min']}")
    logger.info(f"年份：最早 {stats['year_min']} | 最晚 {stats['year_max']} | 平均 {int(stats['year_avg'])}")
    logger.info(f"热门类型：{', '.join(genre_top)}")
    logger.info(f"热门地区：{', '.join(country_top)}")
    logger.info("=" * 60)

def start_flask_in_thread():
    """在子线程中启动Flask服务"""
    try:
                start_flask_server(host=WEB_HOST, port=WEB_PORT, debug=False)
    except Exception as e:
        logger.exception(f"Flask服务启动异常：{str(e)}")

def auto_start_web_service():
    """自动启动Web服务并打开浏览器"""
    # Windows编码适配
    if sys.platform == "win32":
        os.system("chcp 65001 > nul")

    logger.info("\n" + "豆瓣Top250电影数据分析系统")
    logger.info("=" * 60)
    logger.info("自动启动Web可视化服务...")
    logger.info("=" * 60)

    # 启动Flask服务（子线程）
    logger.info(f"\n启动Flask Web服务...")
    logger.info(f"Web服务地址：{WEB_URL}")
    logger.info(f"关闭服务请按 Ctrl+C")
    flask_thread = threading.Thread(target=start_flask_in_thread, daemon=True)
    flask_thread.start()

    # 延迟1秒后尝试打开浏览器（如果环境允许）
    time.sleep(1)
    if _can_open_browser():
        logger.info(f"正在打开浏览器访问 {WEB_URL}...")
        try:
            webbrowser.open(WEB_URL, new=2)
        except Exception as e:
            logger.exception(f"自动打开浏览器失败，请手动访问：{WEB_URL} - {e}")
    else:
        logger.info(f"不尝试自动打开浏览器（OPEN_BROWSER={OPEN_BROWSER}，环境不适合显示）。请手动访问：{WEB_URL}")

    # 第一步：自动检查并爬取过期数据（异步执行，不阻塞浏览器打开）
    logger.info("检查数据保质期...")
    threading.Thread(target=auto_crawl_if_needed, args=(10,), daemon=True).start()
    
    # 启动后台爬取监控线程
    monitor_thread = threading.Thread(target=background_crawl_monitor, daemon=True)
    monitor_thread.start()
    logger.info("启动后台数据监控线程（每30分钟检查一次数据保质期）")

    # 检查JSON文件（非强制）
    if not check_file_exists(JSON_FILE):
        logger.info("提示：未检测到JSON数据文件，自动爬取任务正在处理...")

    # 主线程保持运行
    try:
        while flask_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n\n用户中断操作，Web服务即将停止...")
        sys.exit(0)

# ========== 原交互菜单（保留，可选） ==========
def main():
    # Windows编码适配
    if sys.platform == "win32":
        os.system("chcp 65001 > nul")

    logger.info("豆瓣Top250电影数据分析系统 v2.0")
    logger.info("=" * 60)
    logger.info("自动数据过期重爬 | 3小时保质期 | 无需手动触发")
    logger.info("=" * 60)

    # 启动时自动检查爬取
    logger.info("检查数据保质期...")
    auto_crawl_if_needed(10)

    while True:
        logger.info("===== 功能菜单 =====")
        logger.info("1. 强制重新爬取数据")
        logger.info("2. 生成美化版Excel")
        logger.info("3. 生成可视化图表（本地）")
        logger.info("4. 查看数据统计")
        logger.info("5. 启动Web可视化服务")
        logger.info("6. 退出")
        choice = input("请选择操作（1-6）：").strip()

        # 1. 强制重新爬取
        if choice == "1":
            try:
                pages = int(input("请输入爬取页数（1-10，默认10）：") or 10)
                pages = max(1, min(10, pages))
            except ValueError:
                pages = 10

            logger.info("强制启动豆瓣Top250爬虫...")
            try:
                auto_crawl_if_needed(pages, force=True)
                logger.info("爬取完成！")
                load_json_stats()
            except Exception as e:
                logger.exception(f"爬取异常：{str(e)}")

        # 2. 生成Excel
        elif choice == "2":
            if check_file_exists(JSON_FILE):
                logger.info("生成美化版Excel表格...")
                generate_beautiful_movie_table(JSON_FILE, EXCEL_FILE)
                logger.info(f"Excel已生成：{EXCEL_FILE}")
            else:
                logger.info("请先等待自动爬取完成！")

        # 3. 本地可视化
        elif choice == "3":
            if check_file_exists(JSON_FILE):
                logger.info("启动本地可视化菜单...")
                visualizer = DoubanTop250Visualizer(JSON_FILE)
                generate_visual_menu(visualizer)
            else:
                logger.info("请先等待自动爬取完成！")

        # 4. 查看统计
        elif choice == "4":
            logger.info("加载数据统计...")
            load_json_stats()

        # 5. 启动Web服务
        elif choice == "5":
            logger.info("启动Web可视化服务...")
            logger.info(f"访问地址：{WEB_URL}")
            logger.info("关闭服务请按 Ctrl+C")
            try:
                start_flask_server(host="127.0.0.1", port=7594, debug=False)
            except KeyboardInterrupt:
                logger.info("Web服务已停止")
            except Exception as e:
                logger.exception(f"Web服务启动失败：{str(e)}")

        # 6. 退出
        elif choice == "6":
            logger.info("程序已退出，感谢使用！")
            break

        # 无效输入
        else:
            logger.info("无效输入，请选择1-6！")

if __name__ == "__main__":
    try:
        # 自动启动Web服务（含自动爬取）
        auto_start_web_service()
        # 如果需要使用交互菜单，注释上面一行，取消下面一行注释
        # main()
    except KeyboardInterrupt:
        logger.info("\n程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常退出：{str(e)}")
        input("按回车键退出...")