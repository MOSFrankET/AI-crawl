"""
video_gen.py — 视频生成模块（增强版）
读取 data/briefs/ 最新简报，生成 9:16 竖屏短视频：
  - 背景素材：优先 Pexels 视频接口；无合适视频则降级为图片 + Ken Burns 缩放动效
  - 字幕：edge-tts 时间戳驱动的逐句同步字幕，当前句高亮为黄色，居中显示
  - 语音：edge-tts（微软神经语音，无需 API Key）
  - 合成：MoviePy 输出 MP4，兼容 Windows 和 Ubuntu
"""

import os
import sys
import glob
import re
import logging
import asyncio
import datetime
import tempfile
from io import BytesIO
from typing import Optional

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from moviepy import (
    AudioFileClip,
    VideoFileClip,
    VideoClip,
    concatenate_videoclips,
)
import edge_tts

# ─────────────────────────── 全局配置 ────────────────────────────────
FONT_PATH        = "C:/ai/ai crawl/font/SourceHanSerifSC-VF.otf"
VIDEO_WIDTH      = 1080
VIDEO_HEIGHT     = 1920
TTS_VOICE        = "zh-CN-XiaoxiaoNeural"
OUTPUT_DIR       = "output/videos"
BRIEFS_DIR       = "data/briefs"

# ─────────────────────────── 日志配置 ────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

load_dotenv()


# ════════════════════════════════════════════════════════════════════
# 1. 简报文件定位与解析（不变）
# ════════════════════════════════════════════════════════════════════

def get_latest_brief() -> str:
    """返回 data/briefs/ 目录中最新的 .md 文件路径。"""
    files = glob.glob(os.path.join(BRIEFS_DIR, "*.md"))
    if not files:
        log.error("data/briefs/ 下没有找到简报文件，请先运行 main.py 生成简报")
        sys.exit(1)
    latest = max(files, key=os.path.getmtime)
    log.info(f"使用简报文件：{latest}")
    return latest


def parse_brief(filepath: str) -> dict:
    """
    解析简报 Markdown，提取标题与三条要点。

    返回：
        {"title": str, "points": [{"header": str, "body": str}, ...]}
    """
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    title_match = re.search(r"\*\*【(.+?)】\*\*", text)
    title = title_match.group(1) if title_match else "今日科技简报"

    header_pattern = re.compile(r"\*\*🔥\s*要点[一二三]：\*\*\s*(.+)")
    headers = header_pattern.findall(text)

    body_pattern = re.compile(
        r"📎\s*来源：.+?\n\n([\s\S]+?)(?=\n---|\Z)", re.MULTILINE
    )
    bodies = body_pattern.findall(text)

    points = []
    for i in range(min(3, len(headers))):
        body = bodies[i].strip() if i < len(bodies) else ""
        points.append({"header": headers[i].strip(), "body": body})

    if not points:
        log.error("未能从简报中提取到任何要点，请检查简报文件格式")
        sys.exit(1)

    log.info(f"解析完成：标题='{title}'，共 {len(points)} 条要点")
    return {"title": title, "points": points}


# ════════════════════════════════════════════════════════════════════
# 2. 台本口语化改写（不变）
# ════════════════════════════════════════════════════════════════════

