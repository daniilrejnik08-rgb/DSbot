"""Тёмные неоновые карточки для ежедневных наград и мини-игр (Pillow)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False
    ImageFont = None  # type: ignore

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Визуальные «конфеты» на карточке; реальные монеты задаются в economy
DAILY_VISUAL_CANDIES = [20, 35, 55, 80, 120, 180, 250]


def _font(size: int) -> Any:
    if not _HAS_PIL or ImageFont is None:
        raise RuntimeError("Pillow required")
    for path in (
        _FONT_DIR / "NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_daily_rewards_png(
    *,
    tier_next: int,
    rewards_visual: list[int] | None = None,
) -> bytes:
    """
    Панель «Ежедневная награда» — 7 дней, без посторонних брендов.
    tier_next: какой день сейчас «текущий» (1–7) — подсветка; дни < tier_next — пройдены; > — замок.
    """
    if not _HAS_PIL:
        raise RuntimeError("Pillow required")
    rv = rewards_visual or DAILY_VISUAL_CANDIES
    W, H = 920, 400
    bg = (18, 19, 24)
    card_on = (42, 46, 58)
    card_done = (32, 36, 46)
    card_lock = (22, 24, 30)
    accent = (120, 180, 255)
    accent_dim = (90, 140, 210)
    text_hi = (220, 230, 250)
    text_mid = (160, 175, 200)
    text_dim = (110, 120, 140)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    f_title = _font(24)
    f_sm = _font(14)
    f_md = _font(16)
    f_lg = _font(20)
    f_xl = _font(22)

    title = "Ежедневная награда"
    tb = draw.textbbox((0, 0), title, font=f_title)
    tw = tb[2] - tb[0]
    draw.text(((W - tw) // 2, 22), title, fill=text_mid, font=f_title)

    n = 7
    margin = 36
    gap = 10
    cw = (W - 2 * margin - (n - 1) * gap) // n
    ch = 168
    top = 72
    rad = 18

    for d in range(1, n + 1):
        x = margin + (d - 1) * (cw + gap)
        y = top
        done = d < tier_next
        active = d == tier_next
        locked = d > tier_next

        if locked:
            fill = card_lock
            outline = (50, 55, 65)
        elif done:
            fill = card_done
            outline = (70, 110, 160)
        else:
            fill = card_on
            outline = accent

        wline = 3 if active else 1
        draw.rounded_rectangle((x, y, x + cw, y + ch), radius=rad, fill=fill, outline=outline, width=wline)

        candy_amt = rv[d - 1] if d <= len(rv) else 0
        if locked:
            lock_x = x + cw // 2 - 18
            lock_y = y + 58
            draw.text((lock_x, lock_y), "🔒", font=_font(28))
        elif done:
            draw.text((x + 10, y + 10), "Награда", fill=text_dim, font=f_sm)
            draw.text((x + cw // 2 - 14, y + 58), "✓", fill=accent_dim, font=_font(26))
            draw.text((x + 10, y + 100), f"{candy_amt} конфет", fill=text_dim, font=f_md)
        else:
            draw.text((x + 10, y + 10), "Награда", fill=text_dim, font=f_sm)
            draw.text((x + cw // 2 - 16, y + 50), "🍬", font=_font(34))
            draw.text((x + 10, y + 100), f"{candy_amt} конфет", fill=accent, font=f_md)

        day_lbl = f"{d} день"
        db = draw.textbbox((0, 0), day_lbl, font=f_lg)
        dw = db[2] - db[0]
        col = text_hi if active else text_dim
        draw.text((x + (cw - dw) // 2, y + ch - 36), day_lbl, fill=col, font=f_lg if active else f_md)

    bar_y = top + ch + 28
    draw.line((margin, bar_y, W - margin, bar_y), fill=(55, 62, 78), width=3)
    for d in range(1, n + 1):
        cx = margin + (d - 1) * (cw + gap) + cw // 2
        r = 7
        if d < tier_next:
            fill_dot = accent_dim
        elif d == tier_next:
            fill_dot = accent
        else:
            fill_dot = (45, 50, 62)
        draw.ellipse((cx - r, bar_y - r, cx + r, bar_y + r), fill=fill_dot, outline=accent if d == tier_next else None)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_arcade_result_png(
    *,
    title: str,
    headline: str,
    detail: str = "",
    footer: str = "",
    accent_rgb: tuple[int, int, int] = (120, 180, 255),
) -> bytes:
    """Универсальная карточка результата игры (тёмный неон)."""
    if not _HAS_PIL:
        raise RuntimeError("Pillow required")
    W, H = 720, 280
    bg = (14, 15, 20)
    panel = (28, 30, 40)
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    f_t = _font(22)
    f_h = _font(26)
    f_d = _font(17)
    f_f = _font(14)

    pad = 28
    draw.rounded_rectangle((pad, pad, W - pad, H - pad), radius=20, fill=panel, outline=accent_rgb, width=2)

    draw.text((pad + 22, pad + 20), title, fill=accent_rgb, font=f_t)
    hb = draw.textbbox((0, 0), headline, font=f_h)
    hw = hb[2] - hb[0]
    draw.text(((W - hw) // 2, pad + 70), headline, fill=(235, 240, 255), font=f_h)
    if detail:
        db = draw.textbbox((0, 0), detail, font=f_d)
        dw = db[2] - db[0]
        draw.text(((W - dw) // 2, pad + 118), detail, fill=(170, 185, 210), font=f_d)
    if footer:
        fb = draw.textbbox((0, 0), footer, font=f_f)
        fw = fb[2] - fb[0]
        draw.text(((W - fw) // 2, H - pad - 36), footer, fill=(120, 135, 160), font=f_f)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def has_pillow() -> bool:
    return _HAS_PIL
