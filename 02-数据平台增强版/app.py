from flask import Flask, render_template, jsonify, request
from flask import Response, stream_with_context
import json
import os
import asyncio
import sys
import threading
from datetime import datetime, timedelta
import random
from functools import lru_cache  # 缓存数据，避免重复加载JSON
import toml
from log_config import setup_logging
import webbrowser
from expiry_manager import DataExpiryManager

# ========== 解决Windows异步政策问题 ==========
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())



# ========== Flask初始化 ==========
app = Flask(
    __name__,
    template_folder="templates",  # Web页面模板目录
    static_folder="static"        # 静态资源（CSS/图片）目录
)
app.secret_key = "douban_top250_2025"  # 避免Flask会话警告

# ========== 全局路径配置 ==========
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_FILE = os.path.join(ROOT_DIR, "douban_data_v2.json")  # 爬取的JSON数据文件

# 初始化日志和保质期管理器
logger = setup_logging(os.path.join(ROOT_DIR, "config.toml"))
expiry_manager = DataExpiryManager(ROOT_DIR)

# 防止每次页面请求都并发触发爬取：使用调度器避免重复启动
auto_crawl_lock = threading.Lock()
_auto_crawl_scheduled = False

def schedule_auto_crawl(pages=10):
    """调度一次后台的自动爬取检查，确保同一时刻只有一个检查线程在运行。"""
    global _auto_crawl_scheduled
    with auto_crawl_lock:
        if _auto_crawl_scheduled:
            return
        _auto_crawl_scheduled = True

    def _runner():
        global _auto_crawl_scheduled
        try:
            auto_crawl_if_needed(pages)
        finally:
            with auto_crawl_lock:
                _auto_crawl_scheduled = False

    threading.Thread(target=_runner, daemon=True).start()


# 实时推送（SSE）支持：当数据状态发生变化时通知长连接客户端
status_change_cond = threading.Condition()

def notify_status_change():
    try:
        with status_change_cond:
            status_change_cond.notify_all()
    except Exception:
        pass


@app.route('/api/data-status-stream')
def data_status_stream():
    def event_stream():
        import json as _json
        last_sent = None
        while True:
            try:
                status = expiry_manager.get_data_status()
                payload = _json.dumps(status, ensure_ascii=False)
                if payload != last_sent:
                    yield f"data: {payload}\n\n"
                    last_sent = payload
                # 等待被通知或超时后再次检查
                with status_change_cond:
                    status_change_cond.wait(timeout=30)
            except GeneratorExit:
                break
            except Exception:
                # 在出错时短暂休眠后重试，避免断流
                import time as _time
                _time.sleep(1)
        
    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')


# 检测是否可以打开浏览器（避免在无显示的服务器上打开）
def _can_open_browser() -> bool:
    # 环境变量强制禁止
    if os.environ.get("NO_BROWSER") in ("1", "true", "True"):
        return False
    # 常见 CI 或远程 SSH 场景
    if os.environ.get("CI") or os.environ.get("SSH_CONNECTION"):
        return False
    # Linux 需 DISPLAY 或 WAYLAND
    if sys.platform.startswith("linux"):
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            return True
        return False
    # 其他平台默认允许
    return True

# ========== 全局变量（声明visualizer为全局变量，方便重建） ==========
visualizer = None

# ========== 核心工具函数（修复缓存+实例重建） ==========
@lru_cache(maxsize=1)  # 缓存1个版本，爬取后强制清除
def load_movie_json():
    """加载JSON数据（增强日志+强制读取最新内容）"""
    try:
        if not os.path.exists(JSON_FILE):
            logger.warning(f"JSON文件不存在：{JSON_FILE}")
            return []
        
        # 强制读取最新内容（避免系统文件缓存）
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            movies = json.load(f)
        
        # 基础数据校验
        if not isinstance(movies, list):
            logger.error("JSON格式错误：不是数组")
            return []
        
        # 预处理数据（适配检索/排行功能）
        processed_movies = []
        for movie in movies:
            processed = movie.copy()
            
            # 统一处理数组字段（兼容字符串格式）
            for field in ["director", "actors", "genre", "country", "language"]:
                val = processed.get(field)
                if isinstance(val, str):
                    # 如果是字符串，按 / 分割转为列表
                    processed[field] = [x.strip() for x in val.split("/") if x.strip()]
                elif not isinstance(val, list):
                    processed[field] = []

            # 数组字段转字符串（方便检索匹配）
            processed["director_str"] = "|".join(processed.get("director", []))
            processed["actors_str"] = "|".join(processed.get("actors", []))
            processed["genre_str"] = "|".join(processed.get("genre", []))
            processed["country_str"] = "|".join(processed.get("country", []))
            processed["language_str"] = "|".join(processed.get("language", []))
            # 数值字段类型校准
            processed["rating"] = float(processed.get("rating", 0.0))
            processed["year"] = int(processed.get("year", 0))
            processed["votes"] = int(processed.get("votes", 0))  # 补充评价数校准（排行用）
            processed_movies.append(processed)
        
        logger.info(f"成功加载{len(processed_movies)}条电影数据（最新JSON）")
        return processed_movies
    except json.JSONDecodeError as e:
        logger.exception(f"JSON解析失败：{e}")
        return []
    except Exception as e:
        logger.exception(f"加载JSON失败：{e}")
        return []