def rewrite_for_spoken(header: str, body: str, max_chars: int = 200) -> str:
    """将要点改写为口语化短文（约 150-200 字，对应 25-30s）。"""
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", cleaned)
    cleaned = re.sub(r"\[(.+?)\]\(.*?\)", r"\1", cleaned)
    cleaned = re.sub(r"📎.+\n?", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    spoken = header + "。"
    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    for para in paragraphs:
        if len(spoken) + len(para) + 1 <= max_chars:
            spoken += para
        else:
            candidate = para[:max_chars - len(spoken)]
            cut = max(
                candidate.rfind("。"),
                candidate.rfind("！"),
                candidate.rfind("？"),
                candidate.rfind("…"),
            )
            if cut > 10:
                spoken += candidate[: cut + 1]
            break

    return spoken.strip()


# ════════════════════════════════════════════════════════════════════
# 3. TTS 语音合成 + 词语边界时间戳
# ════════════════════════════════════════════════════════════════════

async def _tts_with_words_async(text: str, out_path: str) -> list:
    """
    异步调用 edge-tts，同时收集 WordBoundary 时间戳事件。

    参数：
        text:     待合成的文本
        out_path: 输出 MP3 文件路径

    返回：
        word boundary 列表，每项 {text, offset(秒), duration(秒)}
    """
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    word_boundaries = []

    with open(out_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append({
                    "text":     chunk["text"],
                    "offset":   chunk["offset"]   / 10_000_000,   # 100ns → 秒
                    "duration": chunk["duration"] / 10_000_000,
                })

    return word_boundaries


def generate_tts_with_words(text: str, out_path: str) -> list:
    """
    同步包装器：生成语音文件并返回词语边界时间戳列表。

    参数：
        text:     待合成的文本
        out_path: 输出 MP3 文件路径

    返回：
        word boundary 列表（offset/duration 已转换为秒）
    """
    log.info(f"TTS 合成（带时间戳）：{os.path.basename(out_path)}（{len(text)} 字）")
    return asyncio.run(_tts_with_words_async(text, out_path))


def words_to_sentences(words: list, text: str) -> list:
    """
    将 edge-tts 词语边界列表映射为逐句时间段。

    算法：
        1. 按中文句末标点切分句子
        2. 逐词标记其在原文中的字符起始位置
        3. 将各词分配到所属句子，统计每句的 [start, end] 时间

    参数：
        words: edge-tts WordBoundary 列表
        text:  原始台本文本

    返回：
        [{"text": str, "start": float, "end": float}, ...]
    """
    # ── 切分句子（保留标点） ──
    sent_texts = [
        s.strip()
        for s in re.split(r'(?<=[。！？…,，.!?])', text)
        if s.strip()
    ]
    if not sent_texts:
        sent_texts = [text.strip()]

    # ── 无时间戳降级：按字数等比估算 ──
    if not words:
        log.warning("edge-tts 未返回时间戳，使用字数比例估算字幕时间")
        total_chars = max(sum(len(s) for s in sent_texts), 1)
        est_total   = len(text) * 0.15          # ≈ 150ms/字
        t = 0.0
        result = []
        for s in sent_texts:
            dur = est_total * len(s) / total_chars
            result.append({"text": s, "start": t, "end": t + dur})
            t += dur
        return result

    # ── 为每个词标记其在原文中的字符起始位置 ──
    search_pos = 0
    for w in words:
        idx = text.find(w["text"], search_pos)
        if idx != -1:
            w["char_start"] = idx
            search_pos = idx + len(w["text"])
        else:
            w["char_start"] = search_pos   # 找不到时记当前扫描位置

    # ── 确定每个句子在原文中的字符范围 ──
    sent_char_ranges = []
    pos = 0
    for s in sent_texts:
        core = s.rstrip("。！？…,，.!? ")     # 去末尾标点后在原文中定位
        idx  = text.find(core, pos) if core else pos
        if idx == -1:
            idx = pos
        end = idx + len(s)
        sent_char_ranges.append((idx, end))
        pos = end

    # ── 将词分配到各句子，统计时间范围 ──
    result = []
    for (s_start, s_end), s_text in zip(sent_char_ranges, sent_texts):
        sw = [w for w in words if s_start <= w.get("char_start", 0) < s_end]
        if sw:
            t_start = sw[0]["offset"]
            t_end   = sw[-1]["offset"] + sw[-1]["duration"]
        elif result:
            t_start = result[-1]["end"]
            t_end   = t_start + max(1.0, len(s_text) * 0.12)
        else:
            t_start = 0.0
            t_end   = max(1.0, len(s_text) * 0.12)
        result.append({"text": s_text, "start": t_start, "end": t_end})

    return result


# ════════════════════════════════════════════════════════════════════
# 4. 背景素材管理（Pexels 视频优先 → 图片 → 渐变色）
# ════════════════════════════════════════════════════════════════════

class AssetsManager:
    """
    负责获取视频背景素材。
    优先级：Pexels 视频 → Pexels 图片（Ken Burns） → 渐变色兜底
    """

    def __init__(self):
        self.api_key = os.getenv("PEXELS_API_KEY", "")

    # ── 公开接口 ──────────────────────────────────────────────────

    def get_background_video(self, keywords: list, download_dir: str) -> Optional[str]:
        """
        尝试从 Pexels 视频接口下载竖屏背景视频。

        参数：
            keywords:     搜索关键词列表
            download_dir: 视频文件保存目录（临时目录）

        返回：
            本地视频文件路径；若获取失败返回 None
        """
        if not self.api_key:
            log.info("未配置 PEXELS_API_KEY，跳过视频素材获取")
            return None
        try:
            return self._fetch_video_from_pexels(keywords, download_dir)
        except Exception as e:
            log.warning(f"Pexels 视频获取失败：{e}，降级使用图片")
            return None

    def get_background_image(self, keywords: list) -> Image.Image:
        """
        获取背景图片（Pexels 图片 → 渐变色兜底）。

        返回：
            VIDEO_WIDTH x VIDEO_HEIGHT 的 PIL RGB Image
        """
        if self.api_key:
            try:
                return self._fetch_image_from_pexels(keywords)
            except Exception as e:
                log.warning(f"Pexels 图片获取失败：{e}，使用渐变色兜底")
        else:
            log.info("使用渐变色背景（未配置 PEXELS_API_KEY）")
        return self._make_gradient_background()

    # ── 内部实现 ─────────────────────────────────────────────────

    def _fetch_video_from_pexels(self, keywords: list, download_dir: str) -> str:
        """
        调用 Pexels Video Search API，下载竖屏背景视频。
        优先选取竖屏（height > width）且最接近 1080p 的文件。
        """
        query   = " ".join(keywords[:3])
        headers = {"Authorization": self.api_key}
        params  = {
            "query":       query,
            "orientation": "portrait",
            "per_page":    5,
            "size":        "medium",
        }
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers, params=params, timeout=15,
        )
        resp.raise_for_status()
        videos = resp.json().get("videos", [])

        if not videos:
            raise ValueError(f"Pexels 视频搜索 '{query}' 无结果")

        for video in videos:
            files = video.get("video_files", [])

            # 筛选竖屏 MP4 文件（height > width）
            portrait = [
                f for f in files
                if f.get("height", 0) > f.get("width", 0)
                and "mp4" in f.get("file_type", "").lower()
            ]
            candidates = portrait if portrait else files   # 无竖屏则接受横屏

            # 选最接近 VIDEO_WIDTH 宽度的文件
            candidates.sort(key=lambda f: abs(f.get("width", 0) - VIDEO_WIDTH))
            best     = candidates[0]
            vid_url  = best["link"]

            log.info(
                f"下载 Pexels 视频（{best.get('width')}x{best.get('height')}，"
                f"关键词：{query}）"
            )
            vid_path = os.path.join(download_dir, "bg_video.mp4")

            r = requests.get(vid_url, timeout=120, stream=True)
            r.raise_for_status()
            with open(vid_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)

            log.info(f"视频下载完成：{vid_path}")
            return vid_path

        raise ValueError("未找到可用的视频文件")

    def _fetch_image_from_pexels(self, keywords: list) -> Image.Image:
        """调用 Pexels Photo Search API，下载竖屏背景图。"""
        query   = " ".join(keywords[:3])
        headers = {"Authorization": self.api_key}
        params  = {"query": query, "orientation": "portrait", "size": "large", "per_page": 5}
        resp    = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers, params=params, timeout=10,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            raise ValueError(f"Pexels 图片搜索 '{query}' 无结果")

        img_url  = photos[0]["src"].get("portrait") or photos[0]["src"]["large"]
        log.info(f"下载 Pexels 背景图（关键词：{query}）")
        img_data = requests.get(img_url, timeout=30)
        img_data.raise_for_status()

        img = Image.open(BytesIO(img_data.content)).convert("RGB")
        return smart_crop_portrait(img)

    def _make_gradient_background(self) -> Image.Image:
        """生成深蓝→深紫渐变色兜底背景。"""
        img  = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT))
        draw = ImageDraw.Draw(img)
        top, bottom = (15, 23, 42), (30, 10, 60)
        for y in range(VIDEO_HEIGHT):
            t = y / VIDEO_HEIGHT
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))
        return img


