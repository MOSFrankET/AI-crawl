"""
main.py — 入口模块
串联抓取（scraper）与 AI 摘要（summarizer）的完整流程。
"""

import os
import sys
import datetime
from scraper import scrape_and_save
from summarizer import generate_brief

# 强制 UTF-8 输出，避免 Windows 终端 emoji 乱码
sys.stdout.reconfigure(encoding="utf-8")

# 默认抓取目标列表（可按需扩展）
DEFAULT_SOURCES = [
    {"url": "https://techcrunch.com", "name": "techcrunch"},
]


def run(sources: list = None):
    """
    执行完整流程：抓取 → AI 摘要 → 保存简报。

    参数：
        sources: 抓取目标列表，每项包含 url 和 name 字段。
                 默认使用 DEFAULT_SOURCES。
    """
    if sources is None:
        sources = DEFAULT_SOURCES

    date_str = datetime.date.today().isoformat()
    os.makedirs("data/briefs", exist_ok=True)

    for source in sources:
        url = source["url"]
        name = source["name"]
        print(f"\n{'='*50}")
        print(f"开始处理：{name} ({url})")
        print(f"{'='*50}")

        # 第一步：抓取网页内容
        try:
            raw_path = scrape_and_save(url, name)
        except Exception as e:
            print(f"抓取失败，跳过 {name}：{e}")
            continue

        # 第二步：读取抓取内容
        with open(raw_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 第三步：调用 Claude API 生成简报
        try:
            brief = generate_brief(content)
        except Exception as e:
            print(f"生成简报失败，跳过 {name}：{e}")
            continue

        # 第四步：保存简报
        brief_path = f"data/briefs/{date_str}_{name}_brief.md"
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(brief)
        print(f"简报已保存：{brief_path}")

        # 输出到终端
        print(f"\n{'='*50}")
        print(f"{name.upper()} AI 简报")
        print(f"{'='*50}")
        print(brief)

    print(f"\n所有任务完成！日期：{date_str}")


if __name__ == "__main__":
    run()
