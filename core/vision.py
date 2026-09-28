# -*- coding: utf-8 -*-
"""视觉层：窗口截图、资金 OCR（可选）、校准截图导出。

资金读取优先用 tesseract(pytesseract) OCR。若未安装 tesseract 引擎或未校准，
默认资金区域配置不存在时返回 -1（表示“未知/未校准”），大脑据此采取保守策略
（资金未知时不盲目花大钱）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

from PIL import Image

from . import winio

# 默认资金读取区域：以窗口宽高归一化(0..1) 左上角 + 宽/高。
DEFAULT_MONEY_REGION = {"left": 0.62, "top": 0.02, "width": 0.34, "height": 0.07}


def capture_game(hwnd: int) -> Optional[Image.Image]:
    return winio.capture_window(hwnd)


def crop_region(img: Image.Image, region: Dict[str, float]) -> Image.Image:
    """按归一化区域裁切。region: {left,top,width,height} 各为 0..1 比例。"""
    w, h = img.size
    left = int(region.get("left", 0) * w)
    top = int(region.get("top", 0) * h)
    rw = int(region.get("width", 0.2) * w)
    rh = int(region.get("height", 0.1) * h)
    return img.crop((max(left, 0), max(top, 0), min(left + rw, w), min(top + rh, h)))


# 全局缓存：tesseract 是否可用，避免每次反复尝试并打印 stderr 噪音
_OCR_AVAILABLE = None


def _ensure_ocr() -> bool:
    """返回 tesseract 是否可用；首次调用时尝试导入 pytesseract 并缓存结果。"""
    import sys
    global _OCR_AVAILABLE
    if "pytesseract" not in sys.modules:
        try:
            import pytesseract
        except Exception:
            _OCR_AVAILABLE = False
            return False
    if _OCR_AVAILABLE is None:
        import io as _io
        import contextlib
        try:
            pytesseract = sys.modules["pytesseract"]
            with contextlib.redirect_stderr(_io.StringIO()):
                pytesseract.get_tesseract_version()  # 不抛则视为可用
            _OCR_AVAILABLE = True
        except Exception:
            _OCR_AVAILABLE = False
    return _OCR_AVAILABLE


def read_money(img: Image.Image, region: Optional[Dict[str, float]] = None,
               logger=None) -> int:
    """从游戏截图中读取资金数字。返回 int；无法可靠读取时返回 -1。

    - region 为空则用默认右上角区域（未校准可先试默认）。
    - 依赖 tesseract；未安装或读取失败返回 -1。
    """
    if not _ensure_ocr():
        return -1
    import sys
    pytesseract = sys.modules["pytesseract"]
    try:
        import io as _io
        import contextlib
        crop = crop_region(img, region or DEFAULT_MONEY_REGION)
        crop = crop.convert("L").resize((crop.width * 3, crop.height * 3))  # 放大便于识别
        with contextlib.redirect_stderr(_io.StringIO()):
            text = pytesseract.image_to_string(
                crop, config="--psm 7 -c tessedit_char_whitelist=0123456789$")
    except Exception as e:
        if logger:
            logger.warning("OCR 读取资金失败: %s", e)
        return -1

    digits = re.sub(r"[^\d]", "", text or "")
    if digits:
        try:
            return int(digits.replace("$", ""))
        except ValueError:
            return -1
    return -1


def save_calibration(img: Image.Image, data_dir: Path, tag: str = "") -> str:
    """把当前游戏截图保存到 data_dir，供人工校准模板/坐标。返回保存路径。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    name = "calib_%s%s.png" % (tag, os.urandom(3).hex()[:4]) if tag else \
        "calib_%s.png" % os.urandom(3).hex()[:4]
    path = data_dir / name
    img.save(path)
    return str(path)