# ════════════════════════════════════════════════════════════════════
# 5. 图像工具函数
# ════════════════════════════════════════════════════════════════════

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """
    按优先级加载字体：FONT_PATH 全局变量 → 系统中文字体 → PIL 默认字体。

    参数：
        size: 字体大小（像素）
    """
    if FONT_PATH and os.path.exists(FONT_PATH):
        return ImageFont.truetype(FONT_PATH, size)

    system_fonts = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ]
    for path in system_fonts:
        if os.path.exists(path):
            log.info(f"自动检测到系统中文字体：{path}")
            return ImageFont.truetype(path, size)

    log.warning("未找到中文字体，中文可能显示为方框。请设置全局变量 FONT_PATH。")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont,
               max_width: int, draw: ImageDraw.Draw) -> list:
    """
    按像素宽度将文本自动折行。

    返回：
        折行后的字符串列表
    """
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            test = current + char
            w    = draw.textbbox((0, 0), test, font=font)[2]
            if w <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines


def smart_crop_portrait(img: Image.Image) -> Image.Image:
    """
    将任意尺寸图片等比缩放并居中裁剪为 VIDEO_WIDTH x VIDEO_HEIGHT。
    策略：缩放到能完全填满目标区域（cover），再裁去多余部分。
    """
    w, h  = img.size
    scale = max(VIDEO_WIDTH / w, VIDEO_HEIGHT / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left    = (new_w - VIDEO_WIDTH)  // 2
    top     = (new_h - VIDEO_HEIGHT) // 2
    return resized.crop((left, top, left + VIDEO_WIDTH, top + VIDEO_HEIGHT))


def apply_ken_burns(img_np: np.ndarray, t: float, duration: float) -> np.ndarray:
    """
    对静态背景图应用 Ken Burns 缩放动效（逐渐放大 100% → 108%）。

    参数：
        img_np:   shape (VIDEO_HEIGHT, VIDEO_WIDTH, 3) 的背景图 numpy 数组
        t:        当前时刻（秒）
        duration: 当前片段总时长（秒）

    返回：
        shape (VIDEO_HEIGHT, VIDEO_WIDTH, 3) uint8 numpy 数组
    """
    ZOOM_END = 1.08
    progress = min(t / max(duration, 0.001), 1.0)
    zoom     = 1.0 + (ZOOM_END - 1.0) * progress

    crop_w = int(VIDEO_WIDTH  / zoom)
    crop_h = int(VIDEO_HEIGHT / zoom)
    left   = (VIDEO_WIDTH  - crop_w) // 2
    top    = (VIDEO_HEIGHT - crop_h) // 2

    cropped = img_np[top : top + crop_h, left : left + crop_w]
    return np.array(
        Image.fromarray(cropped).resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.BILINEAR)
    )


