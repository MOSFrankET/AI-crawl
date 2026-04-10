"""
summarizer.py — AI 摘要模块
读取 data/raw/ 下最新的抓取文件，调用 Claude API 生成适合小红书/即刻风格的科技简报。
"""

import os
import glob
import anthropic
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 爆款内容生成 Prompt（小红书/即刻风格）
SYSTEM_PROMPT = """你是一个擅长写爆款科技内容的新媒体编辑，专门为即刻、小红书、微信公众号创作内容。
你的文章特点：
- 语气像在跟朋友聊天，不用专业术语堆砌
- 善用"绝了""直接""狠活""遥遥领先""yyds"等网络用语
- 标题带 emoji，抓人眼球
- 数据和对比信手拈来，让读者有"涨知识了"的感觉
- 擅长把复杂事件讲得清楚、有趣，让普通人也能看懂
- 结尾必有互动引导，引发评论区讨论"""

USER_PROMPT_TEMPLATE = """根据以下科技资讯内容，生成一篇适合在即刻/小红书传播的深度科技简报。

要求输出格式如下（严格按此结构，不要多余说明）：

**【今日简报标题】**
（带 emoji，15字以内，让人忍不住点开）

---

**🔥 要点一：**（一句话核心结论，口语化，带数据或对比）
📎 来源：（从原文中提取该文章的完整 URL）

（详细解析：约500字，用口语讲清楚"这件事是什么→为什么重要→对我们有什么影响"三层逻辑。重要结论、数字、对比用**加粗**标注。语气像在给朋友讲八卦，生动有料。）

---

**🔥 要点二：**（一句话核心结论，口语化，带数据或对比）
📎 来源：（从原文中提取该文章的完整 URL）

（详细解析：约500字，同上要求。）

---

**🔥 要点三：**（一句话核心结论，口语化，带数据或对比）
📎 来源：（从原文中提取该文章的完整 URL）

（详细解析：约500字，同上要求。）

---

**【互动引导】**
（一个问题，引发读者在评论区说出自己的看法，15-25字）

---
以下是原始资讯内容：

{content}"""


def get_latest_raw_file() -> str:
    """
    获取 data/raw/ 目录下最新的 Markdown 文件路径。

    返回：
        最新文件的路径字符串

    异常：
        若目录为空或不存在，抛出 FileNotFoundError
    """
    files = glob.glob("data/raw/*.md")
    if not files:
        raise FileNotFoundError("data/raw/ 目录下没有找到任何文件，请先运行 scraper.py")

    # 按文件修改时间排序，取最新的
    latest = max(files, key=os.path.getmtime)
    print(f"读取文件：{latest}")
    return latest


def truncate_content(content: str, max_chars: int = 20000) -> str:
    """
    清理并截断内容，跳过页面顶部的验证/广告文本，保留实际文章部分。

    参数：
        content:   原始文本
        max_chars: 最大字符数（默认 12000）

    返回：
        清理并截断后的文本
    """
    # 找到第一个 ### 标题（文章列表的起点），跳过顶部的 Cloudflare 验证等杂音
    article_start = content.find("### [")
    if article_start > 0:
        print(f"跳过顶部 {article_start} 字符的非文章内容")
        content = content[article_start:]

    if len(content) <= max_chars:
        return content
    print(f"内容过长（{len(content)} 字符），已截断至 {max_chars} 字符")
    return content[:max_chars] + "\n\n[内容已截断...]"


def generate_brief(content: str) -> str:
    """
    调用 Claude API，根据资讯内容生成小红书/即刻风格的简报。

    参数：
        content: 原始资讯的 Markdown 文本

    返回：
        生成的简报文本
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY 未设置，请检查 .env 文件")

    client = anthropic.Anthropic(api_key=api_key)

    # 截断内容，控制 token 消耗
    truncated = truncate_content(content)
    prompt = USER_PROMPT_TEMPLATE.format(content=truncated)

    print("正在调用 Claude API 生成简报...")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",  # 速度快、成本低，适合批量摘要
        max_tokens=4096,  # 深度解析每条约500字，三条共需更大空间
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


def summarize_latest() -> str:
    """
    读取最新抓取文件并生成简报，一步到位。

    返回：
        生成的简报文本
    """
    filepath = get_latest_raw_file()
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    brief = generate_brief(content)
    return brief


# 直接运行此文件时，输出最新简报
if __name__ == "__main__":
    import sys
    import datetime
    # 强制 stdout 使用 UTF-8，避免 Windows 终端 emoji 乱码
    sys.stdout.reconfigure(encoding="utf-8")

    try:
        result = summarize_latest()

        # 保存简报到文件
        os.makedirs("data/briefs", exist_ok=True)
        date_str = datetime.date.today().isoformat()
        brief_path = f"data/briefs/{date_str}_brief.md"
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"简报已保存到：{brief_path}")

        print("\n" + "="*50)
        print("AI 简报生成结果：")
        print("="*50)
        print(result)
        print("="*50)
    except Exception as e:
        print(f"\n生成失败：{e}")