def clear_json_cache():
    """彻底清除JSON缓存（确保加载最新数据）"""
    load_movie_json.cache_clear()
    logger.info("JSON缓存已彻底清除")

def rebuild_visualizer():
    """重建visualizer实例（爬取后基于最新JSON重新初始化）"""
    global visualizer
    try:
        from visualizer_utils import DoubanTop250Visualizer
        visualizer = DoubanTop250Visualizer(JSON_FILE) if os.path.exists(JSON_FILE) else None
        logger.info("visualizer分析实例已重建（基于最新JSON）")
    except ImportError as e:
        visualizer = None
        logger.exception(f"重建visualizer失败（模块导入）：{e}")
    except ValueError as e:
        visualizer = None
        logger.exception(f"重建visualizer失败（JSON无效）：{e}")
    except Exception as e:
        visualizer = None
        logger.exception(f"重建visualizer失败：{e}")

# ========== 自动爬取核心函数（新增） ==========
def auto_crawl_if_needed(pages=10):
    """自动检查并爬取过期数据"""
    # 检查是否需要爬取
    if not expiry_manager.is_data_expired():
        status = expiry_manager.get_data_status()
        logger.info(f"数据状态：{status['message']}")
        return True
    
    # 检查是否正在爬取
    if expiry_manager.is_crawl_running():
        logger.info("已有爬取任务正在运行，跳过本次自动爬取")
        return False
    
    # 获取爬取锁
    if not expiry_manager.acquire_crawl_lock():
        logger.warning("获取爬取锁失败，可能有其他爬取任务")
        return False
    
    try:
        # 更新爬取状态
        expiry_manager.update_crawl_status("running", pages)
        logger.info(f"开始自动爬取豆瓣Top250数据（{pages}页）...")
        
        # 执行爬虫
        success, msg = run_spider(pages)
        
        if success:
            expiry_manager.update_crawl_status("completed", pages)
            logger.info(f"自动爬取成功：{msg}")
            # 清除缓存并重建visualizer
            clear_json_cache()
            rebuild_visualizer()
            return True
        else:
            expiry_manager.update_crawl_status("error", pages)
            logger.error(f"自动爬取失败：{msg}")
            return False
    except Exception as e:
        expiry_manager.update_crawl_status("error", pages)
        logger.exception(f"自动爬取异常：{e}")
        return False
    finally:
        # 释放锁
        expiry_manager.release_crawl_lock()

# ========== 爬虫调用函数（保留，供自动爬取使用） ==========
def run_spider(pages=10):
    """执行爬虫并生成JSON数据"""
    try:
        # 动态导入爬虫模块（避免启动时依赖）
        from crawler import DoubanTop250Spider
        
        # 校验爬取页数（1-10页，豆瓣Top250共10页）
        pages = max(1, min(10, int(pages)))
        
        # 执行异步爬虫
        spider = DoubanTop250Spider(pages=pages)
        movie_data = asyncio.run(spider.run())
        
        if not movie_data:
            logger.warning("爬取失败：未获取到任何电影数据")
            return False, "爬取失败：未获取到任何电影数据"
        
        # 保存数据（crawler内部已处理保存到JSON）
        spider.save_data()
        
        # 清除缓存并重新加载数据
        clear_json_cache()
        load_movie_json()
        
        return True, f"爬取成功！共获取{len(movie_data)}条电影数据（已更新JSON）"
    except ImportError as e:
        logger.exception(f"爬虫模块导入失败：{e}")
        return False, f"爬虫模块导入失败：{str(e)}（请确认crawler.py存在）"
    except Exception as e:
        logger.exception(f"爬取异常：{e}")
        return False, f"爬取异常：{str(e)}"

