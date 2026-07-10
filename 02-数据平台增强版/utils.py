import csv
import random
import time
import logging
from typing import List, Dict, Optional
import requests
from requests.exceptions import RequestException
from log_config import setup_logging

# 使用统一的日志配置
logger = setup_logging()

# 随机请求头（新增更多UA，降低反爬概率）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
]

# 其余代码不变...

def get_random_ua() -> str:
    """获取随机User-Agent"""
    return random.choice(USER_AGENTS)
logger = logging.getLogger("douban_top250.utils")


def request_with_retry(
    url: str,
    max_retry: int = 3,
    backoff_factor: float = 0.5,
    session: Optional[requests.Session] = None,
    timeout: float = 10.0,
) -> Optional[requests.Response]:
    """带重试机制的HTTP请求（支持可复用 session 与指数退避）。

    返回 requests.Response 或在失败时返回 None（调用方应当检查返回值）。
    """
    headers = {"User-Agent": get_random_ua()}
    sess = session or requests
    for i in range(max_retry):
        try:
            resp = sess.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp
        except RequestException as e:
            wait = backoff_factor * (2 ** i)
            jitter = random.uniform(0, 0.1 * wait)
            total_wait = wait + jitter
            logger.warning(f"请求失败（第{i+1}次重试，等待{total_wait:.1f}s）：{e}")
            time.sleep(total_wait)
    logger.error(f"多次请求失败：{url}")
    return None

def save_to_csv(data: List[Dict], file_path: str = "movies.csv") -> None:
    """保存数据到CSV文件"""
    if not data:
        logger.info("无数据可保存！")
        return
    # 提取字段名（取第一条数据的键）
    fieldnames = data[0].keys()
    try:
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        logger.info(f"数据已保存到 {file_path}")
    except IOError as e:
        logger.error(f"保存CSV失败：{e}")

def read_from_csv(file_path: str = "movies.csv") -> List[Dict]:
    """从CSV读取数据"""
    data = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        logger.info(f"成功读取 {len(data)} 条电影数据")
        return data
    except FileNotFoundError:
        logger.warning(f"未找到数据文件 {file_path}，请先爬取数据！")
        return []
    except IOError as e:
        logger.error(f"读取CSV失败：{e}")
        return []