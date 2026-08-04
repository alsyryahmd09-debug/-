/* ============================================================================
 * سُطور من أوال — محرّك «اسأل الأرشيف»
 * الملف (2/5): search-worker.js
 * المسؤولية: كلّ العمليات الثقيلة (توسعة الاستعلام، المطابقة التقريبية،
 *            حساب الصلة، الترتيب، استخراج المقتطفات) في خيط منفصل تماماً
 *            كي لا تتجمّد واجهة المستخدم مهما كبر الفهرس.
 * ==========================================================================*/
/* global importScripts, Sutoor */
'use strict';

importScripts('./search-index.js');

var Lang = Sutoor.Lang;
var Semantics = Sutoor.Semantics;

var IDX = null;          // الفهرس المستلَم
var BUCKETS = null;      // سلال المصطلحات لتسريع البحث التقريبي
var IDF = null;          // ذاكرة معامل الندرة

/* ---------------------------------------------------------------------------
 * التهيئة
 * -------------------------------------------------------------------------*/
function init(index) {
  IDX = index;
  IDF = Object.create(null);
  BUCKETS = Object.create(null);
  // سلّة لكلّ (أوّل حرف × الطول) — تقلّص مساحة البحث التقريبي من آلاف إلى عشرات
  for (var i = 0; i < IDX.terms.length; i++) {
    var t = IDX.terms[i];
    var k = t[0] + '|' + t.length;
    (BUCKETS[k] = BUCKETS[k] || []).push(t);
  }
}

function docFreq(term) {
  var p = IDX.postings[term];
  return p ? p.length / 2 : 0;
}

function idf(term) {
  if (IDF[term] !== undefined) return IDF[term];
  var N = IDX.docs.length, df = docFreq(term);
  var v = df ? Math.log(1 + (N - df + 0.5) / (df + 0.5)) : 0;
  return (IDF[term] = v);
}

/* ---------------------------------------------------------------------------
 * توسعة الاستعلام
 * كل مصطلح مرشَّح يحمل «جودة مطابقة» تدخل مباشرة في معادلة الترتيب:
 *   مطابق تام 1.00 | بادئة 0.80 | جذع 0.70 | مرادف تراثي 0.85 | مجاور 0.45
 *   تقريبي (خطأ إملائي) 0.60 مضروباً في نسبة التشابه
 * -------------------------------------------------------------------------*/
function lowerBound(arr, prefix) {
  var lo = 0, hi = arr.length;
  while (lo < hi) { var mid = (lo + hi) >> 1; if (arr[mid] < prefix) lo = mid + 1; else hi = mid; }
  return lo;
}

function prefixMatches(prefix, limit) {
  var out = [], i = lowerBound(IDX.terms, prefix);
  while (i < IDX.terms.length && IDX.terms[i].indexOf(prefix) === 0 && out.length < limit) {
    out.push(IDX.terms[i++]);
  }
  return out;
}

function fuzzyMatches(token) {
  var budget = Lang.fuzzyBudget(token.length);
  if (!budget) return [];
  var out = [];
  for (var d = -budget; d <= budget; d++) {
    var len = token.length + d;
    if (len < 2) continue;
    // نجرّب الحرف الأول كما هو، وأيضاً السلال المجاورة لالتقاط خطأ في أول حرف
    var bucket = BUCKETS[token[0] + '|' + len];
    if (!bucket) continue;
    for (var i = 0; i < bucket.length; i++) {
      var dist = Lang.editDistance(token, bucket[i], budget);
      if (dist <= budget && dist > 0) out.push({ term: bucket[i], dist: dist });
    }
  }
  out.sort(function (a, b) { return a.dist - b.dist; });
  return out.slice(0, 8);
}

function expandQuery(normQuery) {
  var tokens = Lang.tokenize(normQuery).filter(function (t) { return !Lang.isStop(t); });
  var cand = Object.create(null);   // term -> {q: جودة المطابقة, g: مجموعة المصطلح الأصلي}

  function offer(term, quality, group) {
    if (!IDX.postings[term]) return;
    var cur = cand[term];
    if (!cur || cur.q < quality) cand[term] = { q: quality, g: group };
  }

  tokens.forEach(function (tok, gi) {
    offer(tok, 1.0, gi);
    // بادئة (بحث جزئي أثناء الكتابة)
    if (tok.length >= 2) prefixMatches(tok, 12).forEach(function (t) {
      if (t !== tok) offer(t, 0.80 * (tok.length / t.length), gi);
    });
    // اشتقاق وتصريف
    var st = Lang.stem(tok);
    if (st !== tok) {
      offer(st, 0.72, gi);
      (IDX.stems[st] || []).forEach(function (t) { offer(t, 0.70, gi); });
    }
    (IDX.stems[tok] || []).forEach(function (t) { offer(t, 0.70, gi); });
    // تسامح إملائي
    fuzzyMatches(tok).forEach(function (m) {
      offer(m.term, 0.60 * (1 - m.dist / Math.max(3, tok.length)), gi);
    });
  });

  // الربط الدلالي التراثي (يعمل على الاستعلام كاملاً وعلى مفرداته)
  Semantics.expand(normQuery).forEach(function (e) {
    offer(e.term, e.weight, 's');
    if (e.weight >= 0.8) prefixMatches(e.term, 4).forEach(function (t) { offer(t, e.weight * 0.8, 's'); });
  });

  return { tokens: tokens, candidates: cand };
}