# ========== 检索功能核心函数 ==========
def search_movies(keyword="", filter_type="all", min_rating=0, max_rating=10, min_year=0, max_year=9999):
    """多维度检索电影"""
    movies = load_movie_json()
    if not movies:
        return []
    
    # 统一关键词为小写（不区分大小写检索）
    keyword = keyword.lower().strip()
    results = []
    
    for movie in movies:
        # 评分过滤
        if not (min_rating <= movie["rating"] <= max_rating):
            continue
        # 年份过滤
        if not (min_year <= movie["year"] <= max_year):
            continue
        # 关键词检索（按维度匹配）
        match = False
        if filter_type == "all":
            # 全维度匹配：标题/导演/演员/类型/国家
            match_str = f"{movie['title'].lower()}|{movie['director_str'].lower()}|{movie['actors_str'].lower()}|{movie['genre_str'].lower()}|{movie['country_str'].lower()}"
            match = keyword in match_str
        elif filter_type == "title":
            match = keyword in movie["title"].lower()
        elif filter_type == "director":
            match = keyword in movie["director_str"].lower()
        elif filter_type == "actor":
            match = keyword in movie["actors_str"].lower()
        elif filter_type == "genre":
            match = keyword in movie["genre_str"].lower()
        elif filter_type == "country":
            match = keyword in movie["country_str"].lower()
        
        if match:
            # 移除预处理的字符串字段，返回原始结构
            movie_clean = {k: v for k, v in movie.items() if not k.endswith("_str")}
            results.append(movie_clean)
    
    # 按评分降序排序
    results.sort(key=lambda x: x["rating"], reverse=True)
    return results

# ========== 排行功能核心函数 ==========
def get_movie_ranking(dimension="rating", top_n=20):
    """
    获取电影排行
    :param dimension: 排行维度（rating=评分, votes=评价数, year=年份）
    :param top_n: 展示前N名
    :return: 排序后的电影列表
    """
    movies = load_movie_json()
    if not movies:
        return []
    
    # 过滤有效数据（排除评分/评价数/年份为空的电影）
    valid_movies = []
    for movie in movies:
        # 评分榜：需有有效评分
        if dimension == "rating" and movie.get("rating", 0) <= 0:
            continue
        # 热门榜：需有有效评价数
        elif dimension == "votes" and movie.get("votes", 0) <= 0:
            continue
        # 年份榜：需有有效年份（1900年后）
        elif dimension == "year" and movie.get("year", 0) < 1900:
            continue
        valid_movies.append(movie)
    
    # 按维度排序
    if dimension == "rating":
        # 评分降序，评分相同则评价数降序
        sorted_movies = sorted(valid_movies, key=lambda x: (-x["rating"], -x.get("votes", 0)))
    elif dimension == "votes":
        # 评价数降序
        sorted_movies = sorted(valid_movies, key=lambda x: -x["votes"])
    elif dimension == "year":
        # 年份降序，年份相同则评分降序
        sorted_movies = sorted(valid_movies, key=lambda x: (-x["year"], -x.get("rating", 0)))
    else:
        # 默认按评分排序
        sorted_movies = sorted(valid_movies, key=lambda x: (-x.get("rating", 0), -x.get("votes", 0)))
    
    # 截取前N名并清理预处理字段
    final_result = []
    for movie in sorted_movies[:min(top_n, len(sorted_movies))]:
        final_result.append({k: v for k, v in movie.items() if not k.endswith("_str")})
    
    return final_result

# ========== 初始化visualizer（启动时加载） ==========
try:
    from visualizer_utils import DoubanTop250Visualizer
    visualizer = DoubanTop250Visualizer(JSON_FILE) if os.path.exists(JSON_FILE) else None
    logger.info(f"启动时初始化visualizer：{'成功' if visualizer else '失败'}")
except ImportError as e:
    logger.exception(f"可视化模块导入失败：{e}")
    visualizer = None
except ValueError as e:
    logger.exception(f"可视化工具初始化失败：{e}")
    visualizer = None
except Exception as e:
    logger.exception(f"可视化工具初始化失败：{e}")
    visualizer = None

