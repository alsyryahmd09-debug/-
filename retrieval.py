"""
retrieval.py — محرك الاسترجاع الهجين (BM25 + Dense) — المرحلة SEARCH
=========================================================================
BM25 (rank_bm25) يعمل بلا اتصال شبكي — جُرِّب فعلياً في بيئة التطوير.
الفهرسة الكثيفة (Dense/embeddings) تحتاج تحميل نموذج (sentence-transformers)
من الإنترنت؛ بيئة التطوير هنا مقيَّدة الشبكة (مستودعات الحزم فقط، لا
huggingface.co) فلم يتسنَّ اختبار هذا الجزء فعلياً — لذا هو "soft-import"
يتراجع تلقائياً إلى BM25 فقط إن تعذّر تحميل النموذج. اختبره عندك محلياً
حيث الشبكة مفتوحة قبل الاعتماد عليه.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import re

from rank_bm25 import BM25Okapi

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    _DENSE_AVAILABLE = True
except ImportError:
    _DENSE_AVAILABLE = False


def _tokenize_ar(text: str) -> list[str]:
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)  # إزالة التشكيل
    return re.findall(r"[\u0600-\u06FF]+|\w+", text)


@dataclass
class CorpusDoc:
    doc_id: str
    text: str
    source_meta: dict  # title/author/publisher_editor/edition/volume/page/entry_number


class HybridRetriever:
    def __init__(self, docs: list[CorpusDoc], dense_model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.docs = docs
        self._tokenized = [_tokenize_ar(d.text) for d in docs]
        self.bm25 = BM25Okapi(self._tokenized)

        self.dense_ready = False
        if _DENSE_AVAILABLE:
            try:
                self._model = SentenceTransformer(dense_model_name)
                self._doc_vecs = self._model.encode([d.text for d in docs], normalize_embeddings=True)
                self.dense_ready = True
            except Exception:
                self.dense_ready = False  # فشل تحميل النموذج (لا اتصال، إلخ) — رجوع تلقائي لـ BM25 فقط

    def search(self, query: str, top_k: int = 10, bm25_weight: float = 0.5) -> list[tuple[CorpusDoc, float]]:
        bm25_scores = self.bm25.get_scores(_tokenize_ar(query))
        max_bm25 = max(bm25_scores) if len(bm25_scores) and max(bm25_scores) > 0 else 1.0
        norm_bm25 = [s / max_bm25 for s in bm25_scores]

        if self.dense_ready:
            q_vec = self._model.encode([query], normalize_embeddings=True)[0]
            dense_scores = self._doc_vecs @ q_vec  # جيب التمام (متجهات مطبَّعة)
            combined = [bm25_weight * b + (1 - bm25_weight) * float(d)
                        for b, d in zip(norm_bm25, dense_scores)]
        else:
            combined = norm_bm25  # BM25 فقط عند تعذّر التحميل

        ranked = sorted(zip(self.docs, combined), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