# 常见目标在画面中的粗略主色调（辅助归正/验证，不作为主依赖）：
#   pink_key = 粉红史莱姆；plort_gold = 金色结晶（售出价值主色）等。
# 以 (min_r,min_g,min_b)-(max_r,max_g,max_b) 的通道范围近似。实际可后续按实测图微调。
TARGET_COLORS = {
    "pink_slime": ((235, 120, 170), (255, 215, 255)),    # 粉红史莱姆体色
    "pink_plort": ((250, 190, 235), (255, 235, 255)),    # 粉红结晶
    "gold_plort": ((250, 200, 90), (255, 240, 150)),     # 金色结晶/高价结晶
}


# 画面检测用的关键归一化区域(0..1)：
#   MOVE_REGION  = 画面中央偏下，用于判断人物是否真的在移动(避开 HUD/天空)。
#   HUD_REGION   = 右下角真空背包/结晶计数区，用于判断吸附后物品栏是否真的变化(是否抓到东西)。
MOVE_REGION = {"left": 0.15, "top": 0.20, "width": 0.70, "height": 0.50}
HUD_REGION = {"left": 0.62, "top": 0.78, "width": 0.36, "height": 0.20}


def frame_diff(img1: Image.Image, img2: Image.Image, region: Optional[Dict[str, float]] = None,
               sample: int = 2, threshold: int = 14) -> float:
    """两帧灰度差的占比(0..1)。

    - region 指定只看某个区域(移动区/物品栏区)；None 则看全图。
    - 返回"变化像素占比"。经验值：>0.02 视为画面有明显变化(人物移动/物体/数字变化)；
      <0.01 基本没动(失焦/被墙挡/动作没生效)。
    - 作用：让 NEKO 用"眼睛"确认真实动作真的发生，而不是盲信汇报。
    """
    a = img1.convert("L")
    b = img2.convert("L")
    if a.size != b.size:
        return 0.0
    if region:
        a = crop_region(a, region)
        b = crop_region(b, region)
    w, h = a.size
    if w <= 0 or h <= 0:
        return 0.0
    changed = seen = 0
    for yy in range(0, h, sample):
        for xx in range(0, w, sample):
            seen += 1
            if abs(a.getpixel((xx, yy)) - b.getpixel((xx, yy))) > threshold:
                changed += 1
    return changed / max(1, seen)


def movement_fraction(img1: Image.Image | None, img2: Image.Image | None,
                      region: Optional[Dict[str, float]] = None,
                      min_px: int = 8) -> Optional[float]:
    """判定"这帧 vs 上一帧"人物是否真的动了。

    返回变化占比；任一帧缺失返回 None。调用方可按 may_moved(>=0.02) 判断。
    region 默认 MOVE_REGION(只看画面中央)，避免把 HUD/边缘噪声算进来。
    """
    if img1 is None or img2 is None:
        return None
    try:
        return frame_diff(img1, img2, region or MOVE_REGION, sample=2)
    except Exception:
        return None


def locate_target(img: Image.Image, color: str = "pink_slime") -> Optional[list]:
    """在截图里按颜色阈值找目标质心，用于画面的转向辅助归正/结果验证。

    返回 [nx, ny]（0..1 归一化），找不到返回 None。
    只做简单逐像素匹配，量级不大；作为 mod yaw 反馈的补充而非主依赖。
    """
    lo, hi = TARGET_COLORS.get(color, TARGET_COLORS["pink_slime"])
    rgb = img.convert("RGB")
    w, h = rgb.size
    if w <= 0 or h <= 0:
        return None
    r0, g0, b0 = lo
    r1, g1, b1 = hi
    sx = sy = n = 0
    # 隔行采样加速；只需较大概略质心
    for yy in range(0, h, 2):
        for xx in range(0, w, 2):
            r, g, b = rgb.getpixel((xx, yy))
            if r0 <= r <= r1 and g0 <= g <= g1 and b0 <= b <= b1:
                sx += xx; sy += yy; n += 1
    if n < 25:  # 过少像素视为噪音
        return None
    return [sx / n / w, sy / n / h]