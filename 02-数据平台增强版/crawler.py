import os # 确保导入os
import asyncio
import aiohttp
import time
import random
import re
import csv
import json
import threading
from datetime import datetime
from bs4 import BeautifulSoup
from typing import Dict, Optional, List, Set
from pathlib import Path
from log_config import setup_logging
from expiry_manager import DataExpiryManager

logger = setup_logging()
# ======================== 配置项 ========================
COOKIE = "bid=IamaKRx9F_A; _pk_id.100001.4cf6=5c9263dc29c12f1c.1766069025.; ll=\"118160\"; _vwo_uuid_v2=D3CA72B06A7DE56B4BFDC743F9B847394|794858f488561d8d440a4d2d08319421; __yadk_uid=Gw6ZEqeAHawbBfPv7TkkRSbXaUDllvBU; dbcl2=\"292764584:wUCKwK5sg1s\"; push_noty_num=0; push_doumail_num=0; __utmc=30149280; __utmc=223695111; ck=JUPN; frodotk_db=\"6292dfdab509ac6527b89f901f1d052f\"; _pk_ref.100001.4cf6=%5B%22%22%2C%22%22%2C1766168766%2C%22https%3A%2F%2Faccounts.douban.com%2F%22%5D; _pk_ses.100001.4cf6=1; __utma=30149280.2108960386.1766069025.1766160822.1766168766.10; __utmz=30149280.1766168766.10.5.utmcsr=accounts.douban.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmt_douban=1; __utmb=30149280.1.10.1766168766; __utma=223695111.205708186.1766069028.1766160822.1766168766.10; __utmb=223695111.0.10.1766168766; __utmz=223695111.1766168766.10.5.utmcsr=accounts.douban.com|utmccn=(referral)|utmcmd=referral|utmcct=/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.douban.com/",
    "Cookie": COOKIE,
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive"
}

# 核心配置
BASE_URL = "https://movie.douban.com/top250"
BATCH_SIZE = 10  # 每次爬取10个
TARGET_TOTAL = 250  # 目标总数250
CHECK_INTERVAL = 300  # 定时爬取间隔（秒）
RETRY_TIMES = 3  # 单链接重试次数
LIST_PAGE_DELAY = (2.0, 3.0)
DETAIL_PAGE_DELAY = (3.0, 4.0)
ANTI_CRAWL_DELAY = 1800  # 遇到警告后等待时间（30分钟）
STATUS_FILE = "crawl_status.json"  # 状态保存文件
DATA_FILE = "douban_data_v2.json"  # 最终数据文件

# 从 `config.toml` 加载配置（支持 tomllib 或第三方 toml 包）
try:
    import tomllib as _toml_module
except Exception:
    try:
        import toml as _toml_module
    except Exception:
        _toml_module = None

def _load_config_from_toml(path: str = "config.toml") -> dict:
    config = {}
    cfg_path = Path(path)
    if not cfg_path.exists():
        logger.info(f"配置文件 {path} 未找到，使用代码内默认值")
        return config

    if _toml_module is None:
        logger.warning("未安装 tomllib/toml，无法从 config.toml 加载配置，使用默认值")
        return config

    try:
        with open(cfg_path, "rb") as f:
            # tomllib (py3.11+) 提供 load，第三方 toml 也提供 load/loads
            if hasattr(_toml_module, "load"):
                try:
                    config = _toml_module.load(f)
                except Exception:
                    f.seek(0)
                    config = _toml_module.loads(f.read().decode())
            else:
                content = f.read().decode()
                config = _toml_module.loads(content)
    except Exception as e:
        logger.warning(f"读取 config.toml 失败：{e}，使用默认值")

    return config

# 覆盖默认常量（如果 config.toml 提供了 crawler 部分）
_config_data = _load_config_from_toml()
_crawler_cfg = _config_data.get("crawler", {}) if isinstance(_config_data, dict) else {}

try:
    BATCH_SIZE = int(_crawler_cfg.get("batch_size", BATCH_SIZE))
except Exception:
    pass
