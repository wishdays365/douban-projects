import pandas as pd
import json
import re
import os

def csv_to_json(csv_path, json_path=None):
    if not os.path.exists(csv_path):
        print(f"❌ CSV 文件不存在：{csv_path}")
        return False

    if json_path is None:
        json_path = csv_path.replace(".csv", ".json")

    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # 数值字段
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(0)
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)
    df["duration"] = pd.to_numeric(df["duration"], errors="coerce").fillna(0).astype(int)

    # 多值拆分
    def split_field(v):
        if pd.isna(v):
            return []
        return [i.strip() for i in re.split(r"[、/]", str(v)) if i.strip()]

    movies = []
    for _, row in df.iterrows():
        movies.append({
            "title": row["title"],
            "director": split_field(row["director"]),
            "writer": split_field(row["writer"]),
            "actors": split_field(row["actors"]),
            "genre": split_field(row["genre"]),
            "country": split_field(row["country"]),
            "language": split_field(row["language"]),
            "year": row["year"],
            "duration": row["duration"],
            "imdb": row["imdb"],
            "rating": row["rating"],
            "votes": row["votes"],
            "rating_dist": row["rating_dist"],
            "intro": row["intro"],
            "awards": row["awards"],
            "detail_url": row["detail_url"]
        })

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)

    print(f"✅ CSV → JSON 完成：{json_path}")
    return True


# 允许单独运行
if __name__ == "__main__":
    csv_to_json("douban_top250.csv")
