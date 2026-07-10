import json
import os
import time
from datetime import datetime, timedelta
import threading
from log_config import setup_logging

# 初始化日志
logger = setup_logging()

class DataExpiryManager:
    """
    数据保质期管理器 (Item-level)
    管理每个数据项（以URL或ID为键）的过期状态。
    """
    def __init__(self, root_dir=None, expiry_hours=3, expiry_file="item_expiry.json"):
        self.root_dir = root_dir or os.path.dirname(os.path.abspath(__file__))
        self.expiry_hours = expiry_hours
        self.expiry_file = os.path.join(self.root_dir, expiry_file)
        self.lock_file = os.path.join(self.root_dir, "crawl.lock")
        self.lock = threading.Lock()
        self.full_data = self._load_full_data()
        
        # 如果是从文件恢复的（即expiry文件不存在但数据存在），保存一次以创建文件
        if not os.path.exists(self.expiry_file) and self.full_data.get("global", {}).get("last_global_crawl_time"):
            self._save_full_data()

    def _load_full_data(self):
        """加载完整保质期数据结构"""
        default_structure = {
            "global": {
                "expiry_hours": self.expiry_hours,
                "last_global_crawl_time": None
            },
            "items": {},
            "meta": {
                "crawl_status": "idle",
                "data_valid": False
            }
        }
        
        if not os.path.exists(self.expiry_file):
            # 尝试从现有数据文件恢复状态（解决"有数据但显示过期"的问题）
            data_file = os.path.join(self.root_dir, "douban_data_v2.json")
            if os.path.exists(data_file):
                try:
                    mtime = os.path.getmtime(data_file)
                    default_structure["global"]["last_global_crawl_time"] = mtime
                    default_structure["meta"]["data_valid"] = True
                    
                    # 尝试恢复 items 状态
                    with open(data_file, "r", encoding="utf-8") as f:
                        movies = json.load(f)
                        if isinstance(movies, list):
                            for movie in movies:
                                url = movie.get("detail_url")
                                if url:
                                    # 假设所有条目都是在文件修改时间更新的
                                    default_structure["items"][url] = mtime
                    logger.info(f"已从现有数据文件恢复保质期状态（时间：{datetime.fromtimestamp(mtime)}）")
                except Exception as e:
                    logger.warning(f"尝试从数据文件恢复状态失败: {e}")
            
            return default_structure
            
        try:
            with open(self.expiry_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 简单校验结构，如果不是字典或缺少关键key，则重置或迁移
                if not isinstance(data, dict):
                    return default_structure
                
                # 兼容旧的简单字典格式（迁移到 items）
                if "items" not in data and any(k.startswith("http") for k in data.keys()):
                    return {
                        "global": default_structure["global"],
                        "items": data,
                        "meta": default_structure["meta"]
                    }
                
                # 确保基本结构存在
                if "items" not in data: data["items"] = {}
                if "global" not in data: data["global"] = default_structure["global"]
                if "meta" not in data: data["meta"] = default_structure["meta"]
                
                return data
        except Exception as e:
            logger.error(f"加载保质期数据失败: {e}")
            return default_structure

    def _save_full_data(self):
        """保存完整数据"""
        try:
            with open(self.expiry_file, "w", encoding="utf-8") as f:
                json.dump(self.full_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存保质期数据失败: {e}")

    def is_expired(self, item_id):
        """
        检查项目是否过期
        :param item_id: 项目唯一标识 (如 URL)
        :return: True (已过期或不存在), False (未过期)
        """
        items = self.full_data.get("items", {})
        if item_id not in items:
            return True
        
        last_update_ts = items[item_id]
        try:
            last_update = datetime.fromtimestamp(last_update_ts)
            if datetime.now() - last_update > timedelta(hours=self.expiry_hours):
                return True
        except Exception:
            return True # 解析失败视为过期
        
        return False

    def update_expiry(self, item_id):
        """更新项目的过期时间为当前时间"""
        with self.lock:
            # 重新加载以防其他进程修改（虽然这里是简单锁，但在多进程下仍有风险，暂且这样）
            # self.full_data = self._load_full_data() 
            # 考虑到性能，暂不每次都重载，但在并发高时可能覆盖。
            # 鉴于这是单机爬虫，冲突概率较低。
            
            if "items" not in self.full_data:
                self.full_data["items"] = {}
            
            self.full_data["items"][item_id] = time.time()
            self._save_full_data()

    def update_global_status(self, status="completed"):
        """更新全局爬取状态"""
        with self.lock:
            if "global" not in self.full_data:
                self.full_data["global"] = {}
            if "meta" not in self.full_data:
                self.full_data["meta"] = {}
                
            if status == "completed":
                self.full_data["global"]["last_global_crawl_time"] = time.time()
                self.full_data["meta"]["data_valid"] = True
                self.full_data["meta"]["crawl_status"] = "idle"
            elif status == "running":
                self.full_data["meta"]["crawl_status"] = "running"
            
            self._save_full_data()

    def get_expiry_info(self, item_id):
        """获取项目的过期时间戳"""
        return self.full_data.get("items", {}).get(item_id)

    # ========== 新增方法以适配 app.py ==========

    def is_data_expired(self):
        """检查全局数据是否过期（3小时）"""
        # 重新加载以获取最新状态
        self.full_data = self._load_full_data()
        
        last_ts = self.full_data.get("global", {}).get("last_global_crawl_time")
        if not last_ts:
            return True

        try:
            last_crawl = datetime.fromtimestamp(float(last_ts))
            expiry_time = last_crawl + timedelta(hours=self.expiry_hours)
            return datetime.now() > expiry_time
        except Exception:
            return True

    def is_crawl_running(self):
        """检查是否正在爬取"""
        self.full_data = self._load_full_data()
        return self.full_data.get("meta", {}).get("crawl_status") == "running"

    def acquire_crawl_lock(self):
        """获取爬取锁（防止重复爬取）"""
        try:
            if os.path.exists(self.lock_file):
                # 检查锁是否过期（例如超过1小时）
                try:
                    mtime = os.path.getmtime(self.lock_file)
                    if time.time() - mtime > 3600:
                        os.remove(self.lock_file)
                    else:
                        return False
                except Exception:
                    pass
            
            with open(self.lock_file, "w") as f:
                f.write(str(datetime.now().timestamp()))
            return True
        except Exception:
            return False

    def release_crawl_lock(self):
        """释放爬取锁"""
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
        except Exception:
            pass

    def update_crawl_status(self, status, pages=10):
        """更新爬取状态"""
        with self.lock:
            if "global" not in self.full_data:
                self.full_data["global"] = {}
            if "meta" not in self.full_data:
                self.full_data["meta"] = {}
            
            self.full_data["meta"]["crawl_status"] = status
            self.full_data["meta"]["crawl_pages"] = pages

            if status == "completed":
                self.full_data["global"]["last_global_crawl_time"] = time.time()
                self.full_data["meta"]["data_valid"] = True
                self.full_data["meta"]["last_migration"] = time.time()
            elif status == "error":
                # 错误时不更新 last_global_crawl_time，但可能需要标记 data_valid
                pass
            
            self._save_full_data()

    def get_data_status(self):
        """获取数据状态详情"""
        self.full_data = self._load_full_data()
        
        last_ts = self.full_data.get("global", {}).get("last_global_crawl_time")
        
        if not last_ts:
            return {
                "status": "no_data",
                "message": "暂无爬取数据，系统将自动爬取豆瓣Top250数据",
                "expired": True
            }
        
        last_crawl = datetime.fromtimestamp(float(last_ts))
        expiry_time = last_crawl + timedelta(hours=self.expiry_hours)
        now = datetime.now()
        
        crawl_status = self.full_data.get("meta", {}).get("crawl_status", "idle")
        
        if crawl_status == "running":
            return {
                "status": "crawling",
                "message": f"正在自动爬取数据（最后爬取：{last_crawl.strftime('%Y-%m-%d %H:%M:%S')}）",
                "expired": True
            }
        
        if now > expiry_time:
            return {
                "status": "expired",
                "message": f"数据已过期（最后爬取：{last_crawl.strftime('%Y-%m-%d %H:%M:%S')}），系统将自动重新爬取",
                "expired": True
            }
        
        # 计算剩余有效期
        remaining = expiry_time - now
        hours = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        
        return {
            "status": "fresh",
            "message": f"数据有效（最后爬取：{last_crawl.strftime('%Y-%m-%d %H:%M:%S')}，剩余有效期：{hours}小时{minutes}分钟）",
            "expired": False
        }