# ========== Web页面路由 ==========
@app.route("/")
def index():
    """首页：展示评分/年份统计"""
    # 异步触发自动爬取（不阻塞首页加载），使用调度器防止重复触发
    schedule_auto_crawl(10)
    
    stats = {}
    if visualizer:
        stats = visualizer.get_rating_year_stats()
    return render_template("index.html", stats=stats)

@app.route("/crawl")
def crawl_page():
    """数据状态页面：展示自动爬取状态（替代原爬取页面）"""
    return render_template("crawl.html")

@app.route("/search")
def search_page():
    """检索页面"""
    # 异步触发自动爬取（使用调度器）
    schedule_auto_crawl(10)
    
    # 传递检索参数到模板（支持回显）
    keyword = request.args.get("keyword", "")
    filter_type = request.args.get("filter_type", "all")
    min_rating = request.args.get("min_rating", "")
    max_rating = request.args.get("max_rating", "")
    min_year = request.args.get("min_year", "")
    max_year = request.args.get("max_year", "")
    # 执行检索并传递结果
    results = search_movies(keyword, filter_type, 
                           float(min_rating) if min_rating else 0,
                           float(max_rating) if max_rating else 10,
                           int(min_year) if min_year else 0,
                           int(max_year) if max_year else 9999)
    return render_template("search.html", 
                           keyword=keyword,
                           filter_type=filter_type,
                           min_rating=min_rating,
                           max_rating=max_rating,
                           min_year=min_year,
                           max_year=max_year,
                           results=results,
                           total=len(results))

@app.route("/genre-analysis")
def genre_analysis_page():
    """类型分布分析页面"""
    # 异步触发自动爬取（使用调度器）
    schedule_auto_crawl(10)
    
    try:
        return render_template("genre_analysis.html")
    except Exception as e:
        logger.exception(f"加载类型分析页面失败：{e}")
        return "页面加载失败：" + str(e), 500

@app.route("/actor-analysis")
def actor_analysis_page():
    """演员出镜统计页面"""
    # 异步触发自动爬取（使用调度器）
    schedule_auto_crawl(10)
    
    try:
        return render_template("actor_analysis.html")
    except Exception as e:
        logger.exception(f"加载演员统计页面失败：{e}")
        return "页面加载失败：" + str(e), 500

@app.route("/movie-map")
def movie_map_page():
    """国家/地区分布页面"""
    # 异步触发自动爬取（使用调度器）
    schedule_auto_crawl(10)
    
    try:
        return render_template("movie_map.html")
    except Exception as e:
        logger.exception(f"加载国家分布页面失败：{e}")
        return "页面加载失败：" + str(e), 500

@app.route("/rank")
def rank_page():
    """电影排行页面"""
    # 异步触发自动爬取（使用调度器）
    schedule_auto_crawl(10)
    
    try:
        # 获取前端参数（默认按评分排行，前20名）
        dimension = request.args.get("dimension", "rating")
        top_n = int(request.args.get("top_n", 20))
        # 限制top_n范围（1-50）
        top_n = max(1, min(50, top_n))
        # 获取排行数据
        ranking_movies = get_movie_ranking(dimension, top_n)
        # 传递参数到模板
        return render_template("rank.html",
                               dimension=dimension,
                               top_n=top_n,
                               ranking_movies=ranking_movies,
                               total=len(ranking_movies))
    except Exception as e:
        logger.exception(f"加载排行页面失败：{e}")
        return f"页面加载失败：{str(e)}", 500

# ========== API接口路由 ==========
@app.route("/api/data-status", methods=["GET"])
def api_data_status():
    """新增：获取数据状态API"""
    try:
        status = expiry_manager.get_data_status()
        return jsonify({
            "success": True,
            "data": status
        })
    except Exception as e:
        logger.exception(f"数据状态API异常：{e}")
        return jsonify({
            "success": False,
            "data": {
                "status": "error",
                "message": f"获取数据状态失败：{str(e)}",
                "expired": True
            }
        }), 500

@app.route("/api/movies")
def api_movies():
    """获取所有电影数据"""
    # 异步触发自动爬取（使用调度器）
    schedule_auto_crawl(10)
    
    try:
        return jsonify(load_movie_json())
    except Exception as e:
        logger.exception(f"API电影数据接口异常：{e}")
        return jsonify([]), 500

