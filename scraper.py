"""
scraper.py — 网页抓取模块
使用 Firecrawl API 将目标网页转为 Markdown，并保存到 data/raw/ 目录。
"""

import os
import datetime
from firecrawl.v1 import V1FirecrawlApp
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()


def scrape_url(url: str) -> str:
    """
    抓取指定 URL 的内容并转为 Markdown。

    参数：
        url: 目标网页地址

    返回：
        网页内容的 Markdown 字符串

    异常：
        若 API Key 未设置或抓取失败，抛出异常并打印错误信息。
    """
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY 未设置，请检查 .env 文件")

    print(f"正在抓取：{url}")
    app = V1FirecrawlApp(api_key=api_key)
    result = app.scrape_url(url, formats=["markdown"])

    # 从结果中提取 markdown 内容
    if hasattr(result, "markdown") and result.markdown:
        return result.markdown
    else:
        raise ValueError(f"抓取结果为空，请确认 URL 是否正确：{url}")


def save_raw(content: str, source_name: str) -> str:
    """
    将抓取内容保存到 data/raw/ 目录，文件名包含日期。

    参数：
        content:     要保存的 Markdown 文本
        source_name: 来源名称（用于文件名，如 "techcrunch"）

    返回：
        保存后的文件路径
    """
    # 确保目录存在
    os.makedirs("data/raw", exist_ok=True)

    date_str = datetime.date.today().isoformat()
    filename = f"data/raw/{date_str}_{source_name}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"已保存到：{filename}（{len(content)} 字符）")
    return filename


def scrape_and_save(url: str, source_name: str) -> str:
    """
    一步完成抓取并保存。

    参数：
        url:         目标网页地址
        source_name: 来源名称（用于文件名）

    返回：
        保存后的文件路径
    """
    content = scrape_url(url)
    return save_raw(content, source_name)


# 直接运行此文件时，用 TechCrunch 做测试
if __name__ == "__main__":
    try:
        saved_path = scrape_and_save(
            url="https://techcrunch.com",
            source_name="techcrunch"
        )
        print(f"\n抓取成功！文件路径：{saved_path}")
    except Exception as e:
        print(f"\n抓取失败：{e}")
