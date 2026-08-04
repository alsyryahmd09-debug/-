/* ============================================================================
 * سُطور من أوال — محرّك «اسأل الأرشيف»
 * الملف (1/5): search-index.js
 * المسؤولية: وحدة اللغة (تطبيع/تقطيع/اشتقاق) + الخريطة الدلالية + بناء الفهرس
 *
 * ملاحظة معمارية مهمّة:
 * هذا الملف يعمل في بيئتين: نافذة المتصفح (window) وخيط العامل (Worker).
 * لذلك كل ما يمسّ الـDOM محصور داخل SutoorIndexer ولا يُنفَّذ عند التحميل،
 * ويستدعيه العامل عبر importScripts ليستعمل وحدة اللغة وحدها.
 * لا اعتماد خارجيّ إطلاقاً: صفر مكتبات، صفر واجهات برمجية بعيدة.
 * ==========================================================================*/
(function (root) {
  'use strict';

  var Sutoor = (root.Sutoor = root.Sutoor || {});
  var INDEX_VERSION = '3.0.0';

  /* ==========================================================================
   * 1) وحدة اللغة — SutoorLang
   * ========================================================================*/
  var Lang = (function () {

    // الحركات والتشكيل والعلامات القرآنية والتطويل
    var RE_DIACRITICS = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u08D3-\u08E1\u08E3-\u08FF\u0640]/g;
    // الفواصل والرموز (يُستبدل بفراغ لا بحذف كي لا تلتصق الكلمات)
    var RE_PUNCT = /[!-\/:-@\[-`{-~\u00A0\u060C\u061B\u061F\u066A-\u066D\u06D4\u2000-\u206F\u2E00-\u2E7F«»‹›؛…ـ]/g;
    var RE_SPACES = /\s+/g;

    // تطبيع الأحرف العربية + الأرقام الهندية
    var CHAR_MAP = {
      'أ':'ا','إ':'ا','آ':'ا','ٱ':'ا','ء':'',
      'ى':'ي','ئ':'ي','ؤ':'و','ة':'ه',
      'گ':'ك','ک':'ك','چ':'ج','پ':'ب','ژ':'ز','ڤ':'ف','ی':'ي',
      '٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9',
      '۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9'
    };

    // كلمات وقف: لا تُفهرس ولا تُوزن (عربية + إنجليزية)
    var STOP = Object.create(null);
    ('في من على الى إلى عن مع هذا هذه ذلك تلك التي الذي الذين اللاتي كان كانت يكون قد لقد ثم او أو ' +
     'ام أم لا ما لم لن ان أن إن انه أنه هو هي هم هن نحن انت أنت بين بعد قبل عند حتى كل بعض غير سوى ' +
     'حيث لدى منذ خلال ضمن دون ايضا أيضا كما بها به لها له وهو وهي ' +
     'the a an of in on at to for and or but is are was were be been by with from that this these those it as').
      split(' ').forEach(function (w) { STOP[w] = 1; });

    /** التطبيع الكامل: يُستعمل للفهرسة وللاستعلام على السواء. */
    function normalize(text) {
      if (!text) return '';
      var s = String(text);
      if (s.normalize) s = s.normalize('NFKC');
      s = s.toLowerCase().replace(RE_DIACRITICS, '');
      var out = '', ch;
      for (var i = 0; i < s.length; i++) {
        ch = s[i];
        out += (CHAR_MAP[ch] !== undefined ? CHAR_MAP[ch] : ch);
      }
      return out.replace(RE_PUNCT, ' ').replace(RE_SPACES, ' ').trim();
    }

    /** تقطيع النصّ المطبَّع إلى وحدات دلالية. */
    function tokenize(normalized) {
      if (!normalized) return [];
      var raw = normalized.split(' '), out = [];
      for (var i = 0; i < raw.length; i++) {
        var t = raw[i];
        if (t.length < 2 && !/^\d+$/.test(t)) continue;
        if (t.length > 40) t = t.slice(0, 40);
        out.push(t);
      }
      return out;
    }

    function isStop(token) { return STOP[token] === 1; }

    // ---- الاشتقاق العربي الخفيف (Light Stemming) ----
    var AR_PREFIX = ['والت','فالت','بالت','كالت','وال','فال','بال','كال','لال','ولل','الت','ال','لل','و','ف','ب','ك','ل','س'];
    var AR_SUFFIX = ['اتهما','اتهم','اتكم','اتها','تهما','هما','كما','تين','هم','هن','كم','كن','نا','ها','ية','ات','ون','ين','ان','تي','ه','ة','ي','ا'];

    function stemArabic(t) {
      var w = t, i;
      for (i = 0; i < AR_PREFIX.length; i++) {
        var p = AR_PREFIX[i];
        if (w.length - p.length >= 3 && w.indexOf(p) === 0) { w = w.slice(p.length); break; }
      }
      for (i = 0; i < AR_SUFFIX.length; i++) {
        var s = AR_SUFFIX[i];
        if (w.length - s.length >= 3 && w.slice(-s.length) === s) { w = w.slice(0, -s.length); break; }
      }
      return w;
    }

    function stemEnglish(t) {
      if (t.length < 4) return t;
      if (/ies$/.test(t)) return t.slice(0, -3) + 'y';
      if (/(sses|shes|ches|xes)$/.test(t)) return t.slice(0, -2);
      if (/ing$/.test(t) && t.length > 5) return t.slice(0, -3);
      if (/ed$/.test(t) && t.length > 4) return t.slice(0, -2);
      if (/ly$/.test(t) && t.length > 4) return t.slice(0, -2);
      if (/s$/.test(t) && !/ss$/.test(t)) return t.slice(0, -1);
      return t;
    }

    /** جذع موحّد يختار المعالج حسب نظام الكتابة. */
    function stem(token) {
      if (!token) return token;
      return /[\u0600-\u06FF]/.test(token) ? stemArabic(token) : stemEnglish(token);
    }

    /** مسافة ليفنشتاين بحدّ أقصى مع خروج مبكّر — لدعم التسامح الإملائي. */
    function editDistance(a, b, max) {
      if (a === b) return 0;
      var la = a.length, lb = b.length;
      if (Math.abs(la - lb) > max) return max + 1;
      var prev = new Array(lb + 1), cur = new Array(lb + 1), i, j;
      for (j = 0; j <= lb; j++) prev[j] = j;
      for (i = 1; i <= la; i++) {
        cur[0] = i;
        var best = cur[0];
        for (j = 1; j <= lb; j++) {
          var cost = a.charCodeAt(i - 1) === b.charCodeAt(j - 1) ? 0 : 1;
          cur[j] = Math.min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
          if (cur[j] < best) best = cur[j];
        }
        if (best > max) return max + 1;
        for (j = 0; j <= lb; j++) prev[j] = cur[j];
      }
      return prev[lb];
    }

    /** حدّ التسامح المسموح به بحسب طول الكلمة. */
    function fuzzyBudget(len) {
      if (len <= 3) return 0;
      if (len <= 5) return 1;
      return 2;
    }

    return {
      normalize: normalize, tokenize: tokenize, stem: stem, isStop: isStop,
      editDistance: editDistance, fuzzyBudget: fuzzyBudget
    };
  })();

  /* ==========================================================================
   * 2) الخريطة الدلالية — شبكة المفاهيم التراثية
   *    terms  : مسمّيات المفهوم نفسه (مطابقة قويّة 0.85)
   *    related: ما يجاوره في شبكة المعرفة (مطابقة ضعيفة 0.45)
   *    قابلة للتوسعة من الخارج عبر Sutoor.Semantics.extend([...])
   * ========================================================================*/
  var CONCEPTS = [
    { id:'khamis', terms:['مسجد الخميس','جامع الخميس','الخميس','khamis mosque'],
      related:['بلاد القديم','عمر بن عبد العزيز','نقش المنارة','الوقفية','مونيك كيرفران','البعثة الفرنسية','المنارتان'] },
    { id:'dilmun', terms:['دلمون','تايلوس','أوال','اوال','البحرين القديمة','dilmun','tylos','awal'],
      related:['تلال المدافن','عالي','قلعة البحرين','اليونسكو','التراث العالمي','الألف الثالث'] },
    { id:'burial-mounds', terms:['تلال مدافن دلمون','تلال المدافن','مدافن عالي','burial mounds'],
      related:['عالي','اليونسكو','1750 ق م','2050 ق م','حجر ديوراند','التنقيبات'] },
    { id:'uyunid', terms:['العيونيون','الدولة العيونية','العيوني','بنو عيون','uyunid','uyunids'],
      related:['عبد الله بن علي العيوني','ابن المقرب','القرامطة','469هـ','636هـ','المديرس','أبو البهلول','الأحساء','القطيف'] },
    { id:'ibn-muqarrab', terms:['ابن المقرب','ابن المقرب العيوني','ديوان ابن المقرب','شرح ديوان ابن المقرب'],
      related:['780هـ','الدولة العيونية','وقفية البديع','الشراع','فضل بن فاضل'] },
    { id:'abdulqais', terms:['عبد القيس','عبدالقيس','بنو عبد القيس','abd al-qays'],
      related:['جواثى','هجر','تهامة','الردة','الوفود','ربيعة','المنذر بن ساوى'] },
    { id:'samahij', terms:['سماهيج','ميشماهيج','سماهيچ','samahij','mashmahig'],
      related:['كنيسة المشرق','الوجود المسيحي','تيموثي إنسول','سلمان المحاري','جامعة إكستر','الأنصاري','2024'] },
    { id:'ansari', terms:['عبد الله بن محمود الأنصاري','الأنصاري السماهيجي','الأنصاري المالكي'],
      related:['المذهب المالكي','سماهيج','الروض الزاهر','سليمان المهري','943هـ'] },
    { id:'zubarah', terms:['الزبارة','قلعة صبحا','قلعة مرير','zubarah'],
      related:['آل خليفة','أحمد الفاتح','1762','1783','فتح البحرين','الرفاع','قطر'] },
    { id:'alkhalifa', terms:['آل خليفة','ال خليفة','أحمد الفاتح','al khalifa'],
      related:['الزبارة','قلعة الرفاع','1783','وثيقة العهد والبيعة','لوريمر'] },
    { id:'manuscripts', terms:['المخطوطات','مخطوط','مخطوطة','فهرس المخطوطات','manuscript','manuscripts'],
      related:['الناسخ','النسخة','الحماسة','الفوائد','القويصل','العُدة','الروض الزاهر','التحقيق','الوقفية'] },
    { id:'ibn-majid', terms:['أحمد بن ماجد','ابن ماجد','الفوائد','ibn majid'],
      related:['895هـ','أوال','البحرين','الملاحة','البحار'] },
    { id:'ansab', terms:['الأنساب','سطور الأنساب','شجرة العائلة','النسب','مشجرة','genealogy','family tree'],
      related:['العبدلي الرفاعي','السبطين','الزبدة','العُدة','القبيلة','الأجيال'] },
    { id:'abdali', terms:['العبدلي الرفاعي','علي أبو الحسن العبدلي','السيد ماجد العبدلي'],
      related:['848هـ','نقيب البحرين','الزبدة','العُدة','السبطين','الأنساب'] },
    { id:'qalat', terms:['قلعة البحرين','قلعة الرفاع','قلعة عراد','fort','qalat al-bahrain'],
      related:['البعثة الفرنسية','1977','1979','التنقيب','الحصن'] },
    { id:'inscriptions', terms:['النقوش','نقش','النقش','inscription','inscriptions'],
      related:['المنارة','724هـ','الوقفية','776هـ','متحف البحرين','الشاهد المؤرَّخ'] },
    { id:'archive', terms:['اسأل الأرشيف','الأرشيف الموثق','الأرشيف','archive'],
      related:['البحث','المصادر','المراجع','قاعدة البيانات','التوثيق'] },
    { id:'timeline', terms:['الخط الزمني','الخطّ الزمني','العصور','timeline'],
      related:['الأحداث','التأريخ','الحقبة','العصر'] },
    { id:'library', terms:['المكتبة الأكاديمية','المكتبة','الأبحاث','library'],
      related:['الدوريات','الرسائل الجامعية','المحكّمة','الاستشهاد'] }
  ];

  var Semantics = (function () {
    var byTerm = null;           // مصطلح مطبَّع -> [{id, kind}]
    var byId = Object.create(null);
    var list = CONCEPTS.slice();

    function build() {
      byTerm = Object.create(null);
      byId = Object.create(null);
      list.forEach(function (c) {
        byId[c.id] = c;
        (c.terms || []).forEach(function (t) { push(Lang.normalize(t), c.id); });
      });
      function push(k, id) {
        if (!k) return;
        (byTerm[k] = byTerm[k] || []).push(id);
        // فهرسة الكلمة المفردة أيضاً كي تلتقط «الخميس» من «مسجد الخميس»
        var parts = k.split(' ');
        if (parts.length > 1) parts.forEach(function (p) {
          if (p.length > 2 && !Lang.isStop(p)) (byTerm[p] = byTerm[p] || []).push(id);
        });
      }
    }

    /** توسعة الاستعلام: يعيد [{term, weight}] لكل ما يرتبط بالمدخل دلالياً. */
    function expand(normalizedQuery) {
      if (!byTerm) build();
      var seen = Object.create(null), out = [], hitIds = Object.create(null);
      var keys = [normalizedQuery].concat(normalizedQuery.split(' '));
      keys.forEach(function (k) {
        var ids = byTerm[k];
        if (ids) ids.forEach(function (id) { hitIds[id] = 1; });
      });
      Object.keys(hitIds).forEach(function (id) {
        var c = byId[id];
        (c.terms || []).forEach(function (t) { add(t, 0.85); });
        (c.related || []).forEach(function (t) { add(t, 0.45); });
      });
      function add(text, w) {
        var n = Lang.normalize(text);
        n.split(' ').forEach(function (tok) {
          if (!tok || tok.length < 2 || Lang.isStop(tok)) return;
          if (seen[tok] && seen[tok] >= w) return;
          seen[tok] = w;
        });
      }
      Object.keys(seen).forEach(function (t) { out.push({ term: t, weight: seen[t] }); });
      return out;
    }

    return {
      expand: expand,
      concepts: function () { return list; },
      extend: function (extra) { list = list.concat(extra || []); byTerm = null; }
    };
  })();

  /* ==========================================================================
   * 3) بانِي الفهرس — SutoorIndexer (يعمل في النافذة فقط)
   * ========================================================================*/

  // أوزان الحقول: كلّما ارتفعت زاد أثر المطابقة فيها على الترتيب
  var FIELD_WEIGHT = { title: 8, keywords: 5, section: 3.5, heading: 2.5, desc: 2, body: 1, alt: 1.5 };

  // أهمية القسم في معادلة الترتيب (تُقرأ من data-sutoor-rank أو من هذه الخريطة)
  var SECTION_RANK = {
    'المعالم': 1.25, 'المخطوطات': 1.25, 'فهرس المخطوطات': 1.25,
    'الخط الزمني': 1.15, 'عبد القيس والعيونيون': 1.15, 'الشخصيات': 1.2,
    'المكتبة الأكاديمية': 1.1, 'سطور الأنساب': 1.1, 'الرئيسية': 1.0,
    'من نحن': 0.85, 'تواصل': 0.7
  };

  function SutoorIndexer(config) {
    this.cfg = Object.assign({
      // العناصر التي تُفهرَس تلقائياً دون أيّ تعديل على الكود عند إضافة صفحات جديدة
      roots: '[data-sutoor-index], section[id], article, .card, .manuscript-card, .landmark-card, .era-card, .person-card, details',
      sources: [],            // ملفات JSON خارجية (مسارات نسبية داخل الموقع)
      cacheKey: 'sutoor.index.v' + INDEX_VERSION,
      cacheTTL: 1000 * 60 * 60 * 12,
      maxBodyChars: 4000
    }, config || {});
    this.docs = [];
    this._seen = Object.create(null);
  }

  /** توليد معرّف ثابت للوثيقة لتفادي التكرار بين مصادر متعدّدة. */
  SutoorIndexer.prototype._key = function (d) {
    return (d.url || '') + '|' + (d.title || '').slice(0, 80);
  };

  SutoorIndexer.prototype._push = function (d) {
    if (!d || !d.title) return;
    var text = [d.title, d.section, d.keywords, d.desc, d.body].filter(Boolean).join(' ');
    if (Lang.normalize(text).length < 8) return;
    var k = this._key(d);
    if (this._seen[k]) {                       // دمج بدل التكرار
      var prev = this._seen[k];
      if ((d.body || '').length > (prev.body || '').length) prev.body = d.body;
      if (!prev.img && d.img) prev.img = d.img;
      return;
    }
    this._seen[k] = d;
    this.docs.push(d);
  };

  /** (أ) الزحف على الـDOM — يلتقط البطاقات والأقسام والنوافذ والجداول. */
  SutoorIndexer.prototype.collectDOM = function (scope) {
    if (typeof document === 'undefined') return;
    var self = this;
    var root = scope || document;
    var nodes = root.querySelectorAll(this.cfg.roots);
    var pageTitle = (document.title || '').split('—')[0].trim();

    Array.prototype.forEach.call(nodes, function (el) {
      if (el.closest('[data-sutoor-skip]') || el.closest('.sutoor-modal')) return;
      // حاوية تضمّ وحدات فهرسة أصغر لا تُفهرَس بنفسها (تفادياً لتكرار النتيجة)،
      // إلا إن أُعلنت صراحةً بـ data-sutoor-index.
      if (!el.hasAttribute('data-sutoor-index') && el.querySelector(self.cfg.roots)) return;

      var ds = el.dataset || {};
      var headEl = el.querySelector('h1,h2,h3,h4,.card-title,.title,summary,legend');
      var title = (ds.sutoorTitle || (headEl && headEl.textContent) || el.getAttribute('aria-label') || '').trim();
      if (!title) return;

      var section = (ds.sutoorSection ||
        (el.closest('section[id]') && (el.closest('section[id]').dataset.sutoorSection ||
          (el.closest('section[id]').querySelector('h1,h2') || {}).textContent)) ||
        pageTitle || 'المنصّة').trim();

      var headings = Array.prototype.map.call(el.querySelectorAll('h2,h3,h4,h5,dt,th'), function (h) {
        return h.textContent.trim();
      }).join(' · ');

      var body = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      if (body.length > self.cfg.maxBodyChars) body = body.slice(0, self.cfg.maxBodyChars);

      var alts = Array.prototype.map.call(el.querySelectorAll('img'), function (im) {
        return (im.getAttribute('alt') || '') + ' ' + (im.getAttribute('title') || '');
      }).join(' ').trim();

      var thumb = ds.sutoorThumb || (el.querySelector('img') && el.querySelector('img').getAttribute('src')) || '';

      var anchor = el.id ? '#' + el.id : (el.closest('[id]') ? '#' + el.closest('[id]').id : '');
      var url = ds.sutoorUrl || (el.tagName === 'A' ? el.getAttribute('href') : '') || (location.pathname + anchor);

      self._push({
        title: title,
        section: section,
        type: ds.sutoorType || self._guessType(el, section),
        url: url,
        desc: (ds.sutoorDesc || body.slice(0, 220)),
        heading: headings,
        keywords: ds.sutoorKeywords || '',
        alt: alts,
        body: body,
        img: thumb,
        updated: ds.sutoorUpdated || '',
        rank: parseFloat(ds.sutoorRank || '') || SECTION_RANK[section] || 1,
        domId: el.id || ''
      });
    });
  };

  SutoorIndexer.prototype._guessType = function (el, section) {
    var c = (el.className || '') + ' ' + section;
    if (/manuscript|مخطوط/i.test(c)) return 'مخطوطة';
    if (/landmark|معلم|معالم/i.test(c)) return 'معلم';
    if (/person|شخصي/i.test(c)) return 'شخصية';
    if (/era|timeline|زمني|حدث/i.test(c)) return 'حدث';
    if (/ansab|نسب|أنساب/i.test(c)) return 'نسب';
    if (/library|مكتب|بحث/i.test(c)) return 'مرجع';
    return 'صفحة';
  };

  /** (ب) بيانات JSON-LD المضمَّنة — تُقرأ ككيانات معرفية مستقلّة. */
  SutoorIndexer.prototype.collectJSONLD = function () {
    if (typeof document === 'undefined') return;
    var self = this;
    Array.prototype.forEach.call(document.querySelectorAll('script[type="application/ld+json"]'), function (s) {
      try { self.ingestJSON(JSON.parse(s.textContent), 'البيانات المنظَّمة'); } catch (e) { /* تجاهل الكتلة التالفة */ }
    });
  };

  /** (ج) كتل JSON المضمَّنة داخل الصفحة. */
  SutoorIndexer.prototype.collectInlineJSON = function () {
    if (typeof document === 'undefined') return;
    var self = this;
    Array.prototype.forEach.call(document.querySelectorAll('script[type="application/json"][data-sutoor-source]'), function (s) {
      try { self.ingestJSON(JSON.parse(s.textContent), s.dataset.sutoorSection || 'قاعدة البيانات'); } catch (e) {}
    });
  };

  /** (د) ملفات JSON خارجية داخل الموقع نفسه (بدون أيّ خدمة بعيدة). */
  SutoorIndexer.prototype.collectRemote = function () {
    var self = this;
    var list = this.cfg.sources.slice();
    if (typeof document !== 'undefined') {
      var meta = document.querySelector('meta[name="sutoor-sources"]');
      if (meta) list = list.concat(meta.content.split(',').map(function (s) { return s.trim(); }).filter(Boolean));
    }
    if (!list.length || typeof fetch !== 'function') return Promise.resolve();
    return Promise.all(list.map(function (u) {
      return fetch(u, { cache: 'force-cache' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j) self.ingestJSON(j, 'قاعدة البيانات'); })
        .catch(function () { /* المصدر غير متاح: يُتخطّى بصمت */ });
    }));
  };

  /** مُستوعِب عامّ لأيّ شكل JSON: كائن، مصفوفة، @graph، أو خريطة أقسام. */
  SutoorIndexer.prototype.ingestJSON = function (data, section) {
    var self = this;
    if (!data) return;
    if (Array.isArray(data)) { data.forEach(function (x) { self.ingestJSON(x, section); }); return; }
    if (typeof data !== 'object') return;
    if (data['@graph']) { self.ingestJSON(data['@graph'], section); return; }

    var title = data.title || data.name || data.headline || data['@id'] || data.العنوان || data.الاسم;
    if (title && typeof title === 'string') {
      var body = [];
      Object.keys(data).forEach(function (k) {
        if (/^@/.test(k)) return;
        var v = data[k];
        if (typeof v === 'string' || typeof v === 'number') body.push(v);
        else if (Array.isArray(v)) v.forEach(function (x) { if (typeof x === 'string') body.push(x); });
      });
      self._push({
        title: String(title),
        section: data.section || data.القسم || section,
        type: data.type || data['@type'] || data.النوع || 'سجلّ',
        url: data.url || data.link || data.الرابط || '',
        desc: String(data.description || data.abstract || data.الوصف || body.slice(1, 3).join(' ')).slice(0, 220),
        heading: '',
        keywords: [].concat(data.keywords || data.tags || data.الكلمات || []).join(' '),
        alt: '',
        body: body.join(' ').slice(0, self.cfg.maxBodyChars),
        img: data.image || data.thumbnail || data.الصورة || '',
        updated: data.dateModified || data.updated || data.التاريخ || '',
        rank: parseFloat(data.rank) || SECTION_RANK[data.section] || 1
      });
    }
    // النزول إلى الحقول المركَّبة (مثل: {معالم:[...], مخطوطات:[...]})
    Object.keys(data).forEach(function (k) {
      var v = data[k];
      if (v && typeof v === 'object' && !/^@/.test(k)) self.ingestJSON(v, /[\u0600-\u06FF]/.test(k) ? k : section);
    });
  };

  /* ---------- بناء الفهرس المقلوب ---------- */

  /**
   * ينتج بنية مسطّحة قابلة للنقل إلى الـWorker عبر postMessage:
   * { v, docs[], terms[], postings{term:[docId,wtf,...]}, stems{stem:[terms]}, avgLen, sections{} }
   */
  SutoorIndexer.prototype.build = function () {
    var postings = Object.create(null);
    var stems = Object.create(null);
    var sections = Object.create(null);
    var docs = [], totalLen = 0;

    this.docs.forEach(function (d, id) {
      var fields = {
        title: d.title, keywords: d.keywords, section: d.section,
        heading: d.heading, desc: d.desc, alt: d.alt, body: d.body
      };
      var acc = Object.create(null), len = 0;

      Object.keys(fields).forEach(function (f) {
        var toks = Lang.tokenize(Lang.normalize(fields[f] || ''));
        var w = FIELD_WEIGHT[f] || 1;
        toks.forEach(function (t) {
          if (Lang.isStop(t)) return;
          len++;
          acc[t] = (acc[t] || 0) + w;
          var st = Lang.stem(t);
          if (st !== t && st.length >= 3) {
            (stems[st] = stems[st] || []);
            if (stems[st].indexOf(t) === -1) stems[st].push(t);
          }
        });
      });

      Object.keys(acc).forEach(function (t) {
        (postings[t] = postings[t] || []).push(id, +acc[t].toFixed(2));
      });

      sections[d.section] = (sections[d.section] || 0) + 1;
      totalLen += len || 1;

      docs.push({
        i: id,
        t: d.title,
        s: d.section,
        y: d.type,
        u: d.url,
        d: d.desc,
        b: String(d.body || '').slice(0, 1600),
        g: d.img,
        r: d.rank || 1,
        m: d.updated ? (Date.parse(d.updated) || 0) : 0,
        n: Lang.normalize([d.title, d.section, d.keywords, d.heading, d.desc, d.body].join(' ')).slice(0, 6000),
        l: len || 1
      });
    });

    return {
      v: INDEX_VERSION,
      built: Date.now(),
      docs: docs,
      terms: Object.keys(postings).sort(),
      postings: postings,
      stems: stems,
      sections: sections,
      avgLen: totalLen / Math.max(1, docs.length)
    };
  };

  /** المسار الكامل: جمع من كلّ المصادر ثمّ بناء الفهرس (مع ذاكرة تخزين محلية). */
  SutoorIndexer.prototype.run = function () {
    var self = this;
    var cached = this._readCache();
    if (cached) return Promise.resolve(cached);
    this.collectDOM();
    this.collectJSONLD();
    this.collectInlineJSON();
    return Promise.resolve(this.collectRemote()).then(function () {
      var idx = self.build();
      self._writeCache(idx);
      return idx;
    });
  };

  SutoorIndexer.prototype._readCache = function () {
    try {
      var raw = localStorage.getItem(this.cfg.cacheKey);
      if (!raw) return null;
      var obj = JSON.parse(raw);
      if (obj.v !== INDEX_VERSION) return null;
      if (Date.now() - obj.built > this.cfg.cacheTTL) return null;
      // بصمة الصفحة: أيّ تغيير في عدد العناصر يبطل الذاكرة فوراً
      if (typeof document !== 'undefined' &&
          obj.sig !== document.querySelectorAll(this.cfg.roots).length) return null;
      return obj;
    } catch (e) { return null; }
  };

  SutoorIndexer.prototype._writeCache = function (idx) {
    try {
      idx.sig = (typeof document !== 'undefined') ? document.querySelectorAll(this.cfg.roots).length : 0;
      localStorage.setItem(this.cfg.cacheKey, JSON.stringify(idx));
    } catch (e) { /* تجاوز الحصّة: يعمل النظام دون ذاكرة */ }
  };

  /* ---- التصدير ---- */
  Sutoor.VERSION = INDEX_VERSION;
  Sutoor.Lang = Lang;
  Sutoor.Semantics = Semantics;
  Sutoor.Indexer = SutoorIndexer;
  Sutoor.FIELD_WEIGHT = FIELD_WEIGHT;

})(typeof self !== 'undefined' ? self : this);