try:
    TARGET_TOTAL = int(_crawler_cfg.get("target_total", TARGET_TOTAL))
except Exception:
    pass
try:
    CHECK_INTERVAL = int(_crawler_cfg.get("check_interval", CHECK_INTERVAL))
except Exception:
    pass
try:
    RETRY_TIMES = int(_crawler_cfg.get("retry_times", RETRY_TIMES))
except Exception:
    pass

_list_delay = _crawler_cfg.get("list_page_delay", LIST_PAGE_DELAY)
_detail_delay = _crawler_cfg.get("detail_page_delay", DETAIL_PAGE_DELAY)
try:
    if isinstance(_list_delay, (list, tuple)) and len(_list_delay) >= 2:
        LIST_PAGE_DELAY = (float(_list_delay[0]), float(_list_delay[1]))
    if isinstance(_detail_delay, (list, tuple)) and len(_detail_delay) >= 2:
        DETAIL_PAGE_DELAY = (float(_detail_delay[0]), float(_detail_delay[1]))
except Exception:
    pass

try:
    ANTI_CRAWL_DELAY = int(_crawler_cfg.get("anti_crawl_delay", ANTI_CRAWL_DELAY))
except Exception:
    pass

STATUS_FILE = _crawler_cfg.get("status_file", STATUS_FILE)
DATA_FILE = _crawler_cfg.get("data_file", DATA_FILE)


