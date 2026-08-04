/* ============================================================================
 * سُطور من أوال — محرّك «اسأل الأرشيف»
 * الملف (3/5): search-engine.js
 * المسؤولية: التحكّم بالواجهة، اختصارات لوحة المفاتيح، الإدخال المؤجَّل،
 *            التظليل الآمن، العرض الافتراضي، التصفية، والتنقّل إلى النتيجة.
 * ==========================================================================*/
/* global Sutoor */
(function () {
  'use strict';

  var DEBOUNCE = 150;
  var PAGE = 20;                       // عدد النتائج المضافة في كل دفعة عرض
  var RECENT_KEY = 'sutoor.search.recent';

  var Lang = null, worker = null, index = null, fallback = null;
  var el = {}, state = {
    open: false, q: '', rid: 0, active: -1, section: null,
    hits: [], total: 0, rendered: 0, ready: false, expanded: false
  };

  /* =========================================================================
   * أدوات نصّية
   * =======================================================================*/
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /**
   * تطبيع محافظ على المواضع: كل حرف يُنتج حرفاً واحداً أو لا شيء،
   * مع خريطة تُرجع كل موضع مطبَّع إلى موضعه في النصّ الأصلي.
   * هذا ما يسمح بتظليل الكلمة المطابقة في نصّها الأصلي بتشكيلها وهمزاتها.
   */
  var RE_DIA = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]/;
  var CMAP = {
    'أ':'ا','إ':'ا','آ':'ا','ٱ':'ا','ء':'','ى':'ي','ئ':'ي','ؤ':'و','ة':'ه',
    'گ':'ك','ک':'ك','چ':'ج','پ':'ب','ژ':'ز','ی':'ي',
    '٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9'
  };
  function mapNormalize(text) {
    var s = String(text || '');
    if (s.normalize) s = s.normalize('NFKC');
    s = s.toLowerCase();
    var out = '', map = [];
    for (var i = 0; i < s.length; i++) {
      var ch = s[i];
      if (RE_DIA.test(ch)) continue;
      var m = CMAP[ch];
      if (m === '') continue;
      out += (m === undefined ? ch : m);
      map.push(i);
    }
    map.push(s.length);
    return { norm: out, map: map, src: s, raw: String(text || '') };
  }

  /** تظليل المصطلحات المطابقة داخل نصّ، مع تهريب HTML كاملاً. */
  function highlight(text, terms) {
    if (!text) return '';
    if (!terms || !terms.length) return esc(text);
    var mn = mapNormalize(text);
    var ranges = [];
    terms.forEach(function (t) {
      if (!t || t.length < 2) return;
      var from = 0, at;
      while ((at = mn.norm.indexOf(t, from)) !== -1) {
        ranges.push([mn.map[at], mn.map[at + t.length]]);
        from = at + t.length;
        if (ranges.length > 300) break;
      }
    });
    if (!ranges.length) return esc(text);
    ranges.sort(function (a, b) { return a[0] - b[0]; });
    var merged = [ranges[0]];
    for (var i = 1; i < ranges.length; i++) {
      var last = merged[merged.length - 1];
      if (ranges[i][0] <= last[1]) last[1] = Math.max(last[1], ranges[i][1]);
      else merged.push(ranges[i]);
    }
    var raw = mn.raw, html = '', cur = 0;
    merged.forEach(function (r) {
      html += esc(raw.slice(cur, r[0])) + '<mark class="sutoor-highlight">' + esc(raw.slice(r[0], r[1])) + '</mark>';
      cur = r[1];
    });
    return html + esc(raw.slice(cur));
  }

  /* =========================================================================
   * الهيكل: يُستعمل الموجود في الصفحة، وإن غاب يُحقن تلقائياً
   * =======================================================================*/
  var MARKUP =
    '<div class="sutoor-modal" id="sutoorSearchModal" role="dialog" aria-modal="true" aria-labelledby="sutoorSearchLabel" hidden>' +
      '<div class="sutoor-search-box" role="document">' +
        '<div class="sutoor-search-header">' +
          '<svg class="sutoor-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg>' +
          '<label class="sutoor-sr-only" id="sutoorSearchLabel" for="sutoorSearchInput">اسأل الأرشيف</label>' +
          '<input id="sutoorSearchInput" class="sutoor-search-input" type="search" autocomplete="off" spellcheck="false" ' +
                 'placeholder="مثال: متى تأسس مسجد الخميس؟" ' +
                 'role="combobox" aria-expanded="false" aria-controls="sutoorResults" aria-autocomplete="list">' +
          '<kbd class="sutoor-shortcut-hint">Esc</kbd>' +
          '<button type="button" class="sutoor-close" aria-label="إغلاق البحث">&times;</button>' +
        '</div>' +
        '<div class="sutoor-filters" id="sutoorFilters" hidden></div>' +
        '<div class="sutoor-results-container" id="sutoorResults" role="listbox" aria-label="نتائج البحث"></div>' +
        '<div class="sutoor-search-footer">' +
          '<span class="sutoor-legend"><kbd>↑</kbd><kbd>↓</kbd> تنقّل</span>' +
          '<span class="sutoor-legend"><kbd>↵</kbd> فتح النتيجة</span>' +
          '<span class="sutoor-legend"><kbd>Ctrl</kbd>+<kbd>K</kbd> فتح البحث</span>' +
          '<span class="sutoor-stat" id="sutoorStat"></span>' +
        '</div>' +
      '</div>' +
    '</div>';

  function mount() {
    var node = document.getElementById('sutoorSearchModal');
    if (!node) {
      var host = document.createElement('div');
      host.innerHTML = MARKUP;
      node = host.firstChild;
      document.body.appendChild(node);
    }
    el.modal = node;
    el.box = node.querySelector('.sutoor-search-box');
    el.input = node.querySelector('#sutoorSearchInput');
    el.results = node.querySelector('#sutoorResults');
    el.filters = node.querySelector('#sutoorFilters');
    el.stat = node.querySelector('#sutoorStat');
    el.close = node.querySelector('.sutoor-close');
  }

  /* =========================================================================
   * الإقلاع: بناء الفهرس ثمّ تسليمه للعامل
   * =======================================================================*/
  function boot(config) {
    Lang = Sutoor.Lang;
    mount();
    bindUI();

    var idle = window.requestIdleCallback || function (f) { return setTimeout(f, 200); };
    idle(function () {
      var indexer = new Sutoor.Indexer(config || {});
      indexer.run().then(function (idx) {
        index = idx;
        startWorker(idx);
      }).catch(function (e) {
        console.warn('[سُطور] تعذّر بناء الفهرس:', e);
      });
    });
  }

  function startWorker(idx) {
    var url = (window.SUTOOR_WORKER_URL || 'sutoor-search/search-worker.js');
    try {
      worker = new Worker(url);
      worker.onmessage = onWorkerMessage;
      worker.onerror = function () { worker = null; useFallback(idx); };
      worker.postMessage({ type: 'init', index: idx });
    } catch (e) {
      useFallback(idx);
    }
  }

  /** مسار احتياطي (بروتوكول file:// أو منع العمّال): بحث مبسّط في الخيط الرئيسي. */
  function useFallback(idx) {
    fallback = idx;
    state.ready = true;
    setStat('جاهز — ' + idx.docs.length + ' مدخلاً (وضع مبسّط)');
    if (state.q) run(state.q);
  }

  function fallbackSearch(q, opts) {
    var nq = Lang.normalize(q), out = [];
    if (!nq) return { hits: [], total: 0, facets: {}, terms: [] };
    var toks = Lang.tokenize(nq);
    fallback.docs.forEach(function (d) {
      var s = 0;
      toks.forEach(function (t) {
        if (d.n.indexOf(t) !== -1) s += 2;
        if (Lang.normalize(d.t).indexOf(t) !== -1) s += 6;
      });
      if (d.n.indexOf(nq) !== -1) s *= 1.6;
      if (s > 0 && (!opts.section || d.s === opts.section)) {
        out.push({ id: d.i, title: d.t, section: d.s, type: d.y, url: d.u, img: d.g,
                   score: s * (d.r || 1), terms: toks,
                   snippet: (d.d || d.b || '').slice(0, 240) });
      }
    });
    out.sort(function (a, b) { return b.score - a.score; });
    var facets = {};
    out.forEach(function (h) { facets[h.section] = (facets[h.section] || 0) + 1; });
    return { hits: out.slice(0, opts.limit || 40), total: out.length, facets: facets, terms: toks };
  }

  function onWorkerMessage(e) {
    var m = e.data || {};
    if (m.type === 'ready') {
      state.ready = true;
      setStat('جاهز — ' + m.count + ' مدخلاً مفهرساً');
      if (state.q) run(state.q);
      return;
    }
    if (m.type === 'results') {
      if (m.rid !== state.rid) return;         // نتيجة متأخّرة لاستعلام قديم: تُهمَل
      render(m);
      return;
    }
    if (m.type === 'error') console.warn('[سُطور] عامل البحث:', m.reason);
  }

  /* =========================================================================
   * تنفيذ الاستعلام
   * =======================================================================*/
  var timer = null;
  function schedule(q) {
    clearTimeout(timer);
    timer = setTimeout(function () { run(q); }, DEBOUNCE);
  }

  function run(q) {
    state.q = q;
    if (!q || !q.trim()) { renderIdle(); return; }
    if (!state.ready) { setStat('يجري بناء الفهرس…'); return; }
    state.rid++;
    var opts = { limit: state.expanded ? 400 : 60, section: state.section };
    if (worker) worker.postMessage({ type: 'query', rid: state.rid, q: q, opts: opts });
    else if (fallback) {
      var r = fallbackSearch(q, opts);
      r.rid = state.rid; r.q = q; r.ms = 0;
      render(r);
    }
  }

  /* =========================================================================
   * العرض
   * =======================================================================*/
  function setStat(t) { if (el.stat) el.stat.textContent = t; }

  function renderIdle() {
    state.hits = []; state.active = -1;
    el.filters.hidden = true;
    var recent = readRecent();
    var html = '';
    if (recent.length) {
      html += '<div class="sutoor-group"><span class="sutoor-group-title">عمليات بحث سابقة</span>' +
              '<button type="button" class="sutoor-clear" data-act="clear-recent">مسح</button></div>';
      recent.forEach(function (r) {
        html += '<button type="button" class="sutoor-chip" data-fill="' + esc(r) + '">' + esc(r) + '</button>';
      });
    }
    html += '<div class="sutoor-group"><span class="sutoor-group-title">أسئلة مقترحة من الأرشيف</span></div>';
    ['متى تأسس مسجد الخميس؟', 'دلمون وقلعة البحرين', 'التلال الملكية بعالي', 'درب اللؤلؤ',
     'الدولة العيونية', 'سماهيج', 'المخطوطات', 'الأنساب']
      .forEach(function (s) {
        html += '<button type="button" class="sutoor-chip" data-fill="' + esc(s) + '">' + esc(s) + '</button>';
      });
    el.results.innerHTML = html;
    el.input.setAttribute('aria-expanded', 'false');
    setStat(index ? index.docs.length + ' مدخلاً مفهرساً' : '');
  }

  function render(res) {
    state.hits = res.hits || [];
    state.total = res.total || 0;
    state.rendered = 0;
    state.active = -1;
    el.results.scrollTop = 0;

    if (!state.hits.length) {
      el.filters.hidden = true;
      var s = res.suggestion;
      el.results.innerHTML =
        '<div class="sutoor-no-results">' +
          '<p class="sutoor-no-results-title">لا نتائج لـ «' + esc(res.q) + '»</p>' +
          (s ? '<p>هل تقصد <button type="button" class="sutoor-chip" data-fill="' + esc(s) + '">' + esc(s) + '</button>؟</p>'
             : '<p>جرّب كلمة أقصر، أو ابحث باسم المعلم أو المخطوطة مباشرة.</p>') +
        '</div>';
      el.input.setAttribute('aria-expanded', 'false');
      setStat('0 نتيجة · ' + (res.ms || 0) + ' مللي ثانية');
      return;
    }

    renderFilters(res.facets);
    el.results.innerHTML = '';
    appendChunk();
    el.input.setAttribute('aria-expanded', 'true');
    setStat(state.total + ' نتيجة · ' + (res.ms || 0) + ' مللي ثانية');
  }

  function renderFilters(facets) {
    var keys = Object.keys(facets || {}).sort(function (a, b) { return facets[b] - facets[a]; });
    if (keys.length < 2) { el.filters.hidden = true; return; }
    var html = '<button type="button" class="sutoor-filter' + (state.section ? '' : ' is-on') + '" data-section="">الكل</button>';
    keys.slice(0, 8).forEach(function (k) {
      html += '<button type="button" class="sutoor-filter' + (state.section === k ? ' is-on' : '') +
              '" data-section="' + esc(k) + '">' + esc(k) + '<span>' + facets[k] + '</span></button>';
    });
    el.filters.innerHTML = html;
    el.filters.hidden = false;
  }

  /** عرض افتراضي: لا تُبنى إلا الدفعة المرئية، والباقي عند بلوغ الحارس. */
  function appendChunk() {
    var frag = document.createDocumentFragment();
    var end = Math.min(state.rendered + PAGE, state.hits.length);
    for (var i = state.rendered; i < end; i++) frag.appendChild(card(state.hits[i], i));
    state.rendered = end;

    var old = el.results.querySelector('.sutoor-sentinel');
    if (old) old.remove();
    el.results.appendChild(frag);

    if (state.rendered < state.hits.length) {
      var sent = document.createElement('div');
      sent.className = 'sutoor-sentinel';
      sent.textContent = 'جارٍ عرض المزيد…';
      el.results.appendChild(sent);
      observe(sent);
    } else if (state.total > state.hits.length) {
      var more = document.createElement('button');
      more.type = 'button';
      more.className = 'sutoor-more';
      more.dataset.act = 'expand';
      more.textContent = 'عرض كل النتائج (' + state.total + ')';
      el.results.appendChild(more);
    }
  }

  var io = null;
  function observe(node) {
    if (!('IntersectionObserver' in window)) { appendChunk(); return; }
    if (io) io.disconnect();
    io = new IntersectionObserver(function (entries) {
      if (entries.some(function (e) { return e.isIntersecting; })) { io.disconnect(); appendChunk(); }
    }, { root: el.results, rootMargin: '200px' });
    io.observe(node);
  }

  function card(h, i) {
    var a = document.createElement('a');
    a.className = 'sutoor-result-card';
    a.href = h.url || '#';
    a.setAttribute('role', 'option');
    a.id = 'sutoor-opt-' + i;
    a.dataset.idx = i;

    var thumb = h.img
      ? '<img class="sutoor-result-thumb" src="' + esc(h.img) + '" alt="" loading="lazy" decoding="async">'
      : '<span class="sutoor-thumb-placeholder" aria-hidden="true">' + esc((h.type || 'سطور').slice(0, 6)) + '</span>';

    a.innerHTML =
      thumb +
      '<span class="sutoor-result-body">' +
        '<span class="sutoor-result-meta">' +
          '<span class="sutoor-badge">' + esc(h.section) + '</span>' +
          (h.type ? '<span class="sutoor-type">' + esc(h.type) + '</span>' : '') +
        '</span>' +
        '<span class="sutoor-result-title">' + highlight(h.title, h.terms) + '</span>' +
        '<span class="sutoor-result-snippet">' + highlight(h.snippet, h.terms) + '</span>' +
      '</span>' +
      '<svg class="sutoor-go" viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>';
    return a;
  }

  /* =========================================================================
   * التنقّل والفتح
   * =======================================================================*/
  function move(delta) {
    var cards = el.results.querySelectorAll('.sutoor-result-card');
    if (!cards.length) return;
    if (state.active >= 0 && cards[state.active]) cards[state.active].classList.remove('is-active');
    state.active += delta;
    if (state.active < 0) state.active = cards.length - 1;
    if (state.active >= cards.length) {
      if (state.rendered < state.hits.length) { appendChunk(); }
      state.active = Math.min(state.active, el.results.querySelectorAll('.sutoor-result-card').length - 1);
    }
    cards = el.results.querySelectorAll('.sutoor-result-card');
    var node = cards[state.active];
    if (!node) return;
    node.classList.add('is-active');
    node.scrollIntoView({ block: 'nearest' });
    el.input.setAttribute('aria-activedescendant', node.id);
  }

  function openHit(node) {
    var url = node.getAttribute('href') || '';
    saveRecent(state.q);
    var hash = url.indexOf('#') === 0 ? url
      : (url.indexOf(location.pathname) === 0 && url.indexOf('#') > -1 ? url.slice(url.indexOf('#')) : null);
    if (hash) {
      close();
      var target = document.querySelector(hash);
      if (target) {
        if (target.tagName === 'DETAILS') target.open = true;
        var parentDetails = target.closest && target.closest('details');
        if (parentDetails) parentDetails.open = true;
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.add('sutoor-flash');
        setTimeout(function () { target.classList.remove('sutoor-flash'); }, 1800);
        history.replaceState(null, '', hash);
      }
      return true;
    }
    return false;   // رابط خارجي: يُترك للسلوك الطبيعي
  }

  /* =========================================================================
   * عمليات البحث السابقة
   * =======================================================================*/
  function readRecent() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]').slice(0, 6); }
    catch (e) { return []; }
  }
  function saveRecent(q) {
    q = (q || '').trim();
    if (q.length < 2) return;
    try {
      var list = readRecent().filter(function (x) { return x !== q; });
      list.unshift(q);
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 6)));
    } catch (e) {}
  }

  /* =========================================================================
   * فتح/إغلاق النافذة
   * =======================================================================*/
  var lastFocus = null;
  var askInputs = [];

  function open(prefill) {
    if (state.open) { el.input.focus(); el.input.select(); return; }
    state.open = true;
    lastFocus = document.activeElement;
    el.modal.hidden = false;
    el.modal.classList.add('active');
    document.documentElement.classList.add('sutoor-locked');
    if (prefill != null) el.input.value = prefill;
    el.input.focus();
    el.input.select();
    if (el.input.value.trim()) run(el.input.value); else renderIdle();
  }

  function close() {
    if (!state.open) return;
    state.open = false;
    el.modal.classList.remove('active');
    document.documentElement.classList.remove('sutoor-locked');
    // إبقاء آخر سؤال ظاهراً في شريط الصفحة
    askInputs.forEach(function (i) { if (i) i.value = state.q || i.value; });
    var t = setTimeout(function () { el.modal.hidden = true; clearTimeout(t); }, 180);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  /* =========================================================================
   * الربط بالأحداث
   * =======================================================================*/
  function isTyping(t) {
    return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
  }

  function bindUI() {
    // الاختصارات العامة
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K' || e.code === 'KeyK')) {
        e.preventDefault(); open(); return;
      }
      if (e.key === '/' && !state.open && !isTyping(e.target)) { e.preventDefault(); open(); return; }
      if (e.key === 'Escape' && state.open) { e.preventDefault(); close(); }
    });

    // أزرار فتح البحث في الصفحة
    document.addEventListener('click', function (e) {
      var trig = e.target.closest && e.target.closest('[data-sutoor-open]');
      if (trig) { e.preventDefault(); open(trig.getAttribute('data-sutoor-open') || ''); }
    });

    el.close.addEventListener('click', close);
    el.modal.addEventListener('mousedown', function (e) { if (e.target === el.modal) close(); });

    // الإدخال المؤجَّل 150 مللي ثانية
    el.input.addEventListener('input', function () {
      state.expanded = false;
      state.section = null;
      schedule(el.input.value);
    });

    // التنقّل داخل النتائج
    el.input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') {
        var cards = el.results.querySelectorAll('.sutoor-result-card');
        if (state.active >= 0 && cards[state.active]) {
          if (openHit(cards[state.active])) e.preventDefault();
          else { saveRecent(state.q); }
        } else {
          e.preventDefault();
          state.expanded = true;
          saveRecent(state.q);
          run(el.input.value);        // Enter دون تحديد: لوحة النتائج الشاملة
        }
      }
    });

    // النقر داخل لوحة النتائج
    el.results.addEventListener('click', function (e) {
      var chip = e.target.closest('[data-fill]');
      if (chip) { el.input.value = chip.getAttribute('data-fill'); run(el.input.value); el.input.focus(); return; }
      var act = e.target.closest('[data-act]');
      if (act) {
        if (act.dataset.act === 'clear-recent') { localStorage.removeItem(RECENT_KEY); renderIdle(); }
        if (act.dataset.act === 'expand') { state.expanded = true; run(state.q); }
        return;
      }
      var hit = e.target.closest('.sutoor-result-card');
      if (hit && openHit(hit)) e.preventDefault();
    });

    // تصفية بالقسم
    el.filters.addEventListener('click', function (e) {
      var b = e.target.closest('[data-section]');
      if (!b) return;
      state.section = b.getAttribute('data-section') || null;
      run(state.q);
    });

    // حصر التركيز داخل النافذة
    el.modal.addEventListener('keydown', function (e) {
      if (e.key !== 'Tab') return;
      var f = el.box.querySelectorAll('a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])');
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });

    bindAsk();
  }

  /**
   * سطح «اسأل الأرشيف الموثّق» داخل الصفحة:
   * الشريط الكبسولي والشرائح يغذّيان النافذة نفسها — محرّك واحد وواجهتان.
   * لا يُربط حدث focus عمداً كي لا تُعاد النافذة إلى الفتح عند إرجاع التركيز.
   */
  function bindAsk() {
    var asks = document.querySelectorAll('[data-sutoor-ask]');
    if (!asks.length) return;
    Array.prototype.forEach.call(asks, function (host) {
      var input = host.querySelector('[data-sutoor-ask-input]');
      askInputs.push(input);

      if (input) {
        input.addEventListener('click', function () { open(input.value); });
        input.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') { e.preventDefault(); open(input.value); }
        });
      }
      host.addEventListener('click', function (e) {
        var chip = e.target.closest('[data-fill]');
        if (chip) {
          e.preventDefault();
          var v = chip.getAttribute('data-fill');
          if (input) input.value = v;
          open(v);
          return;
        }
        if (e.target.closest('[data-sutoor-ask-submit]')) {
          e.preventDefault();
          open(input ? input.value : '');
        }
      });
    });
  }

  /* =========================================================================
   * الواجهة العامة + الإقلاع التلقائي
   * =======================================================================*/
  var api = {
    open: open,
    close: close,
    search: function (q) { open(q); },
    reindex: function () {
      try { localStorage.removeItem(new Sutoor.Indexer({}).cfg.cacheKey); } catch (e) {}
      location.reload();
    },
    stats: function () { return { docs: index ? index.docs.length : 0, ready: state.ready, worker: !!worker }; }
  };

  function start() {
    if (!window.Sutoor || !window.Sutoor.Indexer) {
      console.warn('[سُطور] لم يُحمّل search-index.js قبل search-engine.js');
      return;
    }
    boot(window.SUTOOR_SEARCH_CONFIG || {});
    window.Sutoor.Search = api;
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

})();
