"""Default texts and branding for Fullerton Villa Community Church worship order."""

CHURCH_NAME_EN = "Fullerton Villa Community Church"
CHURCH_NAME_KO = "플러톤 빌라 교회"

# Legacy / wrong spellings → always normalize to CHURCH_NAME_KO
CHURCH_NAME_KO_ALIASES = (
    "플로튼 빌라 교회",
    "플로톤 빌라 교회",
    "플러튼 빌라 교회",
    "플로튼 장로교회",
    "플로튼 장로 교회",
    "플러튼 장로교회",
    "플러톤 장로교회",
    "플러톤빌라교회",
    "플러톤 빌라교회",
)
DEFAULT_SERVICE_TITLE = "주일 예배"
DEFAULT_SERVICE_TIME = "오전 11:00"
DEFAULT_WORSHIP_LEADER = "엄영민 목사"

# No blank lines — PPT shows exactly 4 dense lines per slide
DEFAULT_APOSTLES_CREED = """전능하사 천지를 만드신 하나님 아버지를 내가 믿사오며,
그 외아들 우리 주 예수 그리스도를 믿사오니,
이는 성령으로 잉태하사 동정녀 마리아에게 나시고,
본디오 빌라도에게 고난을 받으사 십자가에 못 박혀 죽으시고,
장사한 지 사흘 만에 죽은 자 가운데서 다시 살아나시며,
하늘에 오르사 전능하신 하나님 우편에 앉아 계시다가,
거기로부터 산 자와 죽은 자를 심판하러 오시리라.
성령을 믿사오며, 거룩한 공회와, 성도가 서로 교통하는 것과,
죄를 사하여 주시는 것과, 몸이 다시 사는 것과, 영원히 사는 것을 믿사옵나이다. 아멘."""

DEFAULT_RESPONSIVE_READING = """인도자: 여호와는 나의 목자시니 내게 부족함이 없으리로다
회중: 그가 나를 푸른 풀밭에 누이시며 쉴 만한 물 가로 인도하시는도다
인도자: 내 영혼을 소생시키시고 자기 이름을 위하여 의의 길로 인도하시는도다
회중: 내가 사망의 음침한 골짜기로 다닐지라도 해를 두려워하지 않을 것은 주께서 나와 함께 하심이라
인도자: 주의 지팡이와 막대기가 나를 안위하시나이다
회중: 내 평생에 선하심과 인자하심이 반드시 나를 따르리니 내가 여호와의 집에 영원히 살리로다"""

DEFAULT_WORSHIP_PRAYER = """살아계신 하나님 아버지,
오늘 이 자리에 모인 성도들을 주님의 사랑으로 품어 주시고,
예배를 통해 주님을 만나며 새 힘을 얻게 하옵소서.
예수님의 이름으로 기도드립니다. 아멘."""

DEFAULT_BENEDICTION = "담임목사"

# Traditional order labels (11 numbered steps + announcements)
ORDER_LABELS = [
    ("1", "예배 준비의 시간", "Preparation for Worship"),
    ("2", "찬양과 기도", "Praise & Prayer"),
    ("3", "사도신경", "The Apostles' Creed"),
    ("4", "교독문", "Responsive Reading"),
    ("5", "찬송가", "Hymn"),
    ("6", "예배의 기도", "Pastoral Prayer"),
    ("7", "성가대 찬양", "Choir Anthem"),
    ("8", "오늘의 말씀", "Scripture Reading"),
    ("9", "생명의 말씀", "The Word of Life"),
    ("10", "감사와 봉헌", "Offering"),
    ("11", "축도", "Benediction"),
]
