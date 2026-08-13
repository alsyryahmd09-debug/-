"""
rubric.py — قواعد الحظر الحتمية + معيار تقييم الأدلة والقطع
=========================================================================
تصحيح ثانٍ على الأنبوب المقترح (SEARCH→...→ACCEPT/REVIEW/REJECT):
وضع المستخدم CLASSIFY بين MATCH وCOMPARE. لكن قاعدة "التعارض التراجمي"
تفترض أصلاً أن يكون كل الأدلة المُجمَّعة (بعد MATCH) قد قُورنت (COMPARE)
وفُحصت للتعارض (CONTRADICTION TEST) *قبل* أن يُعطى الكيان تصنيفه
النهائي — وإلا يُصنَّف الكيان N أو W ثم يُكتشف التعارض لاحقاً فيحتاج
إلى تراجع لم يُصمَّم له مسار في الرسم الأصلي.
لذلك الترتيب المطبَّق هنا هو:
    MATCH → COMPARE → CONTRADICTION TEST → CLASSIFY → SCORE → GATE
أيضاً صُحِّح خطأ مطبعي في جدول الثقة الأصلي: كانت الرتبة الثالثة
"3 / 3" وهو خطأ واضح قياساً على بقية الصفوف (5/5 .. 0/5)؛ صُحِّحت هنا
إلى 3/5.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EvidenceCode(str, Enum):
    N1 = "N1"  # نص نسبي أصلي
    N2 = "N2"  # سلسلة نسب موثقة
    W1 = "W1"  # ولاء صريح
    R1 = "R1"  # نسبة عبدية مجردة
    D1 = "D1"  # خلاف نسبي بين المصادر
    H1 = "H1"  # استدلال نسبي
    U1 = "U1"  # دليل غير كافٍ


class Relation(str, Enum):
    N = "N"
    W = "W"
    C = "C"
    D = "D"
    U = "U"


LINEAGE_CODES = {EvidenceCode.N1, EvidenceCode.N2}
WILAYA_CODES = {EvidenceCode.W1}


@dataclass
class EvidenceItem:
    """يقابل evidence_extraction في مخرجات EXTRACT، بعد NORMALIZE."""
    raw_quote: str
    claim_type: str                 # Lineage | Wilaya | Nisba_Only | Disputed
    assigned_code: EvidenceCode
    proposed_relation: Relation     # اقتراح Claude — غير نهائي، القاعدة الحتمية قد تُلغيه
    hadith_evaluation: Optional[str] = None
    fiqh_mention: Optional[str] = None
    attributed_tribe: str = "عبد القيس"   # للمقارنة عبر المصادر في CONTRADICTION TEST
    source_meta: dict = field(default_factory=dict)
    has_explicit_linking_text: bool = True  # False = نسبة "العبدي" مجردة بلا نص رابط


@dataclass
class RuleTrace:
    """سجل شفاف لكل قاعدة حتمية طُبِّقت — يُحفظ في evidence.notes لقابلية التدقيق."""
    rule: str
    triggered: bool
    detail: str


# ---------------------------------------------------------------------
# قواعد الحظر والرفض الحتمي — تُطبَّق على كل EvidenceItem منفرداً
# ---------------------------------------------------------------------

def geography_isolation_rule(ev: EvidenceItem) -> tuple[EvidenceItem, RuleTrace]:
    """يُحظر منح كود N أو ثقة > 2/5 اعتماداً على الجغرافيا وحدها دون نص نسبي صريح."""
    relies_on_geo_only = ev.assigned_code not in (LINEAGE_CODES | WILAYA_CODES)
    if ev.proposed_relation == Relation.N and relies_on_geo_only:
        ev.proposed_relation = Relation.C
        return ev, RuleTrace(
            "geography_isolation", True,
            f"اقتراح Claude كان N بدون دليل نسبي صريح (assigned_code={ev.assigned_code.value}) — خُفِّض إلى C قسراً.")
    return ev, RuleTrace("geography_isolation", False, "لا ينطبق")


def nisba_ambiguity_rule(ev: EvidenceItem) -> tuple[EvidenceItem, RuleTrace]:
    """"فلان العبدي" بلا نص رابط بعبد القيس أو أحد بطونها ⇒ C + R1 فوراً."""
    if ev.assigned_code == EvidenceCode.R1 and not ev.has_explicit_linking_text:
        ev.proposed_relation = Relation.C
        return ev, RuleTrace("nisba_ambiguity", True, "نسبة 'العبدي' مجردة بلا نص رابط — صُنِّف C/R1.")
    return ev, RuleTrace("nisba_ambiguity", False, "لا ينطبق")


def hadith_independence_rule(ev: EvidenceItem) -> RuleTrace:
    """ضمان بنيوي: لا يُقرأ hadith_evaluation إطلاقاً في أي دالة تصنيف نسب.
    هذه الدالة توثيقية/تدقيقية — تتأكد أن لا نسب اعتمد على الحكم الحديثي."""
    used_hadith_for_lineage = False  # لا مسار برمجي هنا يقرأ hadith_evaluation عند التصنيف
    return RuleTrace("hadith_independence", used_hadith_for_lineage,
                      "hadith_evaluation مقروء فقط في حقل التقييم الحديثي، لا في proposed_relation.")


def apply_reject_rules(ev: EvidenceItem) -> tuple[EvidenceItem, list[RuleTrace]]:
    traces = []
    ev, t1 = geography_isolation_rule(ev)
    traces.append(t1)
    ev, t2 = nisba_ambiguity_rule(ev)
    traces.append(t2)
    traces.append(hadith_independence_rule(ev))
    return ev, traces


# ---------------------------------------------------------------------
# COMPARE + CONTRADICTION TEST — على مستوى الكيان (بعد MATCH، عبر كل الأدلة المُجمَّعة)
# ---------------------------------------------------------------------

def compare_and_test_contradiction(evidence_items: list[EvidenceItem]) -> tuple[bool, Optional[str]]:
    """يقارن انتماءات القبيلة المذكورة عبر كل الأدلة المُجمَّعة لكيان واحد.
    شرط doc4: مصدر A ينسبه لعبد القيس، ومصدر B لعبس أو ضبيعة ⇒ تعارض."""
    tribes = {ev.attributed_tribe.strip() for ev in evidence_items if ev.attributed_tribe}
    if len(tribes) > 1:
        detail = "تعارض نسبي بين المصادر: " + " / ".join(sorted(tribes))
        return True, detail
    return False, None


# ---------------------------------------------------------------------
# CLASSIFY — يُطبَّق بعد COMPARE/CONTRADICTION TEST لا قبلهما
# ---------------------------------------------------------------------

def classify_final_relation(evidence_items: list[EvidenceItem], has_contradiction: bool) -> Relation:
    if has_contradiction:
        return Relation.D
    codes = {ev.assigned_code for ev in evidence_items}
    if codes & LINEAGE_CODES:
        return Relation.N
    if codes & WILAYA_CODES:
        return Relation.W
    if EvidenceCode.R1 in codes:
        return Relation.C
    return Relation.U


# ---------------------------------------------------------------------
# SCORE — معيار الثقة (٣/٣ الأصلي صُحِّح إلى ٣/٥)
# ---------------------------------------------------------------------

def compute_confidence(evidence_items: list[EvidenceItem], has_contradiction: bool,
                        independent_source_count: int, has_corroborating_clue: bool = False,
                        definitively_other_tribe: bool = False) -> int:
    """
    تصحيح ثالث اكتُشف أثناء المراجعة النهائية قبل التسليم (وليس أثناء الكتابة الأولى):
    الصياغة الأولى مررت لها `independent_source_count >= 1` كشرط لتفريق الصفين
    3/5 و2/5 لحالة R1 — لكن هذا الشرط صحيح دائماً (يستحيل وجود أدلة بلا مصدر واحد
    على الأقل)، فكان فرع "2/5 نسبة مجردة بلا قرينة" ميتاً برمجياً (unreachable).
    الإصلاح: فصل "قرينة مساندة مطابقة (جغرافية/حديثية)" كمعامل مستقل عن عدد
    المصادر، لأن هذا هو الشرط الذي ينص عليه الجدول فعلاً لصف 3/5، لا عدد المصادر.

    كذلك ميّزت هنا بين has_contradiction (نصوص "مختلف فيها" D — غير محسومة،
    فتُصنَّف D بثقة 2/5) وبين definitively_other_tribe (0/5 — الصف الأخير في
    الجدول: "ثبوت نسب الشخصية لقبيلة أخرى يقيناً وزوال الشبهة"). هاتان حالتان
    مختلفتان في جدول doc4 نفسه ولا يصح دمجهما في شرط واحد.
    """
    codes = {ev.assigned_code for ev in evidence_items}

    if definitively_other_tribe:
        return 0  # "ثبوت نسب الشخصية لقبيلة أخرى يقيناً وزوال الشبهة"

    if has_contradiction:
        return 2  # "وجود نصوص متعارضة في النسب (D1)" — غير محسوم، لا مستبعد

    if EvidenceCode.N1 in codes:
        return 5

    if codes & {EvidenceCode.N2, EvidenceCode.W1}:
        # فجوة رابعة اكتُشفت أثناء الاختبار التكاملي الفعلي (لا التأمل النظري):
        # جدول doc4 الأصلي يمنح 4/5 لـ N2/W1 + مصدرين مستقلين، لكنه لا يذكر شيئاً
        # عن N2/W1 بمصدر واحد فقط — فسقطت هذه الحالة عبر كل الشروط التالية حتى
        # 0/5، أي أن دليل ولاء صريح غير مؤيَّد بعد بمصدر ثانٍ كان يُعامَل مثل انعدام
        # الدليل تماماً. هذا يطابق تماماً حالة حقيقية سبق التعامل معها يدوياً في
        # هذا المشروع (بطاقة يونس بن عبيد رقم 17، تهذيب الكمال، دليل واحد فقط)
        # حيث أُعطيت 3/5 كحكم مخصص وقتها؛ هذا الإصلاح يُنمذج نفس الحكم كقاعدة عامة
        # بدل تركه استثناءً يدوياً في كل مرة.
        return 4 if independent_source_count >= 2 else 3

    if EvidenceCode.R1 in codes and has_corroborating_clue:
        return 3  # مصحَّحة من "3/3" الأصلية، وربطها بالقرينة المساندة لا بعدد المصادر
    if EvidenceCode.R1 in codes:
        return 2  # نسبة مجردة بلا أي قرينة مساندة
    if EvidenceCode.H1 in codes:
        return 1
    return 0


class Gate(str, Enum):
    ACCEPT = "ACCEPT"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


def accept_review_reject(relation: Relation, confidence: int, has_contradiction: bool) -> tuple[Gate, str]:
    """المرحلة الأخيرة الناقصة في بروتوكول doc4 الأصلي — لا يكفي حساب الثقة، يجب
    تحديد إجرائياً ماذا يحدث بعدها: إدخال تلقائي؟ مراجعة بشرية؟ رفض؟"""
    if confidence == 0:
        return Gate.REJECT, "درجة ثقة 0/5 — ثبوت الانتساب لقبيلة أخرى يقيناً."
    if confidence >= 4 and not has_contradiction and relation in (Relation.N, Relation.W):
        return Gate.ACCEPT, f"ثقة {confidence}/5، بلا تعارض، صلة {relation.value} — إدخال مباشر مسموح."
    return Gate.REVIEW, f"ثقة {confidence}/5 أو صلة {relation.value} أو وجود تعارض — يتطلب مراجعة بشرية قبل الإدخال."
