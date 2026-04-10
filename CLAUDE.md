# 科技资讯 AI 简报项目

## 项目目标
自动抓取科技资讯网站（TechCrunch 等），通过 Claude API 生成适合小红书/即刻/公众号风格的 AI 简报，并通过 GitHub Actions 实现每日 08:00（北京时间）自动执行。

## 项目结构
```
.
├── CLAUDE.md           # 本文件，项目说明
├── .env                # API 密钥（不提交 git）
├── .env.example        # 密钥模板
├── requirements.txt    # Python 依赖
├── scraper.py          # 网页抓取模块（Firecrawl）
├── summarizer.py       # AI 摘要模块（Claude API）
├── main.py             # 入口，串联抓取与摘要
├── run.sh              # 一键执行脚本
├── data/
│   └── raw/            # 原始抓取结果（Markdown 格式，按日期命名）
└── .github/
    └── workflows/
        └── daily_brief.yml  # GitHub Actions 定时任务
```

## 模块说明
- **scraper.py**：接收 URL，调用 Firecrawl API 将网页转为 Markdown，保存到 `data/raw/`
- **summarizer.py**：读取 `data/raw/` 最新文件，调用 Claude API 生成结构化简报
- **main.py**：按顺序调用 scraper → summarizer，输出最终简报

## 代码规范
- 所有函数必须有中文注释说明用途和参数
- API Key 通过 `.env` 文件加载，禁止硬编码
- 文件命名格式：`YYYY-MM-DD_来源名称.md`
- 异常需捕获并打印清晰的错误信息