/* ---------------------------------------------------------------------------
 * معادلة الترتيب
 * Score = Σ_t [ idf(t) × tfNorm(t,d) × جودة_المطابقة ] × أهمية_القسم
 *         + مكافأة العبارة المتّصلة + مكافأة تطابق العنوان + مكافأة الحداثة
 * حيث tfNorm صيغة BM25 التي تكبح أثر التكرار وتعدّل لطول الوثيقة.
 * -------------------------------------------------------------------------*/
var K1 = 1.2, B = 0.6;

function search(q, opts) {
  opts = opts || {};
  var limit = opts.limit || 40;
  var normQ = Lang.normalize(q);
  if (!normQ) return { hits: [], total: 0, facets: {}, terms: [] };

  var ex = expandQuery(normQ);
  var cand = ex.candidates;
  var terms = Object.keys(cand);
  if (!terms.length) return { hits: [], total: 0, facets: {}, terms: [], suggestion: suggest(normQ) };

  var scores = Object.create(null);
  var matched = Object.create(null);   // docId -> {term:1}
  var groups = Object.create(null);    // docId -> {groupIndex:1} لقياس تغطية الاستعلام

  terms.forEach(function (t) {
    var post = IDX.postings[t];
    if (!post) return;
    var w = idf(t) * cand[t].q;
    if (w <= 0) return;
    for (var i = 0; i < post.length; i += 2) {
      var id = post[i], wtf = post[i + 1];
      var dl = IDX.docs[id].l;
      var tfNorm = (wtf * (K1 + 1)) / (wtf + K1 * (1 - B + B * (dl / IDX.avgLen)));
      scores[id] = (scores[id] || 0) + w * tfNorm;
      (matched[id] = matched[id] || Object.create(null))[t] = 1;
      (groups[id] = groups[id] || Object.create(null))[cand[t].g] = 1;
    }
  });

  var ids = Object.keys(scores);
  var now = Date.now(), YEAR = 31557600000;
  var results = [];

  for (var j = 0; j < ids.length; j++) {
    var id = +ids[j];
    var d = IDX.docs[id];
    if (opts.section && d.s !== opts.section) continue;
    if (opts.type && d.y !== opts.type) continue;

    var s = scores[id];

    // تغطية الاستعلام: الوثيقة التي طابقت كلمات الاستعلام كلّها تتقدّم
    var need = ex.tokens.length || 1;
    var got = Object.keys(groups[id]).filter(function (g) { return g !== 's'; }).length;
    // الوثيقة التي طابقت عبر المرادف الدلالي وحده تُخفَّض بوضوح أمام
    // الوثيقة التي طابقت ما كتبه المستخدم فعلاً.
    s *= (got === 0 ? 0.35 : (0.55 + 0.45 * Math.min(1, got / need)));

    // العبارة المتّصلة حرفياً
    if (need > 1 && d.n.indexOf(normQ) !== -1) s *= 1.6;

    // العنوان: تطابق تام ثمّ بادئة
    var nt = Lang.normalize(d.t);
    if (nt === normQ) s *= 2.2;
    else if (nt.indexOf(normQ) === 0) s *= 1.7;
    else if (nt.indexOf(normQ) !== -1) s *= 1.35;

    // أهمية القسم وحداثة التحديث
    s *= (d.r || 1);
    if (d.m) s *= 1 + Math.max(0, 0.12 * (1 - (now - d.m) / (3 * YEAR)));

    results.push({ id: id, score: s, terms: Object.keys(matched[id]) });
  }

  results.sort(function (a, b) { return b.score - a.score; });

  // عتبة الصلة: التوسعة الدلالية تلتقط أحياناً مجاورات ضعيفة جداً،
  // فتُقصى النتائج التي لا تبلغ نسبة معتبرة من أعلى نتيجة.
  if (results.length > 1) {
    var floor = results[0].score * 0.06;
    var cut = results.length;
    for (var f = 1; f < results.length; f++) {
      if (results[f].score < floor) { cut = f; break; }
    }
    results.length = Math.max(1, cut);
  }
  var total = results.length;

  // إحصاء الأقسام لواجهة التصفية (يُحسب على النتائج كلّها لا على المعروض)
  var facets = Object.create(null);
  results.forEach(function (r) {
    var sname = IDX.docs[r.id].s;
    facets[sname] = (facets[sname] || 0) + 1;
  });

  var hits = results.slice(0, limit).map(function (r) {
    var d = IDX.docs[r.id];
    return {
      id: d.i,
      title: d.t,
      section: d.s,
      type: d.y,
      url: d.u,
      img: d.g,
      score: +r.score.toFixed(3),
      terms: displayTerms(r.terms, cand),
      snippet: snippet(d, r.terms, normQ)
    };
  });

  return {
    hits: hits, total: total, facets: facets,
    terms: terms.filter(function (t) { return cand[t].q >= 0.6; }).slice(0, 20),
    suggestion: total ? null : suggest(normQ)
  };
}