# ======================== 爬虫核心类（兼容pages参数） ========================
class DoubanTop250Spider:
    def __init__(self, pages: int = 10):
        """
        初始化爬虫（兼容pages参数）
        :param pages: 爬取页数（1-10，默认10页/250条）
        """
        self.expiry_manager = DataExpiryManager()
        self.pages = max(1, min(10, pages))  # 限制页数范围1-10
        self.max_total = self.pages * 25  # 计算最大爬取数量（每页25条）
        self.movie_data: List[Dict] = []
        self.semaphore = asyncio.Semaphore(3)  # 低并发减少反爬
        self.status = {
            "crawled_urls": set(),       # 已爬取的URL
            "unknown_urls": set(),       # 有未知字段的URL
            "pending_urls": [],          # 待爬取的URL
            "current_position": 0,       # 当前停止位置（分页start值）
            "total_success": 0,          # 成功爬取总数
            "last_crawl_time": None,     # 最后爬取时间
            "anti_crawl_warning": False  # 是否触发反爬警告
        }
        self._load_status()  # 加载历史状态
        self._init_pending_urls()  # 初始化待爬URL

    # ======================== 状态管理（断点续爬核心） ========================
    def _load_status(self):
        """加载爬取状态，实现断点续爬"""
        # 一致性检查：如果数据文件不存在或为空，强制重置状态
        if not Path(DATA_FILE).exists() or Path(DATA_FILE).stat().st_size < 10:
            logger.warning("数据文件丢失或损坏，强制重置爬取状态")
            self._reset_status()
            return

        if Path(STATUS_FILE).exists():
            try:
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    status = json.load(f)
                    
                    # 关键修复：如果历史状态显示已完成目标，则重置状态以允许重新爬取
                    # 只有当被调用时（意味着需要爬取），且状态显示已完成，才重置。
                    if status.get("total_success", 0) >= self.max_total:
                        logger.info("检测到上次爬取已完成全部目标，重置状态以开始新一轮爬取")
                        self._reset_status()
                        return

                    self.status["crawled_urls"] = set(status.get("crawled_urls", []))
                    self.status["unknown_urls"] = set(status.get("unknown_urls", []))
                    self.status["pending_urls"] = status.get("pending_urls", [])
                    self.status["current_position"] = status.get("current_position", 0)
                    self.status["total_success"] = status.get("total_success", 0)
                    self.status["last_crawl_time"] = status.get("last_crawl_time")
                    self.status["anti_crawl_warning"] = status.get("anti_crawl_warning", False)
                logger.info(f"加载历史状态：已爬{self.status['total_success']}个，待爬{len(self.status['pending_urls'])}个")
            except Exception as e:
                logger.warning(f"加载状态失败，使用初始状态：{e}")
        else:
            logger.info("无历史状态，全新开始爬取")

    def _reset_status(self):
        """重置状态"""
        self.status = {
            "crawled_urls": set(),
            "unknown_urls": set(),
            "pending_urls": [],
            "current_position": 0,
            "total_success": 0,
            "last_crawl_time": None,
            "anti_crawl_warning": False
        }
        # 删除旧的状态文件
        if Path(STATUS_FILE).exists():
            try:
                os.remove(STATUS_FILE)
            except Exception:
                pass

    def _save_status(self):
        """保存爬取状态"""
        save_status = self.status.copy()
        # 集合转列表（JSON不支持集合）
        save_status["crawled_urls"] = list(save_status["crawled_urls"])
        save_status["unknown_urls"] = list(save_status["unknown_urls"])
        save_status["last_crawl_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(save_status, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存状态失败：{e}")

    def _init_pending_urls(self):
        """初始化待爬URL（根据pages参数限制页数）"""
        if not self.status["pending_urls"] and self.status["total_success"] < self.max_total:
            # 计算需要的分页：start从current_position开始，每次25，最多pages页
            max_start = (self.pages - 1) * 25  # 例如pages=10 → start=225
            for start in range(self.status["current_position"], max_start + 1, 25):
                self.status["pending_urls"].extend(self._get_page_urls(start))
            # 去重（避免重复URL）
            self.status["pending_urls"] = list(set(self.status["pending_urls"]) - self.status["crawled_urls"])
            logger.info(f"初始化待爬URL：{len(self.status['pending_urls'])}个（共{self.pages}页/{self.max_total}条）")

    def _get_page_urls(self, start: int) -> List[str]:
        """获取指定分页的电影URL（同步获取）"""
        import requests
        detail_urls = []
        try:
            response = requests.get(
                BASE_URL,
                headers=HEADERS,
                params={"start": start, "filter": ""},
                timeout=15
            )
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "lxml")
                items = soup.find_all("div", class_="item")
                for item in items:
                    a_tag = item.find("a")
                    if a_tag and "subject" in a_tag.get("href", ""):
                        url = a_tag.get("href")
                        if url not in self.status["crawled_urls"]:
                            detail_urls.append(url)
            elif response.status_code in [403, 429]:
                logger.warning(f"触发反爬警告（状态码{response.status_code}），暂停爬取")
                self.status["anti_crawl_warning"] = True
            return detail_urls
        except Exception as e:
            logger.warning(f"获取分页URL失败（start={start}）：{e}")
            return []

    # ======================== 数据提取逻辑（不变） ========================
    def _extract_director(self, soup: BeautifulSoup, page_text: str) -> str:
        director_tags = soup.find_all("a", rel="v:directedBy")
        if director_tags:
            return " / ".join([tag.get_text(strip=True) for tag in director_tags])
        
        info_div = soup.find("div", id="info")
        if info_div:
            info_text = info_div.get_text(separator="\n", strip=True)
            pattern = re.compile(r'导演\s*[:：]\s*(.*?)(?=\n|类型|编剧|主演|$)', re.S)
            match = pattern.search(info_text)
            if match:
                director = match.group(1).strip()
                director = re.sub(r'\s+|更多\.{2,}', '', director)
                director = re.split(r'[\/,，\s]+', director)
                return " / ".join([d for d in director if d]) if director else "未知"
        
        pattern = re.compile(r'导演\s*[:：]\s*(.*?)(?=\n|类型|编剧|主演|$)', re.S | re.M)
        match = pattern.search(page_text)
        if not match:
            return "未知"
        
        director = match.group(1).strip()
        director = re.sub(r'\s+|更多\.{2,}', '', director)
        director = re.split(r'[\/,，\s]+', director)
        return " / ".join([d for d in director if d]) if director else "未知"

    def _extract_writer(self, soup: BeautifulSoup, page_text: str) -> str:
        writer_tags = soup.find_all("a", rel="v:writtenBy")
        if writer_tags:
            return " / ".join([tag.get_text(strip=True) for tag in writer_tags])
        
        info_div = soup.find("div", id="info")
        if info_div:
            info_text = info_div.get_text(separator="\n", strip=True)
            pattern = re.compile(r'编剧\s*[:：]\s*(.*?)(?=\n|导演|类型|主演|$)', re.S)
            match = pattern.search(info_text)
            if match:
                writer = match.group(1).strip()
                writer = re.sub(r'\s+|更多\.{2,}', '', writer)
                writer = re.split(r'[\/,，\s]+', writer)
                return " / ".join([w for w in writer if w]) if writer else "未知"
        
        pattern = re.compile(r'编剧\s*[:：]\s*(.*?)(?=\n|导演|类型|主演|$)', re.S | re.M)
        match = pattern.search(page_text)
        if not match:
            return "未知"
        
        writer = match.group(1).strip()
        writer = re.sub(r'\s+|更多\.{2,}', '', writer)
        writer = re.split(r'[\/,，\s]+', writer)
        return " / ".join([w for w in writer if w]) if writer else "未知"

    def _extract_actors(self, soup: BeautifulSoup, page_text: str, limit: int = 5) -> str:
        actor_tags = soup.find_all("a", rel="v:starring")
        if actor_tags:
            return " / ".join([tag.get_text(strip=True) for tag in actor_tags[:limit]])
        
        info_div = soup.find("div", id="info")
        if info_div:
            info_text = info_div.get_text(separator="\n", strip=True)
            pattern = re.compile(r'主演\s*[:：]\s*(.*?)(?=\n|类型|编剧|导演|$)', re.S)
            match = pattern.search(info_text)
            if match:
                actors_text = match.group(1).strip()
                actors_text = re.sub(r'\s+|更多\.{2,}', '', actors_text)
                actors = re.split(r'[\/,，\s]+', actors_text)
                return " / ".join([a for a in actors if a][:limit]) if actors else "未知"
        
        pattern = re.compile(r'主演\s*[:：]\s*(.*?)(?=\n|类型|编剧|导演|$)', re.S | re.M)
        match = pattern.search(page_text)
        if not match:
            return "未知"
        
        actors_text = match.group(1).strip()
        actors_text = re.sub(r'\s+|更多\.{2,}', '', actors_text)
        actors = re.split(r'[\/,，\s]+', actors_text)
        return " / ".join([a for a in actors if a][:limit]) if actors else "未知"

    def _extract_title(self, soup: BeautifulSoup) -> str:
        title_tag = soup.find("span", property="v:itemreviewed")
        if not title_tag:
            return "未知"
        title = title_tag.get_text(strip=True).split(" ")[0].split("(")[0]
        return title if title else "未知"

    def _extract_genre(self, soup: BeautifulSoup) -> str:
        genre_tags = soup.find_all("span", property="v:genre")
        if not genre_tags:
            return "未知"
        return " / ".join([g.get_text(strip=True) for g in genre_tags])

    def _extract_country(self, page_text: str) -> str:
        pattern = re.compile(r'制片国家/地区\s*[:：]\s*(.*?)(?=\n|语言|类型|$)', re.S | re.M)
        match = pattern.search(page_text)
        if not match:
            return "未知"
        country = match.group(1).strip()
        return country if country else "未知"

    def _extract_language(self, page_text: str) -> str:
        pattern = re.compile(r'语言\s*[:：]\s*(.*?)(?=\n|制片国家/地区|类型|$)', re.S | re.M)
        match = pattern.search(page_text)
        if not match:
            return "未知"
        language = match.group(1).strip()
        return language if language else "未知"

    def _extract_year(self, soup: BeautifulSoup) -> int:
        year_tag = soup.find("span", class_="year")
        if not year_tag:
            return 0
        year_text = year_tag.get_text(strip=True).replace("(", "").replace(")", "")
        return int(year_text) if year_text.isdigit() else 0

    def _extract_duration(self, soup: BeautifulSoup) -> int:
        runtime_tag = soup.find("span", property="v:runtime")
        if not runtime_tag:
            return 0
        runtime_text = runtime_tag.get_text(strip=True)
        match = re.search(r"\d+", runtime_text)
        return int(match.group()) if match else 0

    def _extract_imdb(self, page_text: str) -> str:
        pattern = re.compile(r'IMDb\s*[:：]\s*(.*?)(?=\n|$)', re.S | re.M)
        match = pattern.search(page_text)
        if not match:
            return "未知"
        imdb = match.group(1).strip()
        return imdb if imdb else "未知"

    def _extract_rating(self, soup: BeautifulSoup) -> float:
        rating_tag = soup.find("strong", class_="ll rating_num")
        if not rating_tag:
            return 0.0
        rating_text = rating_tag.get_text(strip=True)
        return float(rating_text) if rating_text.replace(".", "").isdigit() else 0.0

    def _extract_votes(self, soup: BeautifulSoup) -> int:
        votes_tag = soup.find("span", property="v:votes")
        if not votes_tag:
            return 0
        votes_text = votes_tag.get_text(strip=True)
        return int(votes_text.replace(",", "")) if votes_text.replace(",", "").isdigit() else 0

    def _extract_rating_dist(self, soup: BeautifulSoup) -> str:
        dist_tags = soup.find_all("span", class_="rating_per")
        dist = ["0%"] * 5
        for i in range(min(len(dist_tags), 5)):
            dist[i] = dist_tags[i].get_text(strip=True)
        return f"5星:{dist[0]},4星:{dist[1]},3星:{dist[2]},2星:{dist[3]},1星:{dist[4]}"

    def _extract_intro(self, soup: BeautifulSoup) -> str:
        intro_tag = soup.find("span", property="v:summary")
        if not intro_tag:
            return "无简介"
        intro = intro_tag.get_text(strip=True).replace("\n", "").replace("  ", "")
        return intro[:200] + "..." if len(intro) > 200 else intro

    def _extract_awards(self, soup: BeautifulSoup) -> str:
        awards_tag = soup.find("div", class_="awards")
        if not awards_tag:
            return "无"
        awards = awards_tag.get_text(strip=True).replace("获奖情况", "").replace("\n", "")
        return awards[:100] + "..." if len(awards) > 100 else awards

    def _has_unknown_fields(self, movie: Dict) -> bool:
        """检查电影数据是否有未知字段"""
        unknown_fields = ["未知", "无简介", 0, 0.0]
        return any([
            movie["director"] in unknown_fields,
            movie["writer"] in unknown_fields,
            movie["actors"] in unknown_fields,
            movie["genre"] in unknown_fields,
            movie["country"] in unknown_fields,
            movie["language"] in unknown_fields,
            movie["imdb"] in unknown_fields
        ])

    # ======================== 异步爬取逻辑（适配pages限制） ========================
    async def _crawl_detail_batch(self, urls: List[str]) -> List[Dict]:
        """分批爬取详情页（每次10个）"""
        # 过滤未过期的URL
        urls_to_crawl = []
        for url in urls:
            if self.expiry_manager.is_expired(url):
                urls_to_crawl.append(url)
            else:
                logger.info(f"URL未过期，跳过：{url}")
                # 即使跳过，也视为成功处理，避免卡在进度上
                self.status["crawled_urls"].add(url)
                self.status["total_success"] += 1

        if not urls_to_crawl:
            return []

        batch_data = []
        async with aiohttp.ClientSession() as session:  # 每次批次新建session，爬完断开
            tasks = [self._crawl_detail_page(url, session) for url in urls_to_crawl]
            results = await asyncio.gather(*tasks)
        
        for movie in results:
            if movie and self.status["total_success"] < self.max_total:  # 限制最大数量
                batch_data.append(movie)
                self.status["crawled_urls"].add(movie["detail_url"])
                # 标记有未知字段的URL
                if self._has_unknown_fields(movie):
                    self.status["unknown_urls"].add(movie["detail_url"])
                else:
                    self.status["unknown_urls"].discard(movie["detail_url"])
                self.status["total_success"] += 1
        
        # 更新待爬URL（移除已爬取的）
        self.status["pending_urls"] = [u for u in self.status["pending_urls"] if u not in self.status["crawled_urls"]]
        # 更新当前位置（用于断点续爬）
        self.status["current_position"] = min(self.status["current_position"] + len(urls), self.max_total)
        # 保存状态
        self._save_status()
        return batch_data

    async def _crawl_detail_page(self, url: str, session: aiohttp.ClientSession) -> Optional[Dict]:
        """爬取单个详情页（带反爬检测）"""
        async with self.semaphore:
            for retry in range(RETRY_TIMES):
                try:
                    async with session.get(
                        url,
                        headers=HEADERS,
                        timeout=aiohttp.ClientTimeout(total=20),
                        allow_redirects=True
                    ) as response:
                        # 检测反爬警告
                        if response.status in [403, 429]:
                            logger.warning(f"触发反爬警告（URL：{url}，状态码：{response.status}）")
                            self.status["anti_crawl_warning"] = True
                            return None
                        elif response.status != 200:
                            logger.warning(f"URL：{url} 状态码{response.status}，重试{retry+1}/{RETRY_TIMES}")
                            await asyncio.sleep(random.uniform(5, 8))
                            continue

                        text = await response.text()
                        # 检测网页中的反爬提示
                        if "访问验证" in text or "您的访问频率过高" in text:
                            logger.warning(f"网页检测到反爬提示（URL：{url}）")
                            self.status["anti_crawl_warning"] = True
                            return None

                        soup = BeautifulSoup(text, "lxml")
                        page_text = soup.get_text(separator="\n", strip=True)

                        movie = {
                            "detail_url": url,
                            "title": self._extract_title(soup),
                            "director": self._extract_director(soup, page_text),
                            "writer": self._extract_writer(soup, page_text),
                            "actors": self._extract_actors(soup, page_text, limit=5),
                            "genre": self._extract_genre(soup),
                            "country": self._extract_country(page_text),
                            "language": self._extract_language(page_text),
                            "year": self._extract_year(soup),
                            "duration": self._extract_duration(soup),
                            "imdb": self._extract_imdb(page_text),
                            "rating": self._extract_rating(soup),
                            "votes": self._extract_votes(soup),
                            "rating_dist": self._extract_rating_dist(soup),
                            "intro": self._extract_intro(soup),
                            "awards": self._extract_awards(soup)
                        }

                        logger.info(f"解析完成：{movie['title']} | 导演：{movie['director']}")
                        await asyncio.sleep(random.uniform(*DETAIL_PAGE_DELAY))
                        return movie

                except aiohttp.ClientError as e:
                    logger.warning(f"URL：{url} 网络错误：{e}，重试{retry+1}/{RETRY_TIMES}")
                except Exception as e:
                    logger.warning(f"URL：{url} 解析错误：{e}，重试{retry+1}/{RETRY_TIMES}")
                
                await asyncio.sleep(random.uniform(3, 5))
            
            logger.error(f"URL：{url} 重试{RETRY_TIMES}次失败")
            return None

    async def crawl_batch(self) -> bool:
        """执行单次批次爬取（优先重试未知项，再爬新项）"""
        # 1. 检查是否触发反爬警告
        if self.status["anti_crawl_warning"]:
            logger.info(f"检测到反爬警告，等待{ANTI_CRAWL_DELAY/60}分钟后重试")
            await asyncio.sleep(ANTI_CRAWL_DELAY)
            self.status["anti_crawl_warning"] = False  # 重置警告状态
            self._save_status()

        # 2. 检查是否完成目标（适配pages参数的max_total）
        if self.status["total_success"] >= self.max_total:
            logger.info(f"已完成目标：爬取{self.status['total_success']}个（目标{self.max_total}个）")
            self.save_to_csv()
            return False

        # 3. 优先获取有未知字段的URL（重试）
        batch_urls = []
        if self.status["unknown_urls"]:
            batch_urls = list(self.status["unknown_urls"])[:BATCH_SIZE]
            logger.info(f"优先重试未知项：{len(batch_urls)}个")
        else:
            # 无未知项则取新的待爬URL
            batch_urls = self.status["pending_urls"][:BATCH_SIZE]
            logger.info(f"爬取新项：{len(batch_urls)}个（累计已爬{self.status['total_success']}）")

        if not batch_urls:
            logger.warning("无待爬URL，尝试刷新待爬列表")
            self._init_pending_urls()
            batch_urls = self.status["pending_urls"][:BATCH_SIZE]
            if not batch_urls:
                logger.info("无更多待爬URL，爬取结束")
                return False

        # 4. 执行批次爬取
        logger.info(f"开始批次爬取（{len(batch_urls)}个）- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        batch_data = await self._crawl_detail_batch(batch_urls)
        self.movie_data.extend(batch_data)

        # 5. 保存当前数据
        if batch_data:
            self.save_data(batch_data)
            # 更新过期时间
            for movie in batch_data:
                self.expiry_manager.update_expiry(movie["detail_url"])
        
        logger.info(f"批次完成：成功{len(batch_data)}个，累计{self.status['total_success']}个")
        return True

    # ======================== 兼容旧版run方法（适配本地/WEB调用） ========================
    async def run(self) -> list[Dict]:
        """兼容旧版的run方法（单次爬取指定页数，无定时）"""
        logger.info(f"启动豆瓣Top250爬虫（{self.pages}页/{self.max_total}条）...")
        start_time = time.time()
        
        # 循环爬取直到完成目标
        while await self.crawl_batch():
            await asyncio.sleep(random.uniform(*LIST_PAGE_DELAY))
        
        end_time = time.time()
        logger.info("爬虫任务完成！")
        logger.info(f"总耗时：{end_time - start_time:.2f}秒")
        logger.info(f"统计：成功解析{self.status['total_success']}部 | 目标{self.max_total}部")
        
        # 更新全局爬取状态（标记为完成，更新最后爬取时间）
        self.expiry_manager.update_global_status("completed")
        
        # 如果本次运行没有产生新数据（例如全部未过期），尝试从文件加载完整数据返回
        if not self.movie_data and Path(DATA_FILE).exists():
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        return self.movie_data
    def save_data(self, new_data: List[Dict]|None = None):
        """保存数据到JSON（支持增量更新）"""
        save_path = DATA_FILE
        
        # 读取已有数据
        all_data = {}
        if Path(save_path).exists():
            try:
                with open(save_path, "r", encoding="utf-8") as f:
                    existing_list = json.load(f)
                    for item in existing_list:
                        all_data[item["detail_url"]] = item
            except Exception as e:
                logger.warning(f"读取已有数据失败：{e}")
        
        # 合并新数据
        data_to_save = new_data if new_data else self.movie_data
        for movie in data_to_save:
            # 添加最后更新时间
            movie["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            all_data[movie["detail_url"]] = movie
        
        # 写入JSON
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(list(all_data.values()), f, ensure_ascii=False, indent=2)
            logger.info(f"数据已保存到：{save_path}（共{len(all_data)}条）")
        except Exception as e:
            logger.error(f"保存数据失败：{e}")

    def save_to_csv(self, file_path: str|None = None):
        """兼容旧版调用，实际调用save_data"""
        self.save_data()

# ======================== 定时任务（可选） ========================
def start_scheduled_crawl(pages: int = 10):
    """启动定时爬取线程（支持指定页数）"""
    spider = DoubanTop250Spider(pages=pages)

    async def scheduled_task():
        """定时执行爬取"""
        while True:
            continue_crawl = await spider.crawl_batch()
            if not continue_crawl:
                break
            # 批次间隔
            logger.info(f"等待{CHECK_INTERVAL/60}分钟后开始下一批次...")
            await asyncio.sleep(CHECK_INTERVAL)

    # 运行异步任务
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scheduled_task())