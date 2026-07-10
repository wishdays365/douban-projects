import asyncio
import aiohttp
import time
import random
import re
import csv
from bs4 import BeautifulSoup
from typing import Dict, Optional, List

# ========================
# 核心优化：强化请求头（集成你的有效Cookie）
# ========================
# 替换为你自己的Cookie（从浏览器复制，有效期约1-7天）
COOKIE = "bid=IamaKRx9F_A; _pk_id.100001.4cf6=5c9263dc29c12f1c.1766069025.; ll=\"118160\"; _vwo_uuid_v2=D3CA72B06A7DE56B4BFDC743F9B847394|794858f488561d8d440a4d2d08319421; __yadk_uid=Gw6ZEqeAHawbBfPv7TkkRSbXaUDllvBU; dbcl2=\"292764584:wUCKwK5sg1s\"; push_noty_num=0; push_doumail_num=0; __utmc=30149280; __utmc=223695111; ck=JUPN; frodotk_db=\"6292dfdab509ac6527b89f901f1d052f\"; _pk_ref.100001.4cf6=%5B%22%22%2C%22%22%2C1766168766%2C%22https%3A%2F%2Faccounts.douban.com%2F%22%5D; _pk_ses.100001.4cf6=1; __utma=30149280.2108960386.1766069025.1766160822.1766168766.10; __utmz=30149280.1766168766.10.5.utmcsr=accounts.douban.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmt_douban=1; __utmb=30149280.1.10.1766168766; __utma=223695111.205708186.1766069028.1766160822.1766168766.10; __utmb=223695111.0.10.1766168766; __utmz=223695111.1766168766.10.5.utmcsr=accounts.douban.com|utmccn=(referral)|utmcmd=referral|utmcct=/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.douban.com/",
    "Cookie": COOKIE,  # 关键：集成有效Cookie
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive"
}

# 反爬适配配置
BASE_URL = "https://movie.douban.com/top250"
MAX_CONCURRENT = 3  # 降低并发数，减少反爬风险
LIST_PAGE_DELAY = (1.5, 2.0)  # 增加列表页延时
DETAIL_PAGE_DELAY = (2.0, 3.0)  # 增加详情页延时
RETRY_TIMES = 2  # 请求失败重试次数