/**
 * مصطلحات التظليل: ما كتبه المستخدم واشتقاقاته وتصحيحاته فقط.
 * المرادفات الدلالية تُستعمل في الترتيب ولا تُظلَّل كي لا يمتلئ النصّ بعلامات
 * لا صلة لها بما كُتب — إلا إن لم يبقَ ما يُظلَّل فتُستعمل المرادفات القويّة.
 */
function displayTerms(terms, cand) {
  var own = terms.filter(function (t) {
    return t.length >= 3 && cand[t] && cand[t].q >= 0.45 && cand[t].g !== 's';
  });
  if (!own.length) {
    own = terms.filter(function (t) { return t.length >= 3 && cand[t] && cand[t].q >= 0.85; });
  }
  return own.slice(0, 12);
}

/* ---------------------------------------------------------------------------
 * المقتطف: يُختار المقطع الأصلي (غير المطبَّع) الذي يحوي أكثر كلمات مطابقة
 * -------------------------------------------------------------------------*/
function snippet(doc, terms, normQ) {
  var source = doc.b || doc.d || '';
  if (!source) return doc.d || '';
  // تقسيم إلى جُمل دون الاعتماد على lookbehind (غير مدعوم في متصفحات أقدم)
  var chunks = source.replace(/([\.\!\?،؛:])\s+/g, '$1\u0001').split(/\u0001|\n+/)
    .filter(function (c) { return c.trim().length > 20; });
  if (!chunks.length) chunks = [source];

  var best = null, bestScore = -1;
  for (var i = 0; i < chunks.length && i < 60; i++) {
    var n = Lang.normalize(chunks[i]);
    var sc = 0;
    if (normQ && n.indexOf(normQ) !== -1) sc += 5;
    for (var j = 0; j < terms.length; j++) if (n.indexOf(terms[j]) !== -1) sc += 1;
    if (sc > bestScore) { bestScore = sc; best = chunks[i]; }
  }
  var out = (bestScore > 0 ? best : (doc.d || chunks[0] || '')).trim();
  return out.length > 260 ? out.slice(0, 257).replace(/\s+\S*$/, '') + '…' : out;
}

/* ---------------------------------------------------------------------------
 * «هل تقصد؟» عند انعدام النتائج
 * -------------------------------------------------------------------------*/
function suggest(normQ) {
  var tokens = Lang.tokenize(normQ);
  if (!tokens.length) return null;
  var out = [], changed = false;
  tokens.forEach(function (tok) {
    if (IDX.postings[tok]) { out.push(tok); return; }
    var m = fuzzyMatches(tok);
    if (m.length) {
      // نرجّح الأشيع بين المرشّحات المتساوية في المسافة
      m.sort(function (a, b) { return (a.dist - b.dist) || (docFreq(b.term) - docFreq(a.term)); });
      out.push(m[0].term); changed = true;
    } else out.push(tok);
  });
  return changed ? out.join(' ') : null;
}

/* ---------------------------------------------------------------------------
 * بروتوكول الرسائل
 * -------------------------------------------------------------------------*/
self.onmessage = function (e) {
  var msg = e.data || {};
  try {
    if (msg.type === 'init') {
      init(msg.index);
      self.postMessage({ type: 'ready', count: IDX.docs.length, sections: IDX.sections });
      return;
    }
    if (!IDX) { self.postMessage({ type: 'error', reason: 'الفهرس غير مُهيَّأ بعد' }); return; }

    if (msg.type === 'query') {
      var t0 = (self.performance && performance.now()) || Date.now();
      var res = search(msg.q, msg.opts);
      res.type = 'results';
      res.rid = msg.rid;
      res.q = msg.q;
      res.ms = +(((self.performance && performance.now()) || Date.now()) - t0).toFixed(1);
      self.postMessage(res);
      return;
    }
    if (msg.type === 'page') {   // صفحة نتائج إضافية دون إعادة الحساب الكامل
      var r = search(msg.q, Object.assign({}, msg.opts, { limit: (msg.opts && msg.opts.limit) || 200 }));
      r.type = 'results';
      r.rid = msg.rid;
      r.q = msg.q;
      self.postMessage(r);
    }
  } catch (err) {
    self.postMessage({ type: 'error', rid: msg.rid, reason: String(err && err.message || err) });
  }
};
