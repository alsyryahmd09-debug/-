"""
db_writer.py — المرحلة 6: Relational Database & Evidence Store + بوابة القرار
=========================================================================
يفترض وجود المخطط المُسلَّم سابقاً (abd_alqays_schema_and_data.sql) منشوراً
بالفعل، بإضافة جدولين هنا خاصين بهذا الأنبوب: review_queue وrejected_log —
حتى لا يدخل شيء إلى person/evidence مباشرة إلا ما مرّ فعلياً ببوابة ACCEPT.
"""
from __future__ import annotations
import os
import json
import psycopg2
import psycopg2.extras

from entity_resolution import ExtractedPerson, calculate_entity_match_score
from rubric import EvidenceItem, Relation, Gate

EXTRA_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS review_queue (
    review_id SERIAL PRIMARY KEY,
    canonical_name VARCHAR(255),
    kunya VARCHAR(100),
    nisba VARCHAR(255),
    proposed_relation CHAR(1),
    proposed_evidence_code VARCHAR(2),
    confidence_score SMALLINT,
    has_contradiction BOOLEAN,
    raw_quote TEXT,
    source_meta JSONB,
    rule_trace JSONB,
    suggested_existing_person_id INT REFERENCES person(person_id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewer_notes TEXT
);

CREATE TABLE IF NOT EXISTS rejected_log (
    rejected_id SERIAL PRIMARY KEY,
    canonical_name VARCHAR(255),
    reason TEXT,
    raw_quote TEXT,
    source_meta JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("AQ_DB_HOST", "localhost"),
        dbname=os.environ.get("AQ_DB_NAME", "sutoor_abdalqays"),
        user=os.environ.get("AQ_DB_USER", "postgres"),
        password=os.environ.get("AQ_DB_PASSWORD", ""),
    )


def ensure_extra_schema(conn):
    with conn.cursor() as cur:
        cur.execute(EXTRA_SCHEMA_SQL)
    conn.commit()


def _existing_people_as_extracted(conn) -> list[tuple[int, ExtractedPerson]]:
    """يجلب أشخاص قاعدة البيانات الحاليين لمقارنتهم بمرشح جديد ومنع التكرار.
    ملحوظة صادقة: جدول person لا يخزّن شبكة شيوخ/تلاميذ ولا سنة وفاة مؤكدة لكل
    الحالات، فهذه المطابقة جزئية (اسم + كنية + موطن) — أضعف من المطابقة بين
    سجلين مُستخرَجين حديثاً بكامل حقولهما، لكنها كافية لمنع التكرار الفاضح.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT person_id, canonical_name, kunya, geographical_scope FROM person;")
        rows = cur.fetchall()
    out = []
    for r in rows:
        geo = [g.strip() for g in (r["geographical_scope"] or "").split("/") if g.strip()]
        out.append((r["person_id"], ExtractedPerson(
            canonical_name=r["canonical_name"], kunya=r["kunya"], geographical_mentions=geo)))
    return out


def find_matching_existing_person(conn, extracted: ExtractedPerson, threshold: float = 0.75) -> int | None:
    best_id, best_score = None, 0.0
    for pid, existing in _existing_people_as_extracted(conn):
        score = calculate_entity_match_score(extracted, existing)
        if score > best_score:
            best_id, best_score = pid, score
    return best_id if best_score >= threshold else None


def upsert_source(conn, source_meta: dict) -> int:
    fields = ("title", "author", "publisher_editor", "edition", "volume", "page", "entry_number")
    vals = tuple(source_meta.get(f) for f in fields)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source_id FROM source
            WHERE title = %s AND COALESCE(author,'')=COALESCE(%s,'')
              AND COALESCE(edition,'')=COALESCE(%s,'') AND COALESCE(volume,'')=COALESCE(%s,'')
              AND COALESCE(page,'')=COALESCE(%s,'') AND COALESCE(entry_number,'')=COALESCE(%s,'')
        """, (vals[0], vals[1], vals[3], vals[4], vals[5], vals[6]))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("""
            INSERT INTO source (title, author, publisher_editor, edition, volume, page, entry_number)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING source_id
        """, vals)
        return cur.fetchone()[0]


def write_accept(conn, extracted: ExtractedPerson, relation: Relation, evidence_code: str,
                  confidence: int, evidence_items: list[EvidenceItem]) -> dict:
    """مسار ACCEPT فقط: يُنشئ شخصية جديدة أو يربط بشخصية موجودة، ثم يسجل الأدلة."""
    matched_id = find_matching_existing_person(conn, extracted)
    created_new = matched_id is None

    with conn.cursor() as cur:
        if matched_id is None:
            cur.execute("""
                INSERT INTO person (canonical_name, kunya, nisba, geographical_scope, notes)
                VALUES (%s,%s,%s,%s,%s) RETURNING person_id
            """, (extracted.canonical_name, extracted.kunya, None,
                  " / ".join(extracted.geographical_mentions) or None,
                  "أُدرج آلياً عبر أنبوب AQ-Extract — بوابة ACCEPT"))
            person_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO affiliation (person_id, affiliation_type, evidence_code, confidence_score, verification_status)
                VALUES (%s,%s,%s,%s,%s)
            """, (person_id, relation.value, evidence_code, confidence, "Verified"))
        else:
            person_id = matched_id

        evidence_ids = []
        for ev in evidence_items:
            source_id = upsert_source(conn, ev.source_meta)
            cur.execute("""
                INSERT INTO evidence (person_id, source_id, claim_type, quotation, confidence, notes)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING evidence_id
            """, (person_id, source_id, ev.claim_type, ev.raw_quote, confidence,
                  f"مُدخَل آلياً — assigned_code={ev.assigned_code.value}"))
            evidence_ids.append(cur.fetchone()[0])

    conn.commit()
    return {"gate": "ACCEPT", "person_id": person_id, "created_new_person": created_new,
            "evidence_ids": evidence_ids}


def write_review(conn, extracted: ExtractedPerson, relation: Relation, evidence_code: str,
                  confidence: int, has_contradiction: bool, raw_quote: str, source_meta: dict,
                  rule_trace: list[dict]) -> dict:
    # تحسين عملي: نرفق تخمين "هل هذه شخصية موجودة أصلاً؟" حتى لا يبدأ المراجع البشري من الصفر
    suggested_id = find_matching_existing_person(conn, extracted, threshold=0.55)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO review_queue (canonical_name, kunya, nisba, proposed_relation,
                proposed_evidence_code, confidence_score, has_contradiction, raw_quote,
                source_meta, rule_trace, suggested_existing_person_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING review_id
        """, (extracted.canonical_name, extracted.kunya, None, relation.value, evidence_code,
              confidence, has_contradiction, raw_quote, json.dumps(source_meta, ensure_ascii=False),
              json.dumps(rule_trace, ensure_ascii=False), suggested_id))
        review_id = cur.fetchone()[0]
    conn.commit()
    return {"gate": "REVIEW", "review_id": review_id, "suggested_existing_person_id": suggested_id}


def write_reject(conn, extracted: ExtractedPerson, reason: str, raw_quote: str, source_meta: dict) -> dict:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO rejected_log (canonical_name, reason, raw_quote, source_meta)
            VALUES (%s,%s,%s,%s) RETURNING rejected_id
        """, (extracted.canonical_name, reason, raw_quote, json.dumps(source_meta, ensure_ascii=False)))
        rejected_id = cur.fetchone()[0]
    conn.commit()
    return {"gate": "REJECT", "rejected_id": rejected_id}
