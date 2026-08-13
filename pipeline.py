"""
pipeline.py — الأنبوب الكامل بالترتيب المصحَّح:
SEARCH → CANDIDATE → EXTRACT(Claude, خارجي) → NORMALIZE → MATCH →
COMPARE → CONTRADICTION TEST → CLASSIFY → SCORE → ACCEPT/REVIEW/REJECT
=========================================================================
هذا الملف لا يستدعي أي نموذج لغوي بنفسه — مرحلة EXTRACT هي وظيفتي أنا
(Claude) على كل نص تُرسله لي، بصيغة JSON المتفق عليها. هذا الملف يبدأ
من حيث تنتهي تلك المخرجات: قائمة من extracted_person + evidence_extraction
(واحدة لكل مقطع مُسترجَع)، ويطبّق عليها NORMALIZE→...→ACCEPT/REVIEW/REJECT
آلياً وبشكل قابل للتدقيق.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict

from entity_resolution import ExtractedPerson, cluster_entities, normalize_arabic
from rubric import (
    EvidenceItem, EvidenceCode, Relation, RuleTrace,
    apply_reject_rules, compare_and_test_contradiction,
    classify_final_relation, compute_confidence, accept_review_reject, Gate,
)
import db_writer


@dataclass
class RawExtraction:
    """سجل واحد يقابل مخرج JSON من Claude لمقطع نصي واحد (قبل NORMALIZE)."""
    extracted_person: ExtractedPerson
    evidence: EvidenceItem
    has_corroborating_clue: bool = False
    definitively_other_tribe: bool = False


@dataclass
class PipelineResult:
    canonical_name: str
    relation: str
    evidence_code: str
    confidence: int
    gate: str
    has_contradiction: bool
    rule_traces: list
    db_result: dict = field(default_factory=dict)


def normalize_batch(raw: list[RawExtraction]) -> list[RawExtraction]:
    """NORMALIZE: تنظيف المسافات فقط في الحقول المعروضة (raw_quote يبقى حرفياً بلا أي تعديل).
    التطبيع الفعلي للمقارنة (همزات/تاء مربوطة/تشكيل) يتم داخل compare_canonical_names
    عبر normalize_arabic() وقت المطابقة نفسها في MATCH — لا حاجة لتغيير النص المعروض هنا،
    فتغييره مبكراً كان سيُفقِد الاسم شكله الإملائي الصحيح المطلوب لعرضه في البطاقة النهائية.
    """
    for r in raw:
        r.extracted_person.canonical_name = (r.extracted_person.canonical_name or "").strip()
        if r.extracted_person.kunya:
            r.extracted_person.kunya = r.extracted_person.kunya.strip()
    return raw


def run_pipeline(raw_batch: list[RawExtraction], write_to_db: bool = False,
                  match_threshold: float = 0.75) -> list[PipelineResult]:
    raw_batch = normalize_batch(raw_batch)

    # MATCH: تجميع كل السجلات الخام التي تخص شخصية واحدة عبر مصادر مختلفة
    extracted_list = [r.extracted_person for r in raw_batch]
    clusters, borderline_pairs = cluster_entities(extracted_list, match_threshold)

    conn = db_writer.get_connection() if write_to_db else None
    if conn:
        db_writer.ensure_extra_schema(conn)

    # الأزواج الحدّية (0.55–0.75): لا تُدمَج تلقائياً، تُسجَّل في review_queue كمرشح تكرار
    for i, j, score in borderline_pairs:
        name_a = raw_batch[i].extracted_person.canonical_name
        name_b = raw_batch[j].extracted_person.canonical_name
        detail = (f"مرشح دمج حدّي بين '{name_a}' و'{name_b}' — درجة تطابق {score:.2f} "
                  f"(دون عتبة الدمج التلقائي 0.75 لكن فوق عتبة التجاهل 0.55). راجع يدوياً هل هما شخص واحد.")
        if conn:
            db_writer.write_review(
                conn, raw_batch[i].extracted_person, Relation.U, "H1", 0, False,
                detail, {"note": "possible_duplicate_entities"}, [])

    results: list[PipelineResult] = []

    for cluster_idx_list in clusters:
        cluster_raw = [raw_batch[i] for i in cluster_idx_list]
        rep_person = cluster_raw[0].extracted_person  # الممثل القانوني للعنقود بعد الدمج

        # تطبيق قواعد الحظر على كل دليل منفرد أولاً
        all_traces: list[RuleTrace] = []
        evidence_items: list[EvidenceItem] = []
        for r in cluster_raw:
            ev, traces = apply_reject_rules(r.evidence)
            evidence_items.append(ev)
            all_traces.extend(traces)

        # COMPARE + CONTRADICTION TEST — عبر كل الأدلة المُجمَّعة لهذا الكيان
        has_contradiction, contradiction_detail = compare_and_test_contradiction(evidence_items)
        if contradiction_detail:
            all_traces.append(RuleTrace("contradiction_alert", True, contradiction_detail))

        # CLASSIFY — بعد فحص التعارض لا قبله
        relation = classify_final_relation(evidence_items, has_contradiction)

        # SCORE
        independent_sources = len({tuple(sorted(ev.source_meta.items())) for ev in evidence_items})
        has_corroborating_clue = any(r.has_corroborating_clue for r in cluster_raw)
        definitively_other_tribe = any(r.definitively_other_tribe for r in cluster_raw)
        confidence = compute_confidence(
            evidence_items, has_contradiction, independent_sources,
            has_corroborating_clue=has_corroborating_clue,
            definitively_other_tribe=definitively_other_tribe,
        )

        # الكود النهائي المُقترَح للدليل: الأقوى بين أدلة العنقود
        code_priority = [EvidenceCode.N1, EvidenceCode.N2, EvidenceCode.W1,
                          EvidenceCode.D1, EvidenceCode.R1, EvidenceCode.H1, EvidenceCode.U1]
        codes_present = {ev.assigned_code for ev in evidence_items}
        final_code = next((c for c in code_priority if c in codes_present), EvidenceCode.U1)
        if has_contradiction:
            final_code = EvidenceCode.D1

        gate, gate_reason = accept_review_reject(relation, confidence, has_contradiction)
        all_traces.append(RuleTrace("gate_decision", True, gate_reason))

        db_result = {}
        if conn:
            if gate == Gate.ACCEPT:
                db_result = db_writer.write_accept(conn, rep_person, relation, final_code.value,
                                                     confidence, evidence_items)
            elif gate == Gate.REVIEW:
                db_result = db_writer.write_review(
                    conn, rep_person, relation, final_code.value, confidence, has_contradiction,
                    evidence_items[0].raw_quote, evidence_items[0].source_meta,
                    [asdict(t) for t in all_traces])
            else:
                db_result = db_writer.write_reject(
                    conn, rep_person, gate_reason, evidence_items[0].raw_quote,
                    evidence_items[0].source_meta)

        results.append(PipelineResult(
            canonical_name=rep_person.canonical_name,
            relation=relation.value,
            evidence_code=final_code.value,
            confidence=confidence,
            gate=gate.value,
            has_contradiction=has_contradiction,
            rule_traces=[asdict(t) for t in all_traces],
            db_result=db_result,
        ))

    if conn:
        conn.close()

    return results