def composite_overlays(bg_np: np.ndarray, overlays: list) -> np.ndarray:
    """
    将多个 RGBA 叠加层依次 alpha 合成到 RGB 背景帧上。

    参数：
        bg_np:    (H, W, 3) uint8 背景帧
        overlays: list of (H, W, 4) uint8 RGBA 叠加层

    返回：
        (H, W, 3) uint8 合成结果
    """
    result = bg_np.astype(np.float32)
    for ov in overlays:
        alpha  = ov[:, :, 3:4].astype(np.float32) / 255.0
        rgb    = ov[:, :, :3 ].astype(np.float32)
        result = result * (1.0 - alpha) + rgb * alpha
    return np.clip(result, 0, 255).astype(np.uint8)


# ════════════════════════════════════════════════════════════════════
# 6. 预渲染叠加层（RGBA numpy 数组，一次生成，多帧复用）
# ════════════════════════════════════════════════════════════════════

def pre_render_dark_overlay(opacity: int = 120) -> np.ndarray:
    """
    预渲染半透明黑色暗化层（RGBA）。
    覆盖在背景上让文字更清晰。
    """
    ov = np.zeros((VIDEO_HEIGHT, VIDEO_WIDTH, 4), dtype=np.uint8)
    ov[:, :, 3] = opacity
    return ov


