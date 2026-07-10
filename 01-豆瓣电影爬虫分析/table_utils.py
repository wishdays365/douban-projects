# table_utils.py（修正版，确保可导入DoubanTop250Table类）
import csv
import os
from prettytable import PrettyTable
import pandas as pd

# 确保文件编码为UTF-8，无语法错误
class DoubanTop250Table:
    """豆瓣Top250电影数据制表工具（可正常导入版）"""
    
    def __init__(self, csv_path="douban_top250.csv"):
        """
        初始化函数
        :param csv_path: CSV文件路径（默认douban_top250.csv）
        """
        self.csv_path = csv_path
        self.raw_data = []  # 原始数据
        self.processed_data = []  # 处理后的数据
        self.is_data_loaded = False  # 数据加载状态
        self._load_and_process_data()

    def _load_and_process_data(self):
        """加载并预处理CSV数据"""
        try:
            # 检查文件是否存在
            if not os.path.exists(self.csv_path):
                print(f"❌ 未找到数据文件：{self.csv_path}，请先爬取数据！")
                return
            
            # 读取CSV文件（UTF-8编码，兼容中文）
            with open(self.csv_path, 'r', encoding='utf-8', newline='') as f:
                csv_reader = csv.DictReader(f)
                self.raw_data = [row for row in csv_reader]
            
            # 数据预处理（提取关键字段，简化展示）
            for row in self.raw_data:
                # 解析评分分布为字典
                rating_dist = row.get('rating_dist', '').replace(' ', '').strip('"').split(',')
                rating_dist_dict = {}
                for item in rating_dist:
                    if '%' in item and ':' in item:
                        key, value = item.split(':')
                        rating_dist_dict[key] = value
                
                # 提取核心字段（匹配可视化模块的中文列名）
                processed_row = {
                    '电影名称': row.get('title', ''),
                    '导演': row.get('director', ''),
                    '类型': row.get('genre', ''),
                    '国家/地区': row.get('country', ''),
                    '上映年份': row.get('year', ''),
                    '豆瓣评分': row.get('rating', ''),
                    '评价人数': row.get('votes', ''),
                    '5星占比': rating_dist_dict.get('5星', ''),
                    'IMDb编号': row.get('imdb', '')
                }
                self.processed_data.append(processed_row)
            
            self.is_data_loaded = True
            print(f"✅ 成功加载 {len(self.processed_data)} 条电影数据")
        
        except Exception as e:
            print(f"❌ 数据加载失败：{str(e)}")
            self.is_data_loaded = False

    def show_terminal_table(self, limit=None):
        """
        在终端展示美观的表格
        :param limit: 展示条数（None表示全部）
        """
        if not self.is_data_loaded or not self.processed_data:
            print("❌ 无有效数据可展示，请先确认数据已爬取！")
            return
        
        # 截取数据（避免全部展示刷屏）
        display_data = self.processed_data[:limit] if limit else self.processed_data
        
        # 创建表格对象
        table = PrettyTable()
        table.field_names = list(display_data[0].keys())
        
        # 表格样式配置
        table.align = 'l'  # 左对齐
        table.padding_width = 1
        table.horizontal_char = '-'
        table.vertical_char = '|'
        table.junction_char = '+'
        
        # 填充数据
        for row in display_data:
            table.add_row(list(row.values()))
        
        # 打印表格
        print("\n📋 豆瓣Top250电影数据表（终端版）")
        print(table)

    def export_excel(self, output_path="douban_top250_table.xlsx", sheet_name="电影数据"):
        """
        导出数据到Excel文件（兼容可视化模块的中文列名）
        :param output_path: 输出文件路径
        :param sheet_name: Excel工作表名称
        """
        if not self.is_data_loaded or not self.processed_data:
            print("❌ 无有效数据可导出，请先确认数据已爬取！")
            return
        
        try:
            # 转换为DataFrame并导出
            df = pd.DataFrame(self.processed_data)
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                
                # 自动调整列宽
                worksheet = writer.sheets[sheet_name]
                for col in worksheet.columns:
                    max_length = 0
                    column = col[0].column_letter
                    for cell in col:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)  # 限制最大列宽
                    worksheet.column_dimensions[column].width = adjusted_width
            
            print(f"✅ Excel表格已导出至：{os.path.abspath(output_path)}")
        except Exception as e:
            print(f"❌ Excel导出失败：{str(e)}")
            print(f"💡 请安装依赖：pip install openpyxl pandas")

# 确保函数名正确，可被main.py导入
def generate_table_menu(table_tool):
    """制表子菜单（独立函数，便于主程序调用）"""
    while True:
        print("\n----- 制表功能子菜单 -----")
        print("1. 终端展示前10条数据")
        print("2. 终端展示全部数据")
        print("3. 导出Excel表格")
        print("4. 返回主菜单")
        sub_choice = input("请输入子菜单序号（1-4）：").strip()
        
        if sub_choice == "1":
            table_tool.show_terminal_table(limit=10)
        elif sub_choice == "2":
            table_tool.show_terminal_table(limit=None)
        elif sub_choice == "3":
            output_path = input("请输入Excel输出路径（默认：douban_top250_table.xlsx）：").strip()
            if not output_path:
                output_path = "douban_top250_table.xlsx"
            table_tool.export_excel(output_path)
        elif sub_choice == "4":
            print("🔙 返回主菜单...")
            break
        else:
            print("❌ 输入无效，请输入1-4之间的数字！")

# 测试代码（可选，不影响导入）
if __name__ == "__main__":
    # 测试类是否可实例化
    try:
        table_tool = DoubanTop250Table()
        generate_table_menu(table_tool)
    except Exception as e:
        print(f"测试失败：{str(e)}")