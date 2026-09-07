"""Renders the attendance report as a PNG image."""

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Shipped with the bot so the report looks identical on macOS and on a server,
# and so Cyrillic always renders regardless of what the host has installed.
FONT_DIR = Path(__file__).resolve().parent / "fonts"

WIDTH = 900
PAD = 40
HEADER_H = 132
SUMMARY_H = 86
ROW_H = 56
FOOTER_H = 62

INK = (17, 24, 39)
MUTED = (107, 114, 128)
HEADER_BG = (31, 41, 55)
WHITE = (255, 255, 255)
ROW_ALT = (248, 250, 252)
LINE = (229, 231, 235)
GREEN = (22, 163, 74)
GREEN_SOFT = (220, 252, 231)
RED = (220, 38, 38)
RED_SOFT = (254, 226, 226)

_REGULAR = [
    str(FONT_DIR / "DejaVuSans.ttf"),
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_BOLD = [
    str(FONT_DIR / "DejaVuSans-Bold.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font(size: int, bold: bool = False):
    for path in (_BOLD if bold else []) + _REGULAR:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _draw_tick(draw, cx, cy, r, color):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    draw.line(
        [(cx - r * 0.42, cy + r * 0.02), (cx - r * 0.10, cy + r * 0.36), (cx + r * 0.46, cy - r * 0.38)],
        fill=WHITE,
        width=max(2, int(r * 0.30)),
        joint="curve",
    )


def _draw_cross(draw, cx, cy, r, color):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    w = max(2, int(r * 0.30))
    d = r * 0.40
    draw.line([(cx - d, cy - d), (cx + d, cy + d)], fill=WHITE, width=w)
    draw.line([(cx + d, cy - d), (cx - d, cy + d)], fill=WHITE, width=w)


def _pill(draw, x, y, text, font, bg, fg):
    tw = draw.textlength(text, font=font)
    h = 34
    box = [x, y, x + tw + 32, y + h]
    draw.rounded_rectangle(box, radius=h // 2, fill=bg)
    draw.text((x + 16, y + h / 2), text, font=font, fill=fg, anchor="lm")
    return box[2]


def build_report_image(group_name, students, absent, when=None, marked_by=None,
                       generated_at=None) -> io.BytesIO:
    """`when` is the day the sheet covers; `generated_at` is the export time."""
    when = when or datetime.now()
    generated_at = generated_at or when
    absent_set = set(absent)
    present = [s for s in students if s not in absent_set]
    absent_list = [s for s in students if s in absent_set]

    rows = max(len(students), 1)
    height = HEADER_H + SUMMARY_H + rows * ROW_H + FOOTER_H

    img = Image.new("RGB", (WIDTH, height), WHITE)
    draw = ImageDraw.Draw(img)

    f_title = _font(34, bold=True)
    f_sub = _font(19)
    f_pill = _font(18, bold=True)
    f_name = _font(22)
    f_status = _font(18, bold=True)
    f_small = _font(15)

    # Header
    draw.rectangle([0, 0, WIDTH, HEADER_H], fill=HEADER_BG)
    draw.text((PAD, 40), "Attendance Report", font=f_title, fill=WHITE, anchor="lm")
    draw.text(
        (PAD, 82),
        f"{group_name}  ·  {when.strftime('%A, %d %B %Y')}",
        font=f_sub,
        fill=(190, 197, 208),
        anchor="lm",
    )

    # Summary pills
    y = HEADER_H + 26
    x = _pill(draw, PAD, y, f"Present  {len(present)}", f_pill, GREEN_SOFT, GREEN)
    x = _pill(draw, x + 12, y, f"Absent  {len(absent_list)}", f_pill, RED_SOFT, RED)
    _pill(draw, x + 12, y, f"Total  {len(students)}", f_pill, (241, 245, 249), MUTED)

    # Rows
    top = HEADER_H + SUMMARY_H
    if not students:
        draw.text((PAD, top + 30), "No students on the roster.", font=f_name, fill=MUTED)
    for i, name in enumerate(students):
        ry = top + i * ROW_H
        is_absent = name in absent_set
        if i % 2 == 1:
            draw.rectangle([0, ry, WIDTH, ry + ROW_H], fill=ROW_ALT)
        draw.line([(PAD, ry), (WIDTH - PAD, ry)], fill=LINE, width=1)

        cy = ry + ROW_H / 2
        if is_absent:
            _draw_cross(draw, PAD + 14, cy, 13, RED)
        else:
            _draw_tick(draw, PAD + 14, cy, 13, GREEN)

        draw.text((PAD + 40, cy), name, font=f_name, fill=INK, anchor="lm")
        draw.text(
            (WIDTH - PAD, cy),
            "ABSENT" if is_absent else "PRESENT",
            font=f_status,
            fill=RED if is_absent else GREEN,
            anchor="rm",
        )

    # Footer
    fy = top + len(students) * ROW_H
    draw.line([(PAD, fy), (WIDTH - PAD, fy)], fill=LINE, width=1)
    stamp = f"Generated {generated_at.strftime('%d %b %Y, %H:%M')}"
    if marked_by:
        stamp += f"  ·  by {marked_by}"
    draw.text((PAD, fy + FOOTER_H / 2), stamp, font=f_small, fill=MUTED, anchor="lm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = f"attendance-{when.strftime('%Y-%m-%d')}.png"
    return buf


def build_report_text(group_name, students, absent, when=None, generated_at=None) -> str:
    when = when or datetime.now()
    generated_at = generated_at or when
    absent_set = set(absent)
    present = [s for s in students if s not in absent_set]
    absent_list = [s for s in students if s in absent_set]
    lines = [
        f"Attendance Report — {group_name}",
        when.strftime("%A, %d %B %Y, %H:%M"),
        "",
        f"Present: {len(present)} / {len(students)}",
        f"Absent:  {len(absent_list)} / {len(students)}",
        "",
        "PRESENT:",
    ]
    lines += [f"  + {n}" for n in present] or ["  (none)"]
    lines += ["", "ABSENT:"]
    lines += [f"  - {n}" for n in absent_list] or ["  (none)"]
    return "\n".join(lines)