class DoubanTop250Spider:
    """抗反爬版异步爬虫（集成Cookie+重试机制）"""
    def __init__(self, pages: int = 10):
        self.pages = max(1, min(10, pages))
        self.movie_data = []
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # ========================
    # 核心提取逻辑（不变）
    # ========================
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

    # ========================
    # 优化列表页爬取（加重试+处理重定向）
    # ========================
    async def _fetch_list_page(self, page: int) -> list[str]:
        """单页列表爬取（带重试）"""
        start = page * 25
        detail_urls = []
        retry = 0

        while retry < RETRY_TIMES:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        BASE_URL,
                        headers=HEADERS,
                        params={"start": start, "filter": ""},
                        timeout=aiohttp.ClientTimeout(total=20),
                        allow_redirects=True  # 允许重定向，适配豆瓣安全验证
                    ) as response:
                        if response.status == 200:
                            text = await response.text()
                            soup = BeautifulSoup(text, "lxml")
                            items = soup.find_all("div", class_="item")
                            for item in items:
                                a_tag = item.find("a")
                                if a_tag and "subject" in a_tag.get("href", ""):
                                    detail_urls.append(a_tag.get("href"))
                            print(f"📄 第{page+1}页列表解析完成，发现{len(items)}部电影")
                            return detail_urls
                        else:
                            print(f"⚠️  第{page+1}页列表请求失败（状态码：{response.status}），重试{retry+1}/{RETRY_TIMES}")
                            retry += 1
                            await asyncio.sleep(random.uniform(3, 5))  # 重试前延长延时
            except Exception as e:
                print(f"⚠️  第{page+1}页列表请求异常：{e}，重试{retry+1}/{RETRY_TIMES}")
                retry += 1
                await asyncio.sleep(random.uniform(3, 5))
        
        print(f"❌ 第{page+1}页列表请求失败（重试{RETRY_TIMES}次仍失败）")
        return []

    async def crawl_list_pages(self) -> list[str]:
        """批量爬取列表页"""
        detail_urls = []
        print("🎬 豆瓣Top250爬虫启动，开始获取电影链接...")

        # 异步爬取所有列表页
        tasks = [self._fetch_list_page(page) for page in range(self.pages)]
        results = await asyncio.gather(*tasks)

        # 合并结果
        for res in results:
            detail_urls.extend(res)
        
        # 去重（避免重复链接）
        detail_urls = list(set(detail_urls))
        print(f"✅ 链接获取完成，共找到{len(detail_urls)}部电影详情页链接")
        return detail_urls

    # ========================
    # 优化详情页爬取（加重试）
    # ========================
    async def crawl_detail_page(self, url: str, session: aiohttp.ClientSession) -> Optional[Dict]:
        async with self.semaphore:
            retry = 0
            while retry < RETRY_TIMES:
                try:
                    async with session.get(
                        url,
                        headers=HEADERS,
                        timeout=aiohttp.ClientTimeout(total=20),
                        allow_redirects=True
                    ) as response:
                        if response.status == 200:
                            text = await response.text()
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

                            print(f"✅ 解析完成：{movie['title']} | 导演：{movie['director']}")
                            await asyncio.sleep(random.uniform(*DETAIL_PAGE_DELAY) / MAX_CONCURRENT)
                            return movie
                        else:
                            print(f"⚠️  详情页[{url}]请求失败（状态码：{response.status}），重试{retry+1}/{RETRY_TIMES}")
                            retry += 1
                            await asyncio.sleep(random.uniform(3, 5))
                except Exception as e:
                    print(f"⚠️  详情页[{url}]请求异常：{e}，重试{retry+1}/{RETRY_TIMES}")
                    retry += 1
                    await asyncio.sleep(random.uniform(3, 5))
            
            print(f"❌ 详情页[{url}]请求失败（重试{RETRY_TIMES}次仍失败）")
            return None

    # ========================
    # 异步执行入口
    # ========================
    async def run(self) -> list[Dict]:
        detail_urls = await self.crawl_list_pages()
        if not detail_urls:
            print("❌ 未获取到任何详情页链接，爬虫终止")
            return []

        print(f"\n🎬 开始异步爬取电影详情页（共{len(detail_urls)}部，并发数{MAX_CONCURRENT}）...")
        start_time = time.time()

        async with aiohttp.ClientSession() as session:
            tasks = [self.crawl_detail_page(url, session) for url in detail_urls]
            results = await asyncio.gather(*tasks)

        self.movie_data = [movie for movie in results if movie is not None]
        success_count = len(self.movie_data)
        end_time = time.time()

        print("\n🎉 爬虫任务完成！")
        print(f"⏱️  总耗时：{end_time - start_time:.2f}秒")
        print(f"📈 统计：总链接数{len(detail_urls)} | 成功解析{success_count}部 | 失败{len(detail_urls)-success_count}部")
        return self.movie_data

    # ========================
    # 保存CSV
    # ========================
    def save_to_csv(self, file_path: str = "douban_top250.csv") -> None:
        if not self.movie_data:
            print("❌ 无数据可保存")
            return

        fieldnames = [
            "title", "director", "writer", "actors", "genre",
            "country", "language", "year", "duration", "imdb",
            "rating", "votes", "rating_dist", "intro", "awards", "detail_url"
        ]

        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.movie_data)
            print(f"✅ 数据已保存到：{file_path}")
        except Exception as e:
            print(f"❌ 保存CSV失败：{e}")

# 程序入口
if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        pages = int(input("请输入爬取页数（1-10，默认10）："))
    except ValueError:
        pages = 10

    spider = DoubanTop250Spider(pages=pages)
    movie_data = asyncio.run(spider.run())

    if movie_data:
        spider.save_to_csv("douban_top250.csv")