import matplotlib.pyplot as plt
import json
import os
from collections import Counter
from analyzer import MovieAnalyzer

# 全局配置：解决中文乱码
plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

class DoubanTop250Visualizer:
    def __init__(self, json_path):
        self.json_path = json_path
        # 修复：增加JSON文件存在性校验
        if not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
            raise ValueError(f"JSON文件无效（不存在/为空）：{json_path}")
        self.analyzer = MovieAnalyzer(json_path)
        self.static_dir = os.path.join(os.path.dirname(json_path), "static")
        os.makedirs(self.static_dir, exist_ok=True)  # 自动创建static目录

    # ========== 本地可视化图表（Matplotlib） ==========
    def plot_genre_bar(self):
        """生成电影类型分布柱状图（考察功能2）"""
        genre_data = self.analyzer.genre_analysis()
        if not genre_data:
            print("❌ 无类型数据生成图表")
            return None

        plt.figure(figsize=(12, 6))
        bars = plt.bar(genre_data.keys(), genre_data.values(), color="#4472C4")
        # 添加数值标签
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f"{int(height)}", ha="center", va="bottom", fontsize=10)

        plt.title("豆瓣Top250电影类型分布", fontsize=16, pad=20)
        plt.xlabel("电影类型", fontsize=12)
        plt.ylabel("数量（部）", fontsize=12)
        plt.xticks(rotation=45, ha="right")
        plt.grid(axis="y", linestyle="--", alpha=0.7)
        plt.tight_layout()

        # 保存图片到static目录
        img_path = os.path.join(self.static_dir, "genre_bar.png")
        plt.savefig(img_path, dpi=100, bbox_inches="tight")
        plt.close()
        print(f"✅ 类型分布图已保存：{img_path}")
        return img_path

    def plot_country_bar(self):
        """生成国家/地区分布柱状图（额外功能）"""
        country_data = self.analyzer.country_analysis()
        if not country_data:
            print("❌ 无国家数据生成图表")
            return None

        plt.figure(figsize=(12, 6))
        bars = plt.bar(country_data.keys(), country_data.values(), color="#5B9BD5")
        # 添加数值标签
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f"{int(height)}", ha="center", va="bottom", fontsize=10)

        plt.title("豆瓣Top250电影国家/地区分布", fontsize=16, pad=20)
        plt.xlabel("国家/地区", fontsize=12)
        plt.ylabel("数量（部）", fontsize=12)
        plt.xticks(rotation=45, ha="right")
        plt.grid(axis="y", linestyle="--", alpha=0.7)
        plt.tight_layout()

        img_path = os.path.join(self.static_dir, "country_bar.png")
        plt.savefig(img_path, dpi=100, bbox_inches="tight")
        plt.close()
        print(f"✅ 国家分布图已保存：{img_path}")
        return img_path

    def plot_actor_bar(self):
        """生成演员出镜次数柱状图（额外功能2）"""
        actor_data = self.analyzer.actor_analysis()
        if not actor_data:
            print("❌ 无演员数据生成图表")
            return None

        plt.figure(figsize=(12, 6))
        bars = plt.bar(actor_data.keys(), actor_data.values(), color="#E74C3C")
        # 添加数值标签
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                    f"{int(height)}", ha="center", va="bottom", fontsize=10)

        plt.title("豆瓣Top250电影演员出镜次数Top10", fontsize=16, pad=20)
        plt.xlabel("演员", fontsize=12)
        plt.ylabel("出镜次数（部）", fontsize=12)
        plt.xticks(rotation=45, ha="right")
        plt.grid(axis="y", linestyle="--", alpha=0.7)
        plt.tight_layout()

        img_path = os.path.join(self.static_dir, "actor_bar.png")
        plt.savefig(img_path, dpi=100, bbox_inches="tight")
        plt.close()
        print(f"✅ 演员出镜图已保存：{img_path}")
        return img_path

    # ========== Web可视化数据（供ECharts调用） ==========
    def get_echarts_genre_data(self):
        """生成ECharts兼容的类型数据"""
        genre_data = self.analyzer.genre_analysis()
        return {"xAxis": list(genre_data.keys()), "yAxis": list(genre_data.values())}

    def get_echarts_country_data(self):
        """修复：返回前端兼容的列表格式（而非原始字典）"""
        country_data = self.analyzer.country_analysis()
        # 转换为[{cn_name: "美国", count: 100}, ...]格式
        return [{"cn_name": k, "count": v} for k, v in country_data.items()]
    def get_echarts_actor_data(self):
        """生成ECharts兼容的演员数据"""
        actor_data = self.analyzer.actor_analysis()
        return {"xAxis": list(actor_data.keys()), "yAxis": list(actor_data.values())}

    def get_rating_year_stats(self):
        """获取评分/年份统计数据（供Web首页展示）"""
        return self.analyzer.rating_year_analysis()

# 可视化菜单（适配main.py交互）
def generate_visual_menu(visualizer):
    while True:
        print("\n===== 📊 可视化图表生成菜单 =====")
        print("1. 电影类型分布柱状图")
        print("2. 国家/地区分布柱状图")
        print("3. 演员出镜次数柱状图")
        print("4. 返回主菜单")
        choice = input("请选择操作（1-4）：").strip()

        if choice == "1":
            visualizer.plot_genre_bar()
        elif choice == "2":
            visualizer.plot_country_bar()
        elif choice == "3":
            visualizer.plot_actor_bar()
        elif choice == "4":
            break
        else:
            print("❌ 无效输入，请选择1-4！")