def pre_render_title_overlay(title: str, is_cover: bool) -> np.ndarray:
    """
    预渲染标题叠加层（RGBA）。

    参数：
        title:    简报标题文字
        is_cover: True=封面/结束帧（大字居中）；False=内容帧（小字置顶）

    返回：
        (VIDEO_HEIGHT, VIDEO_WIDTH, 4) uint8 RGBA numpy 数组
    """
    canvas = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)
    padding = 70
    max_w   = VIDEO_WIDTH - padding * 2

    if is_cover:
        font_title = _load_font(64)
        font_sub   = _load_font(40)
        lines  = _wrap_text(title, font_title, max_w, draw)
        line_h = 84
        total_h = len(lines) * line_h
        y = (VIDEO_HEIGHT - total_h) // 3

        for line in lines:
            lw = draw.textbbox((0, 0), line, font=font_title)[2]
            x  = (VIDEO_WIDTH - lw) // 2
            draw.text((x + 3, y + 3), line, font=font_title, fill=(0, 0, 0, 160))    # 阴影
            draw.text((x,     y    ), line, font=font_title, fill=(255, 255, 255, 255))
            y += line_h

        subtitle = "今日科技简报"
        sw = draw.textbbox((0, 0), subtitle, font=font_sub)[2]
        draw.text(
            ((VIDEO_WIDTH - sw) // 2, y + 50),
            subtitle,
            font=font_sub,
            fill=(160, 200, 255, 220),
        )
    else:
        font_small = _load_font(38)
        lines = _wrap_text(title, font_small, max_w, draw)
        y = 90
        for line in lines:
            draw.text((padding, y), line, font=font_small, fill=(150, 185, 255, 200))
            y += 52
        y += 12
        draw.line(
            [(padding, y), (VIDEO_WIDTH - padding, y)],
            fill=(255, 255, 255, 70),
            width=2,
        )

    return np.array(canvas)


def pre_render_subtitle_overlay(text: str) -> np.ndarray:
    """
    预渲染单句字幕叠加层（RGBA）。

    样式：
        - 画面底部居中
        - 半透明黑色底条（增强对比度）
        - 黄色文字 + 黑色阴影

    参数：
        text: 字幕句子文本

    返回：
        (VIDEO_HEIGHT, VIDEO_WIDTH, 4) uint8 RGBA numpy 数组
    """
    canvas   = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw     = ImageDraw.Draw(canvas)
    font_sub = _load_font(52)
    padding  = 60
    max_w    = VIDEO_WIDTH - padding * 2
    line_h   = 72

    lines   = _wrap_text(text, font_sub, max_w, draw)
    total_h = len(lines) * line_h + 40

    # 底部背景条
    bar_top = VIDEO_HEIGHT - total_h - 80
    draw.rectangle(
        [(0, bar_top - 20), (VIDEO_WIDTH, VIDEO_HEIGHT - 50)],
        fill=(0, 0, 0, 180),
    )

    # 字幕文字（黄色高亮 + 黑色阴影）
    y = bar_top
    for line in lines:
        lw = draw.textbbox((0, 0), line, font=font_sub)[2]
        x  = (VIDEO_WIDTH - lw) // 2
        draw.text((x + 2, y + 2), line, font=font_sub, fill=(0,   0,   0,   200))  # 阴影
        draw.text((x,     y    ), line, font=font_sub, fill=(255, 230, 0,   255))  # 黄色
        y += line_h

    return np.array(canvas)


# ════════════════════════════════════════════════════════════════════
# 7. 动态字幕视频片段合成
# ════════════════════════════════════════════════════════════════════

def create_dynamic_segment(
    bg_video_clip,                      # MoviePy VideoFileClip 或 None
    bg_image_np:      Optional[np.ndarray],  # (H,W,3) numpy 或 None
    dark_overlay:     np.ndarray,       # 预渲染暗化层 (H,W,4)
    title_overlay:    np.ndarray,       # 预渲染标题层 (H,W,4)
    subtitle_overlays: dict,            # {句子文本: (H,W,4) numpy}
    sentences:        list,             # [{text, start, end}]
    audio_path:       str,
) -> VideoClip:
    """
    创建一个带逐句同步字幕的动态 VideoClip。

    核心逻辑：
        - 视频背景：用取模运算实现无缝循环，避免多次开文件
        - 图片背景：应用 Ken Burns 缩放动效
        - 字幕：在对应时间段显示预渲染的字幕叠加层（黄色高亮当前句）

    参数：
        bg_video_clip:     背景视频 Clip（可为 None）
        bg_image_np:       背景图片 numpy 数组（bg_video_clip 为 None 时使用）
        dark_overlay:      暗化叠加层
        title_overlay:     标题叠加层
        subtitle_overlays: 各句子字幕叠加层字典
        sentences:         句子时间段列表
        audio_path:        对应语音 MP3 文件路径

    返回：
        带音频的 MoviePy VideoClip
    """
    audio    = AudioFileClip(audio_path)
    duration = audio.duration

    def make_frame(t: float) -> np.ndarray:
        # ── 1. 获取背景帧 ──
        if bg_video_clip is not None:
            # 取模循环播放（避免超出视频时长）
            vid_t = t % max(bg_video_clip.duration - 0.001, 0.001)
            raw   = bg_video_clip.get_frame(vid_t)
            bg    = np.array(smart_crop_portrait(Image.fromarray(raw.astype(np.uint8))))
        else:
            bg = apply_ken_burns(bg_image_np, t, duration)

        # ── 2. 查找当前应显示的字幕句子 ──
        current_text = None
        for sent in sentences:
            if sent["start"] <= t < sent["end"]:
                current_text = sent["text"]
                break
        # 最后一句结束后继续显示（防止结尾出现空字幕区）
        if current_text is None and sentences and t >= sentences[-1]["start"]:
            current_text = sentences[-1]["text"]

        # ── 3. 合成叠加层 ──
        layers = [dark_overlay, title_overlay]
        if current_text and current_text in subtitle_overlays:
            layers.append(subtitle_overlays[current_text])

        return composite_overlays(bg, layers)

    clip = VideoClip(make_frame, duration=duration).with_audio(audio)
    return clip


# ════════════════════════════════════════════════════════════════════
# 8. 主流程编排
# ════════════════════════════════════════════════════════════════════

def main():
    """
    主入口：解析简报 → 获取背景素材 → 逐段生成 TTS+字幕 → 合成导出 MP4。
    输出至 output/videos/Daily_Brief_YYYYMMDD.mp4
    """
    log.info("=" * 60)
    log.info("  视频生成启动（逐句字幕 + Pexels 视频背景）")
    log.info("=" * 60)

    # ── Step 1：解析简报 ──
    brief_path = get_latest_brief()
    brief  = parse_brief(brief_path)
    title  = brief["title"]
    points = brief["points"]

    # ── Step 2：提取搜索关键词 ──
    keywords = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]+", title)[:4]
    if not keywords:
        keywords = ["technology", "news"]

    # ── Step 3：准备输出目录 ──
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_str    = datetime.date.today().strftime("%Y%m%d")
    output_path = os.path.join(OUTPUT_DIR, f"Daily_Brief_{date_str}.mp4")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        log.info(f"临时工作目录：{tmpdir}")

        assets = AssetsManager()

        # ── Step 4：获取背景素材 ──
        bg_video_path = assets.get_background_video(keywords, tmpdir)
        bg_video_clip = None
        bg_image_np   = None

        if bg_video_path:
            try:
                bg_video_clip = VideoFileClip(bg_video_path)
                log.info(
                    f"视频背景已加载：{bg_video_clip.duration:.1f}s "
                    f"（{bg_video_clip.w}x{bg_video_clip.h}）"
                )
            except Exception as e:
                log.warning(f"加载背景视频失败：{e}，降级使用图片")
                bg_video_clip = None

        if bg_video_clip is None:
            bg_pil      = assets.get_background_image(keywords)
            bg_image_np = np.array(bg_pil)

        # ── Step 5：预渲染公共叠加层 ──
        dark_overlay = pre_render_dark_overlay(opacity=120)

        # ── Step 6：定义各段台本 ──
        intro_text = "今天的科技简报来了！共三条要点，我们来看看。"
        outro_text = "以上就是今天的科技简报，觉得有用的话别忘了点赞收藏，我们明天见！"

        segment_defs = [
            {"text": intro_text, "is_cover": True,  "tag": "intro"},
        ]
        for i, point in enumerate(points, start=1):
            spoken = rewrite_for_spoken(point["header"], point["body"])
            segment_defs.append({
                "text":     spoken,
                "is_cover": False,
                "tag":      f"point_{i}",
            })
        segment_defs.append({"text": outro_text, "is_cover": True, "tag": "outro"})

        # ── Step 7：逐段生成字幕同步视频片段 ──
        segments = []
        for seg_def in segment_defs:
            tag      = seg_def["tag"]
            text     = seg_def["text"]
            is_cover = seg_def["is_cover"]

            audio_path = os.path.join(tmpdir, f"seg_{tag}.mp3")

            # TTS 合成 + 词语边界时间戳
            words     = generate_tts_with_words(text, audio_path)
            sentences = words_to_sentences(words, text)

            time_info = " ".join(
                f"[{s['start']:.2f}-{s['end']:.2f}]" for s in sentences
            )
            log.info(f"  [{tag}] {len(sentences)} 句字幕 | {time_info}")

            # 预渲染本段标题叠加层 + 各句字幕叠加层
            title_overlay     = pre_render_title_overlay(title, is_cover)
            subtitle_overlays = {
                s["text"]: pre_render_subtitle_overlay(s["text"])
                for s in sentences
            }

            seg = create_dynamic_segment(
                bg_video_clip     = bg_video_clip,
                bg_image_np       = bg_image_np,
                dark_overlay      = dark_overlay,
                title_overlay     = title_overlay,
                subtitle_overlays = subtitle_overlays,
                sentences         = sentences,
                audio_path        = audio_path,
            )
            segments.append(seg)
            log.info(f"  [{tag}] 片段完成（{seg.duration:.1f}s）")

        # ── Step 8：拼接并导出最终 MP4 ──
        log.info("合成视频中，请稍候…")
        final = concatenate_videoclips(segments, method="compose")
        final.write_videofile(
            output_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=os.path.join(tmpdir, "tmp_audio.m4a"),
            remove_temp=True,
            logger="bar",
        )
        total_dur = final.duration

        # 显式释放所有 Clip（Windows 下释放文件锁）
        for seg in segments:
            try: seg.close()
            except Exception: pass
        if bg_video_clip:
            try: bg_video_clip.close()
            except Exception: pass
        try: final.close()
        except Exception: pass

    log.info("=" * 60)
    log.info(f"  视频已生成：{output_path}")
    log.info(f"  总时长：{total_dur:.1f} 秒")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
