# aq_extract — تنفيذ بروتوكول AQ-Extract (بعد تصحيحه واختباره فعلياً)

حزمة بايثون تُطبِّق الأنبوب المصحَّح:

```
SEARCH → CANDIDATE → EXTRACT (Claude، خارج هذه الحزمة) → NORMALIZE → MATCH
  → COMPARE → CONTRADICTION TEST → CLASSIFY → SCORE → ACCEPT/REVIEW/REJECT
```

مبنية فوق مخطط `abd_alqays_schema_and_data.sql` المُسلَّم سابقاً (تُضيف عليه
جدولين فقط: `review_queue` و`rejected_log`، تُنشأ تلقائياً عند أول تشغيل).

## التصحيحات الأربعة المُطبَّقة هنا (كل واحد منها اكتُشف بالاختبار الفعلي، لا بالتأمل النظري)

1. **ترتيب MATCH بعد EXTRACT لا قبله** — بروتوكول doc4 الأصلي وضع حل الكيانات
   (تجميع التراجم) قبل مرحلة الاستخراج، رغم أن دالة المطابقة نفسها تحتاج حقولاً
   (الاسم المُطبَّع، الكنية، سنة الوفاة، شبكة الرواية) لا تُستخرَج إلا في EXTRACT.
2. **عتبة دمج مزدوجة بدل عتبة واحدة صارمة** (`entity_resolution.cluster_entities`) —
   اختبار حقيقي لشخصين هما نفس الفرد فعلياً (بروايتين مختلفتي التفصيل) سجّل 0.70
   فقط رغم تطابق الكنية وسنة الوفاة وشبكة الرواية والموطن، لأن اختلاف صياغة
   الاسم وحده كلّف 0.30 من أصل 1.00. أُضيفت عتبة ثانية (0.55) تُسجِّل هذه الأزواج
   الحدّية في `review_queue` بدل دمجها صامتاً أو تجاهلها صامتاً.
3. **فجوة في جدول الثقة**: N2/W1 من مصدر واحد فقط (غير مؤيَّد بعد) كانت تسقط إلى
   0/5 مباشرة رغم قوة الدليل، لأن الجدول الأصلي لا يذكر هذه الحالة إطلاقاً — أُضيف
   3/5 لها (نفس الحكم المُطبَّق يدوياً سابقاً على بطاقة يونس بن عبيد رقم 17).
4. **CLASSIFY بعد COMPARE/CONTRADICTION TEST لا قبلهما** — وإلا يُصنَّف الكيان N أو W
   ثم يحتاج تراجعاً عند اكتشاف تعارض لاحق لم يُرسَم له مسار.

بالإضافة إلى تصحيح مطبعي (٣/٣ ← ٣/٥ في جدول الثقة الأصلي) وسدّ الفجوة الإجرائية
التي أشرتَ إليها بنفسك بإضافة ACCEPT/REVIEW/REJECT كمرحلة أخيرة صريحة.

## بنية الملفات

| ملف | المرحلة | حالة الاختبار |
|---|---|---|
| `vocabulary.py` | SEARCH / CANDIDATE (الطبقات الثلاث) | مُختبَر ✓ (4/4 حالات) |
| `entity_resolution.py` | MATCH | مُختبَر ✓ (دمج صلب + حالة حدّية + رفض دمج خاطئ) |
| `rubric.py` | COMPARE / CONTRADICTION TEST / CLASSIFY / SCORE / GATE | مُختبَر ✓ (كل الحالات + الفجوات الثلاث المُصلَحة) |
| `retrieval.py` | SEARCH (BM25+Dense) | BM25 مُختبَر جزئياً محلياً؛ **الطبقة الكثيفة (embeddings) غير مُختبَرة هنا** — بيئة التطوير مقيَّدة الشبكة (مستودعات حزم فقط، لا huggingface.co)، فتراجع تلقائياً لِـ BM25 عند تعذّر تحميل النموذج. اختبرها عندك حيث الشبكة مفتوحة كاملة قبل الاعتماد عليها. |
| `db_writer.py` | ACCEPT/REVIEW/REJECT → PostgreSQL | مُختبَر تكاملياً ✓ ضد قاعدة حقيقية (35 بطاقة + 4 حالات جديدة، تحقّق مباشر بالاستعلام لا افتراضاً) |
| `pipeline.py` | التنسيق الكلي | مُختبَر تكاملياً ✓ |

## التشغيل

```bash
pip install rank_bm25 psycopg2-binary --break-system-packages
# اختياري للاسترجاع الكثيف (يحتاج شبكة مفتوحة لتحميل النموذج مرة واحدة):
pip install sentence-transformers --break-system-packages

export AQ_DB_HOST=localhost
export AQ_DB_NAME=sutoor_abdalqays   # القاعدة التي حمّلتَ عليها abd_alqays_schema_and_data.sql
export AQ_DB_USER=postgres
export AQ_DB_PASSWORD=...
```

```python
from entity_resolution import ExtractedPerson
from rubric import EvidenceItem, EvidenceCode, Relation
from pipeline import RawExtraction, run_pipeline

# كل RawExtraction يقابل مخرج JSON واحد ممّا أستخرجه أنا (Claude) من مقطع نصي واحد
batch = [
    RawExtraction(
        extracted_person=ExtractedPerson(canonical_name="...", kunya="...", geographical_mentions=["..."]),
        evidence=EvidenceItem(raw_quote="...", claim_type="Lineage", assigned_code=EvidenceCode.N1,
                               proposed_relation=Relation.N, source_meta={"title": "...", "author": "...",
                               "page": "...", "entry_number": "..."}),
    ),
    # ... بقية النتائج المُسترجَعة لنفس الاستعلام أو استعلامات متعددة
]

results = run_pipeline(batch, write_to_db=True)
for r in results:
    print(r.canonical_name, r.relation, r.evidence_code, r.confidence, r.gate)
```

## مراجعة `review_queue` يدوياً

كل ما لم يعبر بوابة ACCEPT ينتظر هنا — بما في ذلك مرشحات الدمج الحدّية
(الاكتشاف رقم 2 أعلاه)، ومعها `suggested_existing_person_id` إن وُجد تطابق
محتمل مع شخصية موجودة أصلاً، ليبدأ المراجع من هناك لا من الصفر:

```sql
SELECT review_id, canonical_name, proposed_relation, confidence_score,
       suggested_existing_person_id, raw_quote, source_meta
FROM review_queue WHERE status = 'pending' ORDER BY review_id;
```

الترقية اليدوية إلى الجداول الرئيسية بعد المراجعة تبقى قراراً بشرياً متعمَّداً —
لم تُضَف دالة "ترقية آلية" عمداً، اتساقاً مع مبدأ المشروع نفسه: لا يقرر الذكاء
الاصطناعي النسب مباشرة.