@app.route("/api/search", methods=["GET", "POST"])
def api_search():
    """检索API"""
    # 异步触发自动爬取（使用调度器）
    schedule_auto_crawl(10)
    
    try:
        # 获取参数（POST/GET兼容）
        if request.method == "POST":
            data = request.form
        else:
            data = request.args
        
        keyword = data.get("keyword", "")
        filter_type = data.get("filter_type", "all")
        min_rating = float(data.get("min_rating", 0))
        max_rating = float(data.get("max_rating", 10))
        min_year = int(data.get("min_year", 0))
        max_year = int(data.get("max_year", 9999))
        
        # 执行检索
        results = search_movies(keyword, filter_type, min_rating, max_rating, min_year, max_year)
        return jsonify({"total": len(results), "results": results, "params": data.to_dict()})
    except Exception as e:
        logger.exception(f"API检索接口异常：{e}")
        return jsonify({"total": 0, "results": [], "params": {}}), 500

@app.route("/api/genre-data")
def api_genre_data():
    """类型分布数据API"""
    # 异步触发自动爬取（使用调度器）
    schedule_auto_crawl(10)
    
    try:
        if not visualizer:
            return jsonify({"xAxis": [], "yAxis": []})
        data = visualizer.get_echarts_genre_data()
        # 校验返回格式
        if not isinstance(data, dict) or "xAxis" not in data or "yAxis" not in data:
            return jsonify({"xAxis": [], "yAxis": []})
        return jsonify(data)
    except Exception as e:
        logger.exception(f"API类型数据接口异常：{e}")
        return jsonify({"xAxis": [], "yAxis": []}), 500

@app.route("/api/actor-data")
def api_actor_data():
    """演员出镜数据API"""
    # 异步触发自动爬取
    threading.Thread(target=auto_crawl_if_needed, args=(10,), daemon=True).start()
    
    try:
        if not visualizer:
            return jsonify({"xAxis": [], "yAxis": []})
        data = visualizer.get_echarts_actor_data()
        if not isinstance(data, dict) or "xAxis" not in data or "yAxis" not in data:
            return jsonify({"xAxis": [], "yAxis": []})
        return jsonify(data)
    except Exception as e:
        logger.exception(f"API演员数据接口异常：{e}")
        return jsonify({"xAxis": [], "yAxis": []}), 500

@app.route("/api/country-data")
def api_country_data():
    """国家分布数据API（双重兜底）"""
    # 异步触发自动爬取
    schedule_auto_crawl(10)
    
    try:
        # 兜底方案1：使用visualizer（优先）
        if visualizer:
            data = visualizer.get_echarts_country_data()
            if isinstance(data, list) and len(data) > 0:
                return jsonify(data)
        
        # 兜底方案2：直接解析JSON文件（不依赖visualizer）
        movies = load_movie_json()
        if not movies:
            return jsonify([])
        
        # 国家名称映射（适配ECharts世界地图）
        country_mapping = {
            "中国": "China", "美国": "United States", "日本": "Japan", 
            "韩国": "South Korea", "英国": "United Kingdom", "法国": "France",
            "德国": "Germany", "意大利": "Italy", "西班牙": "Spain", "印度": "India"
        }
        
        # 统计国家数量
        from collections import Counter
        country_counter = Counter()
        for movie in movies:
            countries = movie.get("country", [])
            if isinstance(countries, str):
                countries = [c.strip() for c in countries.split("/") if c.strip()]
            if isinstance(countries, list):
                for c in countries:
                    c = c.strip()
                    country_counter[country_mapping.get(c, c)] += 1
        
        # 转换为ECharts格式
        result = [{"cn_name": name, "count": count} for name, count in country_counter.most_common(20)]
        return jsonify(result)
    except Exception as e:
        logger.exception(f"API国家数据接口异常：{e}")
        return jsonify([]), 500

