"""Senior-friendly slide design tokens — nursing-home projection."""

from __future__ import annotations

from pathlib import Path

from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

# 16:9 widescreen
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

# Preferred: dark charcoal + pure white (minimal eye strain)
BG_COLOR = RGBColor(0x21, 0x21, 0x21)
TITLE_COLOR = RGBColor(0xFF, 0xFF, 0xFF)
BODY_COLOR = RGBColor(0xFF, 0xFF, 0xFF)
ACCENT_COLOR = RGBColor(0xD8, 0xD8, 0xD8)
SUBTLE_COLOR = RGBColor(0xBD, 0xBD, 0xBD)

# Alternate cream theme tokens (available if toggled later)
CREAM_BG = RGBColor(0xFF, 0xFD, 0xF5)
CREAM_INK = RGBColor(0x33, 0x33, 0x33)


def _resolve_korean_sans() -> str:
    """Prefer Pretendard / Noto Sans KR Bold-capable faces; fall back to Malgun Gothic."""
    candidates = [
        Path(r"C:\Windows\Fonts\Pretendard-Bold.otf"),
        Path(r"C:\Windows\Fonts\PretendardBold.ttf"),
        Path(r"C:\Windows\Fonts\NotoSansCJKkr-Bold.otf"),
        Path(r"C:\Windows\Fonts\NotoSansKR-Bold.otf"),
        Path(r"C:\Windows\Fonts\NotoSansKR-Bold.ttf"),
        Path(r"C:\Windows\Fonts\malgunbd.ttf"),
        Path(r"C:\Windows\Fonts\malgun.ttf"),
    ]
    # python-pptx uses installed font *family* names, not file paths
    for path in candidates:
        name = path.name.lower()
        if "pretendard" in name and path.exists():
            return "Pretendard"
        if "notosans" in name.replace("-", "").replace("_", "") and path.exists():
            return "Noto Sans KR"
    return "Malgun Gothic"


FONT_NAME = _resolve_korean_sans()
FONT_NAME_FALLBACK = "Malgun Gothic"

# Senior sizes (strict floors)
TITLE_SIZE = Pt(54)       # Hymn number / name
SECTION_SIZE = Pt(48)     # Section headings
BODY_SIZE = Pt(40)        # Lyrics / scripture minimum
HYMN_SIZE = Pt(40)
SMALL_LABEL_SIZE = Pt(28)

# Generous layout
MARGIN_LEFT = Inches(0.85)
MARGIN_RIGHT = Inches(0.85)
MARGIN_TOP = Inches(0.55)
CONTENT_WIDTH = SLIDE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

# Typography rhythm
LINE_SPACING = 1.5
PARAGRAPH_SPACE_AFTER_PT = 16
