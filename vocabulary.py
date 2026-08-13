"""
vocabulary.py — قاموس طبقات البحث الثلاثي (المرحلتان SEARCH / CANDIDATE)
=========================================================================
يطبّق الجدول الوارد في البروتوكول (ثانياً: قاموس طبقات البحث والتنقيب).
هذه الطبقة لا تحسم شيئاً — فقط تُصنّف "قوة الإشارة" الأولية لمقطع نصي
مُسترجَع، تمهيداً لتمريره إلى EXTRACT (طبقة Claude).
"""
import re
from dataclasses import dataclass, field
from enum import Enum


class CandidateTier(str, Enum):
    CONFIRMED_TARGET = "Confirmed Target"      # الطبقة 1: نسب صريح
    SUBTRIBE = "Candidate: Sub-tribe"           # الطبقة 2: بطون وأفخاذ
    DISCOVERY_SIGNAL = "Discovery Signal Only"  # الطبقة 3: قرينة جغرافية (محظور الإثبات المباشر)
    NONE = "No Match"


# الطبقة 1: النسب الصريح
_T1_LINEAGE = re.compile(r"عبد\s*القيس|عبدالقيس|من\s+عبد\s+القيس|من\s+بني\s+عبد\s+القيس")
_T1_CONTEXT = re.compile(r"ترجمة|روى|حدث|ولد|مات|توفي")

# الطبقة 2: البطون والأفخاذ (يمكن للمستخدم توسيعها لاحقاً بسهولة)
_T2_SUBTRIBES = [
    "العصري", "العوقي", "الأنماري", "الجارودي", "اللكيزي",
    "الصباحي", "الجدَني", "الجدني", "الضبعي",
]
_T2_PATTERN = re.compile("|".join(map(re.escape, _T2_SUBTRIBES)))

# الطبقة 3: القرائن النسبية والجغرافية (إشارة اكتشاف فقط)
_T3_NISBA = re.compile(r"العبدي|العبقسي")
_T3_GEO = re.compile(r"أوال|البحرين|هجر|القطيف|البصرة")


@dataclass
class CandidateHit:
    text: str
    tier: CandidateTier
    matched_terms: list = field(default_factory=list)
    matched_geo: list = field(default_factory=list)

    def to_dict(self):
        return {
            "tier": self.tier.value,
            "matched_terms": self.matched_terms,
            "matched_geo": self.matched_geo,
        }


def classify_candidate(text: str) -> CandidateHit:
    """يُطبَّق فوراً بعد SEARCH لتصنيف كل نتيجة مُسترجَعة قبل تمريرها لـ EXTRACT."""
    # الطبقة 1: نسب صريح + سياق ترجمي
    if _T1_LINEAGE.search(text) and _T1_CONTEXT.search(text):
        return CandidateHit(text, CandidateTier.CONFIRMED_TARGET,
                             matched_terms=_T1_LINEAGE.findall(text))

    # الطبقة 2: بطن معروف من بطون عبد القيس
    m2 = _T2_PATTERN.findall(text)
    if m2:
        return CandidateHit(text, CandidateTier.SUBTRIBE, matched_terms=list(set(m2)))

    # الطبقة 3: نسبة مجردة + قرينة جغرافية معاً (شرط AND كما في الجدول الأصلي)
    m3_nisba = _T3_NISBA.findall(text)
    m3_geo = _T3_GEO.findall(text)
    if m3_nisba and m3_geo:
        return CandidateHit(text, CandidateTier.DISCOVERY_SIGNAL,
                             matched_terms=list(set(m3_nisba)), matched_geo=list(set(m3_geo)))

    return CandidateHit(text, CandidateTier.NONE)
