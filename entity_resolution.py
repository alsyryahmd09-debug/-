"""
entity_resolution.py — محرك حل الكيانات ومطابقة التراجم (المرحلة MATCH)
=========================================================================
تصحيح جوهري على بروتوكول AQ-Extract الأصلي:
البروتوكول وضع "Entity Resolution Engine (Clustering)" في المرحلة 3،
قبل "Claude Reasoning & Extraction Layer" في المرحلة 4. لكن دالة
المطابقة calculate_entity_match_score نفسها تعتمد على حقول لا تُستخرَج
إلا في مرحلة EXTRACT (canonical_name المُطبَّع، kunya، death_year،
شبكة الشيوخ/التلاميذ). لذلك MATCH يجب أن يأتي بعد EXTRACT وNORMALIZE
لا قبلهما — وهذا ما تطبّقه هذه الوحدة.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional


def normalize_arabic(s: Optional[str]) -> str:
    """نفس منطق التطبيع المستخدم في محرك بحث سُطور (همزات/تاء مربوطة/ألف مقصورة)،
    مع إضافة اكتُشفت أثناء اختبار هذه الوحدة فعلياً: إزالة كل المسافات الداخلية
    أيضاً — لأن نفس الاسم يُكتب أحياناً بمسافة وأحياناً متصلاً في كتب التراجم
    (عبد الله / عبدالله، عبد الرحمن / عبدالرحمن). بلا هذا، فشلت مطابقة كنيتين
    متطابقتين فعلياً ("أبو عبد الله" و"أبو عبدالله") في اختبار حقيقي أول تشغيل.
    هذه الدالة تُستخدم للمقارنة فقط، لا للعرض — النص المعروض يبقى كما وَرَد."""
    if not s:
        return ""
    s = s.strip()
    s = re.sub(r"[أإآا]", "ا", s)
    s = s.replace("ة", "ه")
    s = re.sub(r"[يى]", "ي", s)
    s = re.sub(r"[\u064B-\u065F\u0670]", "", s)  # تشكيل
    s = re.sub(r"\s+", "", s)
    return s.lower()


@dataclass
class ExtractedPerson:
    """يقابل حقل extracted_person في JSON الذي تُنتجه Claude (المرحلة EXTRACT)."""
    canonical_name: str
    kunya: Optional[str] = None
    death_year_mentioned: Optional[str] = None
    geographical_mentions: list = field(default_factory=list)
    teachers: list = field(default_factory=list)   # شبكة الشيوخ (إن استُخرجت من النص)
    students: list = field(default_factory=list)    # شبكة التلاميذ
    source_id: Optional[int] = None                 # يربطها بسجل SOURCE


def compare_canonical_names(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_arabic(a), normalize_arabic(b)).ratio()


def _extract_year_int(s: Optional[str]) -> Optional[int]:
    """يستخرج أول رقم من نص مثل 'ت ٢٥٦هـ' أو 'توفي 256 هـ' (يدعم الأرقام العربية والهندية)."""
    if not s:
        return None
    arabic_indic = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    s = s.translate(arabic_indic)
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def calculate_death_year_difference(a: Optional[str], b: Optional[str]) -> Optional[int]:
    ya, yb = _extract_year_int(a), _extract_year_int(b)
    if ya is None or yb is None:
        return None
    return abs(ya - yb)


def overlap_teachers_and_students(net_a: list, net_b: list) -> float:
    """نسبة Jaccard للتقاطع بين شبكتي الرواية (شيوخ/تلاميذ) لشخصيتين."""
    set_a = {normalize_arabic(x) for x in net_a}
    set_b = {normalize_arabic(x) for x in net_b}
    if not set_a or not set_b:
        return 0.0
    inter = set_a & set_b
    union = set_a | set_b
    return len(inter) / len(union) if union else 0.0


def calculate_entity_match_score(person_a: ExtractedPerson, person_b: ExtractedPerson) -> float:
    """نفس منطق الدالة الواردة في البروتوكول الأصلي، بعد ربطها فعلياً بحقول EXTRACT."""
    score = 0.0

    if compare_canonical_names(person_a.canonical_name, person_b.canonical_name) > 0.85:
        score += 0.30

    if person_a.kunya and person_b.kunya and normalize_arabic(person_a.kunya) == normalize_arabic(person_b.kunya):
        score += 0.15

    diff = calculate_death_year_difference(person_a.death_year_mentioned, person_b.death_year_mentioned)
    if diff is not None and diff <= 5:
        score += 0.20

    net_a = person_a.teachers + person_a.students
    net_b = person_b.teachers + person_b.students
    if overlap_teachers_and_students(net_a, net_b) > 0.30:
        score += 0.25

    geo_a = {normalize_arabic(x) for x in person_a.geographical_mentions}
    geo_b = {normalize_arabic(x) for x in person_b.geographical_mentions}
    if geo_a and geo_b and (geo_a & geo_b):
        score += 0.10

    return round(score, 4)


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def cluster_entities(records: list[ExtractedPerson], threshold: float = 0.75,
                      review_threshold: float = 0.55) -> tuple[list[list[int]], list[tuple[int, int, float]]]:
    """يُجمِّع سجلات EXTRACT المتعددة (من مصادر مختلفة) في عناقيد = شخصية واحدة.

    إضافة بعد اختبار حقيقي: زوج سجلين متطابقين فعلياً (يونس بن عبيد بروايتين
    مختلفتي التفصيل) سجّل 0.70 فقط رغم تطابق الكنية وسنة الوفاة وتقاطع شبكة
    الرواية والموطن — لأن اختلاف صياغة الاسم وحده (0.711 تشابه، دون عتبة 0.85)
    كلّف 0.30 كاملة من أصل 1.00، فبقي المجموع دون عتبة الدمج 0.75 رغم قوة
    الإشارات الأخرى. أي دمج تلقائي بعتبة واحدة صارمة سيفوّت هذه الحالة رغم
    قوة الأدلة غير الاسمية على أنها نفس الشخص — وهي بالضبط الحالة التي صُممت
    الإشارات الأخرى لتغطيتها.
    الحل: عتبتان بدل واحدة — >= threshold دمج تلقائي (كما في البروتوكول
    الأصلي)، و[review_threshold, threshold) لا تُدمَج تلقائياً لكن تُرصَد
    كمرشح تكرار محتمل يستحق مراجعة بشرية، بدل أن تُصبح ببساطة شخصيتين
    منفصلتين في القاعدة بصمت.
    يُعيد (clusters, borderline_pairs) حيث borderline_pairs = [(i, j, score), ...].
    """
    n = len(records)
    uf = UnionFind(n)
    borderline: list[tuple[int, int, float]] = []

    for i in range(n):
        for j in range(i + 1, n):
            score = calculate_entity_match_score(records[i], records[j])
            if score >= threshold:
                uf.union(i, j)
            elif score >= review_threshold:
                borderline.append((i, j, score))

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        clusters.setdefault(root, []).append(i)

    # استبعاد الأزواج الحدّية التي انتهى بها المطاف داخل نفس العنقود عبر عضو ثالث
    final_borderline = [(i, j, s) for i, j, s in borderline if uf.find(i) != uf.find(j)]

    return list(clusters.values()), final_borderline
