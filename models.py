"""Shared worship data model — Fullerton Villa order of worship."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

PREP_HYMN_COUNT = 5


@dataclass
class HymnEntry:
    number: str = ""
    title: str = ""
    lyrics: List[str] = field(default_factory=list)
    include_lyrics: bool = True


@dataclass
class WorshipData:
    # Cover / basic info
    church_name_en: str = "Fullerton Villa Community Church"
    church_name_ko: str = "플러톤 빌라 교회"
    service_title: str = "주일 예배"
    date: str = ""
    service_time: str = "오전 11:00"
    preacher: str = ""
    worship_leader: str = "엄영민 목사"

    # 1. 예배 준비의 시간 (up to 5 hymns)
    prep_hymn_1: HymnEntry = field(default_factory=HymnEntry)
    prep_hymn_2: HymnEntry = field(default_factory=HymnEntry)
    prep_hymn_3: HymnEntry = field(default_factory=HymnEntry)
    prep_hymn_4: HymnEntry = field(default_factory=HymnEntry)
    prep_hymn_5: HymnEntry = field(default_factory=HymnEntry)

    # 2. 찬양과 기도
    praise_hymn: HymnEntry = field(default_factory=HymnEntry)

    # 3. 사도신경
    apostles_creed: str = ""

    # 4. 교독문
    responsive_reading_title: str = ""
    responsive_reading: str = ""

    # 5. 찬송가
    hymn: HymnEntry = field(default_factory=HymnEntry)

    # 6. 예배의 기도
    worship_prayer: str = ""
    worship_prayer_leader: str = ""

    # 7. 성가대 찬양
    choir_anthem: HymnEntry = field(default_factory=HymnEntry)

    # 8. 오늘의 말씀
    scripture_reference: str = ""
    scripture_text: str = ""
    # 금주의 암송구절 (one verse, shown under scripture on the bulletin)
    memory_verse_reference: str = ""
    memory_verse_text: str = ""

    # (removed from numbered order — keep empty)
    response_hymn: HymnEntry = field(default_factory=HymnEntry)

    # 9. 생명의 말씀
    sermon_title: str = ""
    sermon_subtitle: str = ""

    # 10. 감사와 봉헌
    offering_hymn: HymnEntry = field(default_factory=HymnEntry)

    # 11. 축도
    benediction: str = ""
    closing_note: str = ""

    # Extra bulletin content (often source page 2+)
    announcements: str = ""

    # Multi-page layout plan: role -> list of 1-based source page numbers
    # roles: cover_order | readings | announcements
    page_plan: Dict[str, List[int]] = field(default_factory=dict)

    # Exact uploaded bulletin pages for 1:1 PDF mirroring
    # each item: {"index": int, "role": str, "text": str}
    source_pages: List[dict] = field(default_factory=list)

    # Output options
    # PPT uses hymn intro slides only; lyrics come from separate hymn PPTs
    include_hymn_lyrics: bool = False

    def iter_prep_hymns(self) -> List[HymnEntry]:
        return [getattr(self, f"prep_hymn_{i}") for i in range(1, PREP_HYMN_COUNT + 1)]

    def iter_hymns(self) -> List[HymnEntry]:
        return [
            *self.iter_prep_hymns(),
            self.praise_hymn,
            self.hymn,
            self.choir_anthem,
            self.offering_hymn,
            self.response_hymn,
        ]

    # --- Compatibility helpers for older call sites ---
    @property
    def church_name(self) -> str:
        return self.church_name_ko or self.church_name_en

    @property
    def is_multipage(self) -> bool:
        if (self.announcements or "").strip():
            return True
        roles = [r for r, pages in (self.page_plan or {}).items() if pages]
        return len(roles) >= 2
