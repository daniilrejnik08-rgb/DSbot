"""Тёмные неоновые карточки для ежедневных наград и мини-игр (Pillow)."""

from __future__ import annotations

import io
import math
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


def _clamp(v: int) -> int:
    return 0 if v < 0 else 255 if v > 255 else v


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (
        _clamp(int(a[0] + (b[0] - a[0]) * t)),
        _clamp(int(a[1] + (b[1] - a[1]) * t)),
        _clamp(int(a[2] + (b[2] - a[2]) * t)),
    )


def _draw_vignette(img: "Image.Image", *, strength: float = 0.22) -> None:
    """Лёгкая виньетка, чтобы фон выглядел глубже (без альфы)."""
    w, h = img.size
    cx, cy = w / 2.0, h / 2.0
    maxd = math.hypot(cx, cy)
    px = img.load()
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy) / maxd
            k = strength * (d**1.7)
            r, g, b = px[x, y]
            px[x, y] = (_clamp(int(r * (1 - k))), _clamp(int(g * (1 - k))), _clamp(int(b * (1 - k))))


def _draw_lock(draw: "ImageDraw.ImageDraw", cx: int, cy: int, *, size: int, color: tuple[int, int, int]) -> None:
    """Простой замок из примитивов (без эмодзи)."""
    bw = int(size * 0.62)
    bh = int(size * 0.52)
    x0 = cx - bw // 2
    y0 = cy - bh // 2 + int(size * 0.15)
    x1 = x0 + bw
    y1 = y0 + bh
    rad = int(size * 0.14)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=rad, outline=color, width=max(2, size // 10))
    sh_w = int(bw * 0.62)
    sh_h = int(size * 0.40)
    sx0 = cx - sh_w // 2
    sy0 = y0 - sh_h + int(size * 0.08)
    sx1 = sx0 + sh_w
    sy1 = y0 + int(size * 0.10)
    draw.arc((sx0, sy0, sx1, sy1), start=200, end=-20, fill=color, width=max(2, size // 10))
    draw.ellipse((cx - 3, cy + 5, cx + 3, cy + 11), outline=color, width=2)


def _draw_check(draw: "ImageDraw.ImageDraw", cx: int, cy: int, *, size: int, color: tuple[int, int, int]) -> None:
    w = size
    pts = [
        (cx - int(w * 0.35), cy + int(w * 0.00)),
        (cx - int(w * 0.10), cy + int(w * 0.25)),
        (cx + int(w * 0.38), cy - int(w * 0.28)),
    ]
    draw.line(pts, fill=color, width=max(3, size // 8), joint="curve")


def _draw_candy(draw: "ImageDraw.ImageDraw", cx: int, cy: int, *, size: int, color: tuple[int, int, int]) -> None:
    """Конфета-капсула + «ушки»."""
    w = int(size * 0.78)
    h = int(size * 0.46)
    x0, y0 = cx - w // 2, cy - h // 2
    x1, y1 = x0 + w, y0 + h
    rad = h // 2
    draw.rounded_rectangle((x0, y0, x1, y1), radius=rad, outline=color, width=max(2, size // 10))
    ear = int(size * 0.22)
    draw.polygon([(x0, cy), (x0 - ear, cy - ear // 2), (x0 - ear, cy + ear // 2)], outline=color)
    draw.polygon([(x1, cy), (x1 + ear, cy - ear // 2), (x1 + ear, cy + ear // 2)], outline=color)
    # полоска на конфете
    draw.line([(cx - int(w * 0.18), y0 + 2), (cx - int(w * 0.18), y1 - 2)], fill=_mix(color, (255, 255, 255), 0.25), width=2)


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
    _draw_vignette(img, strength=0.24)
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
            _draw_lock(draw, x + cw // 2, y + 84, size=44, color=text_dim)
        elif done:
            draw.text((x + 10, y + 10), "Награда", fill=text_dim, font=f_sm)
            _draw_check(draw, x + cw // 2, y + 78, size=42, color=accent_dim)
            draw.text((x + 10, y + 100), f"{candy_amt} конфет", fill=text_dim, font=f_md)
        else:
            draw.text((x + 10, y + 10), "Награда", fill=text_dim, font=f_sm)
            _draw_candy(draw, x + cw // 2, y + 78, size=50, color=accent)
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
    bg = (12, 13, 18)
    panel = (26, 28, 38)
    img = Image.new("RGB", (W, H), bg)
    _draw_vignette(img, strength=0.28)
    draw = ImageDraw.Draw(img)
    f_t = _font(22)
    f_h = _font(26)
    f_d = _font(17)
    f_f = _font(14)

    pad = 28
    draw.rounded_rectangle((pad, pad, W - pad, H - pad), radius=20, fill=panel, outline=accent_rgb, width=2)
    # акцентная полоска сверху
    draw.rounded_rectangle((pad, pad, W - pad, pad + 10), radius=10, fill=_mix(accent_rgb, (20, 22, 30), 0.35))

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


def render_crash_result_png(
    *,
    bet: int,
    crash_at: float,
    cashout: float,
    win: int | None,
) -> bytes:
    """Карточка Crash с мини-графиком."""
    if not _HAS_PIL:
        raise RuntimeError("Pillow required")

    ok = win is not None
    accent = (120, 220, 170) if ok else (235, 90, 110)
    W, H = 720, 320
    bg = (12, 13, 18)
    panel = (26, 28, 38)
    img = Image.new("RGB", (W, H), bg)
    _draw_vignette(img, strength=0.30)
    draw = ImageDraw.Draw(img)

    f_t = _font(22)
    f_h = _font(26)
    f_d = _font(16)
    f_f = _font(14)

    pad = 26
    draw.rounded_rectangle((pad, pad, W - pad, H - pad), radius=20, fill=panel, outline=accent, width=2)
    draw.rounded_rectangle((pad, pad, W - pad, pad + 10), radius=10, fill=_mix(accent, (20, 22, 30), 0.35))
    draw.text((pad + 22, pad + 18), "📉 Crash", fill=accent, font=f_t)

    headline = "Успешный кэшаут" if ok else "Краш"
    hb = draw.textbbox((0, 0), headline, font=f_h)
    draw.text(((W - (hb[2] - hb[0])) // 2, pad + 58), headline, fill=(235, 240, 255), font=f_h)

    # chart
    cx0, cy0 = pad + 44, pad + 122
    cx1, cy1 = W - pad - 44, H - pad - 68
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=14, outline=(60, 66, 82), width=2)

    max_m = max(crash_at, cashout, 1.0)
    max_m = min(max_m, 8.0)

    def _map_x(t: float) -> int:
        return int(cx0 + (cx1 - cx0) * t)

    def _map_y(m: float) -> int:
        # higher multiplier -> higher line (visually up)
        t = (m - 1.0) / (max_m - 1.0) if max_m > 1.0 else 0.0
        return int(cy1 - (cy1 - cy0) * (0.08 + 0.86 * t))

    # curve points (simple ease-out)
    pts: list[tuple[int, int]] = []
    for i in range(0, 60):
        t = i / 59.0
        m = 1.0 + (max_m - 1.0) * (t**1.6)
        pts.append((_map_x(t), _map_y(m)))
    draw.line(pts, fill=_mix(accent, (255, 255, 255), 0.12), width=3, joint="curve")

    # crash marker
    crash_t = min(1.0, max(0.0, (crash_at - 1.0) / (max_m - 1.0) if max_m > 1.0 else 0.0))
    x_cr = _map_x(crash_t)
    draw.line([(x_cr, cy0 + 10), (x_cr, cy1 - 10)], fill=(90, 100, 125), width=2)
    draw.text((x_cr - 18, cy0 - 18), f"{crash_at:.2f}×", fill=(170, 185, 210), font=f_f)

    # cashout marker
    cash_t = min(1.0, max(0.0, (cashout - 1.0) / (max_m - 1.0) if max_m > 1.0 else 0.0))
    x_ca = _map_x(cash_t)
    y_ca = _map_y(min(cashout, max_m))
    draw.ellipse((x_ca - 6, y_ca - 6, x_ca + 6, y_ca + 6), fill=accent, outline=(235, 240, 255))

    detail = f"Краш: **{crash_at:.2f}×**   Выход: **{cashout:.2f}×**"
    db = draw.textbbox((0, 0), detail.replace("**", ""), font=f_d)
    draw.text(((W - (db[2] - db[0])) // 2, H - pad - 116), detail.replace("**", ""), fill=(170, 185, 210), font=f_d)

    footer = f"Ставка {bet} 🪙"
    if ok:
        footer += f"  •  Выигрыш {win} 🪙"
    fb = draw.textbbox((0, 0), footer, font=f_f)
    draw.text(((W - (fb[2] - fb[0])) // 2, H - pad - 38), footer, fill=(120, 135, 160), font=f_f)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_slots_result_png(
    *,
    bet: int,
    symbols: list[str],
    mult: float,
    win: int,
) -> bytes:
    """Карточка слотов с «барабанами» (без эмодзи-зависимости)."""
    if not _HAS_PIL:
        raise RuntimeError("Pillow required")

    W, H = 760, 360
    bg = (12, 13, 18)
    panel = (26, 28, 38)
    img = Image.new("RGB", (W, H), bg)
    _draw_vignette(img, strength=0.30)
    draw = ImageDraw.Draw(img)

    ok = win > 0
    accent = (255, 210, 120) if ok else (140, 170, 220)
    outline = accent if ok else (70, 78, 96)

    f_t = _font(22)
    f_h = _font(28)
    f_s = _font(18)
    f_f = _font(14)

    pad = 26
    draw.rounded_rectangle((pad, pad, W - pad, H - pad), radius=22, fill=panel, outline=outline, width=2)
    draw.rounded_rectangle((pad, pad, W - pad, pad + 10), radius=10, fill=_mix(accent, (20, 22, 30), 0.35))
    draw.text((pad + 22, pad + 18), "🎰 Слоты", fill=accent, font=f_t)

    headline = f"Выигрыш ×{mult:g}" if ok else "Без совпадений"
    hb = draw.textbbox((0, 0), headline, font=f_h)
    draw.text(((W - (hb[2] - hb[0])) // 2, pad + 56), headline, fill=(235, 240, 255), font=f_h)

    # Symbol theme (labels + colors) — не зависит от emoji.
    theme: dict[str, tuple[str, tuple[int, int, int]]] = {
        "🍒": ("CHERRY", (235, 90, 110)),
        "🍋": ("LEMON", (255, 220, 120)),
        "🍊": ("ORANGE", (255, 165, 90)),
        "🍇": ("GRAPE", (160, 110, 255)),
        "💎": ("DIAMOND", (120, 200, 255)),
        "7️⃣": ("SEVEN", (255, 245, 210)),
        # на случай если список символов будет другим
        "?": ("?", (170, 185, 210)),
    }

    # reels area
    rx0, ry0 = pad + 56, pad + 118
    rx1, ry1 = W - pad - 56, H - pad - 72
    reel_gap = 18
    reel_w = (rx1 - rx0 - 2 * reel_gap) // 3
    reel_h = ry1 - ry0
    tile_h = int(reel_h * 0.28)
    tile_gap = int(reel_h * 0.05)

    # win detection for highlight
    a, b, c = (symbols + ["?"] * 3)[:3]
    uniq = len({a, b, c})
    hi = [False, False, False]
    if uniq == 1:
        hi = [True, True, True]
    elif uniq == 2:
        # highlight the matching pair
        if a == b:
            hi = [True, True, False]
        elif a == c:
            hi = [True, False, True]
        else:
            hi = [False, True, True]

    # Draw three reels with fake motion (top/bottom faded random)
    pool = list(theme.keys())
    for i, sym in enumerate([a, b, c]):
        x0 = rx0 + i * (reel_w + reel_gap)
        y0 = ry0
        x1 = x0 + reel_w
        y1 = y0 + reel_h
        draw.rounded_rectangle((x0, y0, x1, y1), radius=18, outline=(70, 78, 96), width=2, fill=(20, 22, 30))

        def draw_tile(center_y: int, s: str, *, alpha: float, highlight: bool) -> None:
            lab, col = theme.get(s, theme["?"])
            col2 = _mix(col, (255, 255, 255), 0.15)
            base = _mix((40, 44, 58), col, 0.10 if highlight else 0.04)
            base = _mix(base, (12, 13, 18), 1 - alpha)
            ox = 8
            ty0 = center_y - tile_h // 2
            ty1 = ty0 + tile_h
            draw.rounded_rectangle((x0 + ox, ty0, x1 - ox, ty1), radius=14, fill=base, outline=col if highlight else (60, 66, 82), width=2)
            # icon: diamond / 7 / fruit as simple shapes
            icx = (x0 + x1) // 2
            icy = center_y - 6
            if lab == "DIAMOND":
                r = 16
                draw.polygon([(icx, icy - r), (icx + r, icy), (icx, icy + r), (icx - r, icy)], outline=col2)
                draw.line([(icx - r, icy), (icx + r, icy)], fill=_mix(col2, (255, 255, 255), 0.25), width=2)
            elif lab == "SEVEN":
                draw.text((icx - 10, icy - 18), "7", fill=col2, font=_font(34))
            else:
                # fruit: circle + leaf
                r = 16
                draw.ellipse((icx - r, icy - r, icx + r, icy + r), outline=col2, width=3)
                draw.polygon([(icx, icy - r - 8), (icx + 10, icy - r), (icx - 6, icy - r + 2)], fill=_mix(col2, (255, 255, 255), 0.15))
            tb = draw.textbbox((0, 0), lab, font=f_s)
            draw.text((icx - (tb[2] - tb[0]) // 2, center_y + 20), lab, fill=_mix((170, 185, 210), col2, 0.25), font=f_s)

        top_sym = random.choice(pool)
        bot_sym = random.choice(pool)
        draw_tile(ry0 + tile_h // 2 + 10, top_sym, alpha=0.35, highlight=False)
        draw_tile((ry0 + ry1) // 2, sym, alpha=1.0, highlight=hi[i] and ok)
        draw_tile(ry1 - tile_h // 2 - 10, bot_sym, alpha=0.35, highlight=False)

        # motion lines
        for k in range(6):
            yy = y0 + 18 + k * int((reel_h - 36) / 5)
            draw.line([(x0 + 16, yy), (x1 - 16, yy)], fill=(30, 34, 46), width=1)

    # footer
    footer = f"Ставка {bet} 🪙"
    if ok:
        footer += f"  •  +{win} 🪙"
    fb = draw.textbbox((0, 0), footer, font=f_f)
    draw.text(((W - (fb[2] - fb[0])) // 2, H - pad - 40), footer, fill=(120, 135, 160), font=f_f)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def has_pillow() -> bool:
    return _HAS_PIL