@app.route("/api/stats")
def api_stats():
    """评分/年份统计API（双重兜底）"""
    # 异步触发自动爬取
    schedule_auto_crawl(10)
    
    try:
        # 优先使用visualizer
        if visualizer:
            stats = visualizer.get_rating_year_stats()
            if stats.get("rating_avg", 0) > 0:
                return jsonify(stats)
        
        # 兜底：直接计算最新JSON数据
        movies = load_movie_json()
        if not movies:
            return jsonify({"rating_avg": 0, "rating_max": 0, "rating_min": 0, "year_min": 0, "year_max": 0, "year_avg": 0})
        
        ratings = [m["rating"] for m in movies if m["rating"] > 0]
        years = [m["year"] for m in movies if m["year"] > 0]
        return jsonify({
            "rating_avg": round(sum(ratings)/len(ratings), 2) if ratings else 0,
            "rating_max": max(ratings) if ratings else 0,
            "rating_min": min(ratings) if ratings else 0,
            "year_min": min(years) if years else 0,
            "year_max": max(years) if years else 0,
            "year_avg": round(sum(years)/len(years), 0) if years else 0
        })
    except Exception as e:
        logger.exception(f"API统计接口异常：{e}")
        return jsonify({"rating_avg": 0, "rating_max": 0, "rating_min": 0, "year_min": 0, "year_max": 0, "year_avg": 0}), 500

@app.route("/api/rank")
def api_rank():
    """排行数据API"""
    # 异步触发自动爬取
    schedule_auto_crawl(10)
    
    try:
        dimension = request.args.get("dimension", "rating")
        top_n = int(request.args.get("top_n", 20))
        top_n = max(1, min(50, top_n))
        ranking_movies = get_movie_ranking(dimension, top_n)
        return jsonify({
            "dimension": dimension,
            "top_n": top_n,
            "total": len(ranking_movies),
            "results": ranking_movies
        })
    except Exception as e:
        logger.exception(f"API排行接口异常：{e}")
        return jsonify({
            "dimension": "rating",
            "top_n": 20,
            "total": 0,
            "results": []
        }), 500

# ========== 移除原手动爬取API（不再需要） ==========
# @app.route("/api/crawl", methods=["POST"])
# def api_crawl():
#     原手动爬取接口已移除

# ========== 全局异常处理器 ==========
@app.errorhandler(500)
def handle_500_error(e):
    """全局500错误处理"""
    logger.exception(f"全局500异常：{e}")
    return jsonify({
        "success": False,
        "message": "服务器内部错误，请查看日志或稍后重试",
        "error": str(e)
    }), 500

@app.errorhandler(404)
def handle_404_error(e):
    """全局404错误处理"""
    logger.warning(f"全局404异常：{e}")
    return jsonify({
        "success": False,
        "message": "请求的页面/接口不存在，请检查URL是否正确",
        "error": str(e)
    }), 404

# ========== 启动函数（新增自动爬取检查） ==========
def start_flask_server(host: str = None, port: int = None, debug: bool = False):
    """启动Flask Web服务"""
    # 若未传入 host/port，则尝试从 config.toml 读取（回退为默认）
    try:
        cfg_path = os.path.join(ROOT_DIR, "config.toml")
        cfg = toml.load(cfg_path) if os.path.exists(cfg_path) else {}
    except Exception:
        cfg = {}

    server_cfg = cfg.get("server", {})
    host = host or server_cfg.get("host", "127.0.0.1")
    port = int(port or server_cfg.get("port", 7594))
    # 启动前清除JSON缓存（避免旧数据干扰）
    clear_json_cache()

    # 启动前自动检查并爬取过期数据（异步）
    logger.info("启动前检查数据保质期...")
    threading.Thread(target=auto_crawl_if_needed, args=(10,), daemon=True).start()

    # 启动前校验JSON文件
    if not os.path.exists(JSON_FILE):
        logger.warning(f"警告：未找到JSON文件 {JSON_FILE}")
        logger.info("   系统将自动爬取豆瓣Top250数据，无需手动操作")

    # 打印完整访问路径（更新crawl为数据状态）
    logger.info(f"\nWeb服务已启动：http://{host}:{port}")
    logger.info("访问路径：")
    logger.info(f"   - 首页：http://{host}:{port}")
    logger.info(f"   - 数据状态：http://{host}:{port}/crawl")
    logger.info(f"   - 电影检索：http://{host}:{port}/search")
    logger.info(f"   - 电影排行：http://{host}:{port}/rank")
    logger.info(f"   - 类型分析：http://{host}:{port}/genre-analysis")
    logger.info(f"   - 演员统计：http://{host}:{port}/actor-analysis")
    logger.info(f"   - 国家分布：http://{host}:{port}/movie-map")

    # 启动服务（关闭reloader避免重复初始化）
    app.run(host=host, port=port, debug=debug, use_reloader=False)

# ========== 测试入口（修复语法错误） ==========
if __name__ == "__main__":
    start_flask_server(debug=True)