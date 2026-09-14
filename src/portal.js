/*
 * onco-portal · движок раздела «Ординатура» для onco-science.ru
 * Один файл на все страницы. Конфигурация через data-атрибуты контейнера:
 *   <div id="oncoResidencyPortal"
 *        data-year="1"                       1 | 2 | all
 *        data-data-url="…/orp-data.json"     откуда брать базу
 *        data-results-url="…/exec"           куда слать результаты тестов (опционально)
 *        data-home="/ordinatura"></div>      ссылка «назад» (опционально)
 * Глубокие ссылки: ?module=M07  ?vp=VP-01  ?osce=S01  ?tb=TB01  ?panel=tests
 */
(function () {
  'use strict';

  var root = document.getElementById('oncoResidencyPortal');
  if (!root) return;

  var DEFAULT_DATA_URL = 'https://cdn.jsdelivr.net/gh/Evdokimov-onco1/onco-portal@main/data/orp-data.json';
  var DEFAULT_MODULES_URL = 'https://cdn.jsdelivr.net/gh/Evdokimov-onco1/onco-portal@main/modules/';

  var CFG = {
    year: String(root.getAttribute('data-year') || 'all'),
    dataUrl: root.getAttribute('data-data-url') || DEFAULT_DATA_URL,
    modulesUrl: root.getAttribute('data-modules-url') || DEFAULT_MODULES_URL,
    resultsUrl: root.getAttribute('data-results-url') || '',
    home: root.getAttribute('data-home') || '',
    yearUrls: { '1': root.getAttribute('data-year-1-url') || '', '2': root.getAttribute('data-year-2-url') || '' }
  };

  var fileUrl = function (name) { return name ? CFG.modulesUrl + encodeURIComponent(name) : ''; };
  var withParam = function (base, key, val) { return base + (base.indexOf('?') > -1 ? '&' : '?') + key + '=' + encodeURIComponent(val); };

  /* ---------- утилиты ---------- */

  var esc = function (v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  // 'М-09' | 'M9' | 'M09' -> 'M09'
  var normId = function (s) {
    var m = String(s || '').match(/[МM]\s*-?\s*0*(\d+)/);
    if (!m) return String(s || '').trim();
    var n = m[1];
    return 'M' + (n.length < 2 ? '0' + n : n);
  };

  // 'M04, M09–M10, M57–M59 (база)' -> ['M04','M09','M10','M57','M58','M59']
  var parseModuleList = function (str) {
    var out = [];
    String(str || '').replace(/\([^)]*\)/g, '').split(',').forEach(function (part) {
      part = part.trim();
      if (!part) return;
      var range = part.match(/[МM]\s*-?\s*0*(\d+)\s*[–—-]\s*[МM]?\s*-?\s*0*(\d+)/);
      if (range) {
        for (var i = Number(range[1]); i <= Number(range[2]); i++) out.push(normId('M' + i));
      } else if (/[МM]\s*-?\s*\d/.test(part)) {
        out.push(normId(part));
      }
    });
    return out;
  };

  var uniq = function (arr) {
    var seen = {};
    return arr.filter(function (x) { if (seen[x]) return false; seen[x] = true; return true; });
  };

  var shuffle = function (arr) {
    var a = arr.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  };

  var q = function (sel, ctx) { return (ctx || root).querySelector(sel); };
  var qa = function (sel, ctx) { return Array.prototype.slice.call((ctx || root).querySelectorAll(sel)); };

  var scrollTo = function (el, delay) {
    if (!el) return;
    setTimeout(function () {
      try { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
      catch (e) { el.scrollIntoView(true); }
    }, delay || 60);
  };

  var TIER = {
    FOUNDATION_CORE: 'базовое ядро',
    CLINICAL_CORE: 'клиническое ядро',
    ADVANCED: 'продвинутый уровень',
    INTEGRATION: 'интеграционный уровень'
  };

  /* ---------- участник Tilda Members ---------- */

  function getMember() {
    try {
      var records = document.querySelector('#allrecords');
      var projectId = records ? records.getAttribute('data-tilda-project-id') : '';
      var raw = localStorage.getItem('tilda_members_profile' + projectId);
      if (!raw) return { name: '', email: '' };
      var user = JSON.parse(raw);
      return { name: String(user.name || ''), email: String(user.login || user.email || '') };
    } catch (e) {
      return { name: '', email: '' };
    }
  }

  function sendResult(payload) {
    if (!CFG.resultsUrl) return;
    var user = getMember();
    payload.name = user.name;
    payload.email = user.email;
    payload.year = CFG.year;
    payload.page = window.location.pathname;
    payload.completed_at = new Date().toISOString();
    try {
      fetch(CFG.resultsUrl, {
        method: 'POST',
        mode: 'no-cors',
        headers: { 'Content-Type': 'text/plain;charset=utf-8' },
        body: JSON.stringify(payload)
      });
    } catch (e) {
      /* тихо: результат на экране всё равно показан */
    }
  }

  /* ---------- оболочка ---------- */

  var YEAR_TITLE = { '1': 'Ординатура — 1-й год', '2': 'Ординатура — 2-й год', all: 'Ординатура по онкологии' };
  var YEAR_LEAD = {
    '1': 'Учебные модули первого года, самоконтроль, библиотека и практические сценарии.',
    '2': 'Учебные модули второго года, самоконтроль, библиотека и практические сценарии.',
    all: 'Двухлетняя учебная среда: модули, библиотека, тесты, виртуальные пациенты, OSCE и Tumor Board.'
  };

  function renderShell() {
    if (q('.orp-wrap')) return;
    var yearPills = CFG.year === 'all'
      ? '<button type="button" class="orp-pill is-active" data-year="all">Все</button>' +
        '<button type="button" class="orp-pill" data-year="1">1-й год</button>' +
        '<button type="button" class="orp-pill" data-year="2">2-й год</button>'
      : '';
    root.innerHTML =
      '<div class="orp-wrap">' +
        (CFG.home ? '<div class="orp-topbar"><a class="orp-back" href="' + esc(CFG.home) + '">← Ординатура</a></div>' : '') +
        '<section class="orp-hero">' +
          '<div class="orp-eyebrow">Кафедра онкологии · Личный кабинет</div>' +
          '<h1 class="orp-h1">' + esc(YEAR_TITLE[CFG.year] || YEAR_TITLE.all) + '</h1>' +
          '<p class="orp-lead">' + esc(YEAR_LEAD[CFG.year] || YEAR_LEAD.all) + '</p>' +
        '</section>' +
        '<div id="orpNotice"></div>' +
        '<nav class="orp-nav" aria-label="Разделы ординатуры">' +
          '<button type="button" class="orp-navbtn is-active" data-panel="modules">Модули</button>' +
          '<button type="button" class="orp-navbtn" data-panel="library">Библиотека</button>' +
          '<button type="button" class="orp-navbtn" data-panel="tests">Банк тестов</button>' +
          '<button type="button" class="orp-navbtn" data-panel="vp">Виртуальные пациенты</button>' +
          '<button type="button" class="orp-navbtn" data-panel="osce">OSCE</button>' +
          '<button type="button" class="orp-navbtn" data-panel="tb">Tumor Board</button>' +
          '<button type="button" class="orp-navbtn" data-panel="calendar">Календарь</button>' +
        '</nav>' +

        '<section class="orp-panel is-active" data-panel-id="modules">' +
          '<div class="orp-sectionhead"><h2 class="orp-h2">Учебные модули</h2><span class="orp-muted" id="orpModuleCount"></span></div>' +
          '<div class="orp-controls">' + yearPills +
            '<input class="orp-input orp-grow" id="orpModuleSearch" type="search" placeholder="Поиск по номеру или теме модуля">' +
          '</div>' +
          '<div class="orp-grid" id="orpModuleGrid"></div>' +
        '</section>' +

        '<section class="orp-panel" data-panel-id="library">' +
          '<div class="orp-sectionhead"><h2 class="orp-h2">Библиотека</h2><span class="orp-muted" id="orpLibCount"></span></div>' +
          '<div class="orp-controls">' +
            '<select class="orp-input" id="orpLibType">' +
              '<option value="rf_guidelines">Клинические рекомендации РФ</option>' +
              '<option value="books_guides">Учебники и руководства</option>' +
              '<option value="clinical_tools">Клинические инструменты</option>' +
              '<option value="simulators">Внешние симуляторы</option>' +
              '<option value="module_guidelines">Рекомендации из модулей (РФ и международные)</option>' +
            '</select>' +
            '<input class="orp-input orp-grow" id="orpLibSearch" type="search" placeholder="Поиск в библиотеке">' +
          '</div>' +
          '<div class="orp-grid" id="orpLibGrid"></div>' +
        '</section>' +

        '<section class="orp-panel" data-panel-id="tests">' +
          '<div class="orp-sectionhead"><h2 class="orp-h2">Банк тестов</h2><span class="orp-muted" id="orpTestCount"></span></div>' +
          '<div class="orp-controls">' +
            '<select class="orp-input orp-grow" id="orpTestModule"><option value="">Все модули</option></select>' +
            '<select class="orp-input" id="orpTestN"><option value="5">5 вопросов</option><option value="10" selected>10 вопросов</option><option value="20">20 вопросов</option><option value="60">60 вопросов (пробный экзамен)</option></select>' +
            '<button type="button" class="orp-primary" id="orpStartTest">Начать тест</button>' +
          '</div>' +
          '<div id="orpTestBox"></div>' +
        '</section>' +

        '<section class="orp-panel" data-panel-id="vp">' +
          '<div class="orp-sectionhead"><h2 class="orp-h2">Виртуальные пациенты</h2><span class="orp-muted" id="orpVpCount"></span></div>' +
          '<p class="orp-lead orp-lead-sm">Ветвящиеся клинические сценарии: каждое решение имеет последствия и обратную связь.</p>' +
          '<div class="orp-grid" id="orpVpGrid"></div>' +
          '<div id="orpVpRunner"></div>' +
        '</section>' +

        '<section class="orp-panel" data-panel-id="osce">' +
          '<div class="orp-sectionhead"><h2 class="orp-h2">OSCE</h2><span class="orp-muted" id="orpOsceCount"></span></div>' +
          '<p class="orp-lead orp-lead-sm">Экзаменационные станции: задание, материалы, затем эталон действий и чек-лист.</p>' +
          '<div class="orp-grid" id="orpOsceGrid"></div>' +
          '<div id="orpOsceRunner"></div>' +
        '</section>' +

        '<section class="orp-panel" data-panel-id="tb">' +
          '<div class="orp-sectionhead"><h2 class="orp-h2">Tumor Board</h2><span class="orp-muted" id="orpTbCount"></span></div>' +
          '<p class="orp-lead orp-lead-sm">Мультидисциплинарные кейсы с поэтапным раскрытием информации.</p>' +
          '<div class="orp-grid" id="orpTbGrid"></div>' +
          '<div id="orpTbRunner"></div>' +
        '</section>' +

        '<section class="orp-panel" data-panel-id="calendar">' +
          '<div class="orp-sectionhead"><h2 class="orp-h2">Календарный план 2026/2027</h2><span class="orp-muted" id="orpCalCount"></span></div>' +
          '<p class="orp-lead orp-lead-sm">Лекции и семинары в хронологическом порядке. Даты предварительные, по проекту кафедры.</p>' +
          '<div class="orp-controls" id="orpCalControls"></div>' +
          '<div id="orpCalBox"></div>' +
        '</section>' +
      '</div>';
  }

  function notice(text, kind) {
    var box = q('#orpNotice');
    if (!box) return;
    box.innerHTML = text ? '<div class="orp-notice ' + (kind || '') + '">' + esc(text) + '</div>' : '';
  }

  function activatePanel(id) {
    qa('.orp-navbtn').forEach(function (b) { b.classList.toggle('is-active', b.getAttribute('data-panel') === id); });
    qa('.orp-panel').forEach(function (p) { p.classList.toggle('is-active', p.getAttribute('data-panel-id') === id); });
  }

  function setUrlParam(key, value) {
    try {
      var url = new URL(window.location.href);
      ['module', 'vp', 'osce', 'tb', 'panel'].forEach(function (k) { url.searchParams.delete(k); });
      if (value) url.searchParams.set(key, value);
      history.replaceState(null, '', url.toString());
    } catch (e) { /* ignore */ }
  }

  /* ---------- индекс данных ---------- */

  function buildIndex(D) {
    var X = {
      tools: {}, sims: {}, vps: {}, osce: {}, tb: {},
      rfByModule: {}, booksByModule: {}, sourcesByModule: {}, questionsByModule: {},
      toolsByModule: {}, simsByModule: {}
    };
    var push = function (map, key, val) { (map[key] = map[key] || []).push(val); };

    (D.library.clinical_tools || []).forEach(function (t) { X.tools[t.id] = t; });
    (D.library.simulators || []).forEach(function (s) { X.sims[s.id] = s; });
    (D.virtual_patients || []).forEach(function (v) { X.vps[v.id] = v; });
    ((D.osce && D.osce.stations) || []).forEach(function (s) { X.osce[s.id] = s; });
    ((D.tumor_board && D.tumor_board.cases) || []).forEach(function (c) { X.tb[c.id] = c; });

    (D.library.rf_guidelines || []).forEach(function (g) {
      (g.module_ids || []).forEach(function (m) { push(X.rfByModule, normId(m), g); });
    });
    (D.library.books_guides || []).forEach(function (b) {
      parseModuleList(b.modules).forEach(function (m) { push(X.booksByModule, m, b); });
    });
    (D.questions || []).forEach(function (qq) {
      var m = normId(qq.module);
      push(X.questionsByModule, m, qq);
      if (qq.source_title || qq.source_url) push(X.sourcesByModule, m, { title: qq.source_title || qq.source_url, url: qq.source_url || '' });
    });
    (D.modules || []).forEach(function (m) {
      var id = normId(m.module_id);
      var ct = m.clinical_tools || {};
      var ids = [];
      if (Array.isArray(ct)) ids = ct.slice();
      else ['mandatory', 'optional', 'journal'].forEach(function (k) { ids = ids.concat(ct[k] || []); });
      X.toolsByModule[id] = uniq(ids).map(function (t) { return X.tools[t]; }).filter(Boolean);
      X.simsByModule[id] = uniq(m.external_simulators || []).map(function (s) { return X.sims[s]; }).filter(Boolean);
    });
    Object.keys(X.sourcesByModule).forEach(function (m) {
      var seen = {};
      X.sourcesByModule[m] = X.sourcesByModule[m].filter(function (s) {
        var k = (s.url || s.title).toLowerCase();
        if (seen[k]) return false; seen[k] = true; return true;
      });
    });
    return X;
  }

  /* ---------- модули ---------- */

  function moduleCard(m, X) {
    var id = normId(m.module_id);
    var cases = (m.clinical_cases || m.clinical_case_titles || []).length;
    var practice = (m.virtual_patients || []).length + (m.osce_links || []).length + (m.tumorboard_links || []).length;
    return '<article class="orp-card" data-module="' + esc(id) + '">' +
      '<div class="orp-cardtop"><span class="orp-tag">' + esc(id) + '</span><span class="orp-tag">' + esc(m.pedagogical_year) + '-й год</span></div>' +
      '<h3 class="orp-h3">' + esc(m.module_title) + '</h3>' +
      '<div class="orp-muted">Лекция ' + esc(m.actual_lecture_date || '') + (m.lecturer ? ' · ' + esc(m.lecturer) : '') + '</div>' +
      '<div class="orp-stats"><span class="orp-tag">задачи ' + cases + '</span><span class="orp-tag">тесты ' + esc(m.test_questions || (X.questionsByModule[id] || []).length) + '</span>' +
        (practice ? '<span class="orp-tag">практика ' + practice + '</span>' : '') + '</div>' +
      '<button type="button" class="orp-primary orp-module-open" data-id="' + esc(id) + '">Открыть модуль</button>' +
    '</article>';
  }

  function linkList(items, mapFn) {
    if (!items || !items.length) return '';
    return '<ul class="orp-resources">' + items.map(mapFn).join('') + '</ul>';
  }

  function resLink(title, url, meta) {
    return '<li class="orp-res-item">' +
      (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(title) + '</a>' : esc(title)) +
      (meta ? '<span class="orp-res-meta">' + esc(meta) + '</span>' : '') +
    '</li>';
  }

  function renderModuleDetail(m, D, X) {
    var id = normId(m.module_id);
    var R = m.reading || {};
    var rf = X.rfByModule[id] || [];
    var books = X.booksByModule[id] || [];
    var tools = (X.toolsByModule[id] || []).slice(0, Number((D.rules && D.rules.tools_primary_max) || 3));
    var sims = (X.simsByModule[id] || []).slice(0, Number((D.rules && D.rules.simulators_primary_max) || 2));
    var vps = (m.virtual_patients || []).map(function (i) { return X.vps[i]; }).filter(Boolean);
    var osce = (m.osce_links || []).map(function (i) { return X.osce[i]; }).filter(Boolean);
    var tbs = (m.tumorboard_links || []).map(function (i) { return X.tb[i]; }).filter(Boolean);
    var nQ = (X.questionsByModule[id] || []).length;
    var cal = m.calendar || [];

    var lectureLine = cal.length
      ? cal.map(function (c) { return esc(c.date) + ' · ' + esc(c.lecturer) + (c.section ? ' · ' + esc(c.section) : '') + (cal.length > 1 ? ' — ' + esc(c.title) : ''); }).join('<br>')
      : esc(m.lecture || 'Материал будет добавлен.');

    // Что читать: блок А из DOCX, затем связи из библиотеки руководителя
    var reading = '';
    var res = function (items, mapFn) { return linkList(items, mapFn); };
    if ((R.guidelines || []).length) reading += '<div class="orp-kicker">Рекомендации и нормативные документы</div>' + res(R.guidelines, function (g) { return resLink(g.title, g.url, g.note); });
    if (rf.length) reading += '<div class="orp-kicker">Клинические рекомендации РФ по теме</div>' + res(rf, function (g) { return resLink(g.title, g.url, (g.year ? g.year : '') + (g.kr_id ? ' · КР ' + g.kr_id : '')); });
    if ((R.reviews || []).length) reading += '<div class="orp-kicker">Обзоры и справочные ресурсы</div>' + res(R.reviews, function (g) { return resLink(g.title, g.url, g.note); });
    if ((R.key_studies || []).length) {
      var groups = [], byG = {};
      R.key_studies.forEach(function (k) { var g = k.group || ''; if (!byG[g]) { byG[g] = []; groups.push(g); } byG[g].push(k); });
      reading += '<div class="orp-kicker">Ключевые исследования</div>' + groups.map(function (g) {
        return (g ? '<div class="orp-subkicker">' + esc(g) + '</div>' : '') + res(byG[g], function (k) { return resLink(k.title, k.url, k.note); });
      }).join('');
    }
    if (books.length) reading += '<div class="orp-kicker">Учебники и руководства</div>' + res(books, function (b) { return resLink(b.title, b.url, b.type || ''); });
    if ((R.lectures || []).length) reading += '<div class="orp-kicker">Лекции и видео</div>' + res(R.lectures, function (g) { return resLink(g.title, g.url, g.note); });
    if ((R.updates_2026 || []).length) reading += '<div class="orp-kicker">Актуализация 2026</div>' + res(R.updates_2026, function (g) { return resLink(g.title, g.url, g.note); });
    if (!reading) reading = '<p class="orp-muted">Материалы для чтения к этому модулю пока не привязаны.</p>';

    // Клинические задачи с эталонами (Б2) или только заголовки (старый формат)
    var casesHtml = '';
    if ((m.clinical_cases || []).length) {
      casesHtml = m.clinical_cases.map(function (c, i) {
        return '<div class="orp-case">' +
          '<div class="orp-case-title">' + esc(c.title) + '</div>' +
          (c.vignette ? '<p>' + esc(c.vignette) + '</p>' : '') +
          (c.questions ? '<p class="orp-case-q">' + esc(c.questions) + '</p>' : '') +
          (c.answer ? '<button type="button" class="orp-btn orp-btn-sm orp-case-toggle" data-i="' + i + '">Показать эталонный ответ</button>' +
            '<div class="orp-feedback orp-hidden" data-answer="' + i + '">' + esc(c.answer) +
            ((c.sources || []).length ? '<div class="orp-source">Источники: ' + c.sources.map(function (sx) { return sx.url ? '<a href="' + esc(sx.url) + '" target="_blank" rel="noopener">' + esc(sx.title) + '</a>' : esc(sx.title); }).join(' · ') + '</div>' : '') +
            '</div>' : '') +
        '</div>';
      }).join('');
    } else {
      casesHtml = '<ol class="orp-list">' + ((m.clinical_case_titles || []).map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') || '<li>Материалы будут добавлены.</li>') + '</ol>';
    }

    var practice = '';
    var chip = function (kind, item, label) {
      return '<button type="button" class="orp-chipbtn" data-open="' + kind + '" data-id="' + esc(item.id) + '"><b>' + esc(item.id) + '</b> ' + esc(label) + '</button>';
    };
    if (vps.length) practice += '<div class="orp-kicker">Виртуальные пациенты</div><div class="orp-chips">' + vps.map(function (v) { return chip('vp', v, v.title); }).join('') + '</div>';
    if (osce.length) practice += '<div class="orp-kicker">Станции OSCE</div><div class="orp-chips">' + osce.map(function (sx) { return chip('osce', sx, sx.title); }).join('') + '</div>';
    if (tbs.length) practice += '<div class="orp-kicker">Tumor Board</div><div class="orp-chips">' + tbs.map(function (c) { return chip('tb', c, c.title); }).join('') + '</div>';
    if (!practice) practice = '<p class="orp-muted">Интеграционные сценарии к этому модулю не назначены.</p>';

    var instruments = '';
    if (tools.length) instruments += '<div class="orp-kicker">Клинические инструменты</div>' + linkList(tools, function (t) { return resLink(t.name, t.url, [t.category, t.teaching].filter(Boolean).join(' · ')); });
    if (sims.length) instruments += '<div class="orp-kicker">Внешние симуляторы</div>' + linkList(sims, function (sx) { return resLink(sx.name, sx.url, [sx.provider, sx.access].filter(Boolean).join(' · ')); });
    if (!instruments) instruments = '<p class="orp-muted">Инструменты к этому модулю не назначены.</p>';

    var checklist = (m.skills_checklist || []).length
      ? '<div class="orp-stage"><b>Чек-лист навыков для дневника ординатора</b><ul class="orp-list orp-checklist">' + m.skills_checklist.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ul></div>'
      : '';

    return '<div class="orp-runner orp-module-detail">' +
      '<div class="orp-cardtop">' +
        '<span class="orp-tag">' + esc(id) + '</span>' +
        '<span class="orp-tag">' + esc(m.pedagogical_year) + '-й год</span>' +
        '<span class="orp-tag">Лекция ' + esc(m.actual_lecture_date || '') + '</span>' +
        (TIER[m.competence_tier] ? '<span class="orp-tag">' + esc(TIER[m.competence_tier]) + '</span>' : '') +
      '</div>' +
      '<h3 class="orp-h3 orp-h3-lg">' + esc(m.module_title) + '</h3>' +
      (m.rationale ? '<p class="orp-muted">' + esc(m.rationale) + '</p>' : '') +
      '<div class="orp-actions orp-actions-top">' +
        (m.docx ? '<a class="orp-primary" href="' + esc(fileUrl(m.docx)) + '" target="_blank" rel="noopener">Скачать модуль (DOCX)</a>' : '') +
        (nQ ? '<button type="button" class="orp-btn orp-module-test" data-id="' + esc(id) + '">Тест по модулю · ' + nQ + '</button>' : '') +
      '</div>' +

      '<div class="orp-stage"><b>Лекция</b><p>' + lectureLine + '</p></div>' +
      '<div class="orp-stage"><b>Что читать</b>' + reading + '</div>' +
      '<div class="orp-stage"><b>Клинические задачи семинара</b>' +
        (m.seminar_basis ? '<p class="orp-muted">' + esc(m.seminar_basis) + '</p>' : '') + casesHtml + '</div>' +
      ((m.oral_discussion_questions || []).length ? '<div class="orp-stage"><b>Вопросы для устного разбора</b><ol class="orp-list">' + m.oral_discussion_questions.slice(0, 8).map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ol></div>' : '') +
      '<div class="orp-stage"><b>Самоконтроль</b><p>Тестовых заданий по модулю: ' + nQ + '. Ответ, пояснение и источник показываются после каждого вопроса.</p>' +
        (nQ ? '<button type="button" class="orp-primary orp-module-test" data-id="' + esc(id) + '">Запустить тест по модулю</button>' : '') + '</div>' +
      '<div class="orp-stage"><b>Практика</b>' + practice + '</div>' +
      '<div class="orp-stage"><b>Инструменты и симуляторы</b>' + instruments + '</div>' +
      checklist +
      '<div class="orp-actions"><button type="button" class="orp-btn orp-module-close">Закрыть модуль</button>' +
        '<a class="orp-btn orp-copylink" href="?module=' + esc(id) + '">Ссылка на модуль</a></div>' +
    '</div>';
  }

  function setupModules(D, X, api) {
    var grid = q('#orpModuleGrid'), search = q('#orpModuleSearch'), count = q('#orpModuleCount');
    var selectedYear = CFG.year;

    function visibleModules() {
      var query = search.value.trim().toLowerCase();
      return D.modules.filter(function (m) {
        var okYear = selectedYear === 'all' || String(m.pedagogical_year) === selectedYear;
        var text = (normId(m.module_id) + ' ' + m.module_title).toLowerCase();
        return okYear && text.indexOf(query) > -1;
      });
    }

    function closeDetail() {
      var old = q('.orp-module-inline', grid);
      if (old) old.remove();
      qa('.orp-card-selected', grid).forEach(function (c) { c.classList.remove('orp-card-selected'); });
      setUrlParam('module', '');
    }

    function openModule(id) {
      var m = D.modules.filter(function (x) { return normId(x.module_id) === id; })[0];
      if (!m) return;
      var card = q('.orp-card[data-module="' + id + '"]', grid);
      if (!card) {
        if (CFG.year !== 'all' && String(m.pedagogical_year) !== CFG.year) {
          var other = CFG.yearUrls[String(m.pedagogical_year)];
          if (other) { window.location.href = withParam(other, 'module', id); return; }
          notice('Модуль ' + id + ' относится к ' + m.pedagogical_year + '-му году обучения и открывается на странице другого года.', 'is-error');
          return;
        }
        search.value = '';
        if (selectedYear !== 'all') { selectedYear = 'all'; qa('.orp-pill[data-year]').forEach(function (x) { x.classList.toggle('is-active', x.getAttribute('data-year') === 'all'); }); }
        render();
        card = q('.orp-card[data-module="' + id + '"]', grid);
        if (!card) return;
      }
      closeDetail();
      card.classList.add('orp-card-selected');
      var inline = document.createElement('div');
      inline.className = 'orp-module-inline';
      inline.innerHTML = renderModuleDetail(m, D, X);
      card.insertAdjacentElement('afterend', inline);

      q('.orp-module-close', inline).addEventListener('click', closeDetail);
      qa('.orp-module-test', inline).forEach(function (b) { b.addEventListener('click', function () { api.startModuleTest(id); }); });
      qa('.orp-case-toggle', inline).forEach(function (b) {
        b.addEventListener('click', function () {
          var ans = q('[data-answer="' + b.getAttribute('data-i') + '"]', inline);
          if (ans) { ans.classList.remove('orp-hidden'); b.classList.add('orp-hidden'); }
        });
      });
      qa('.orp-chipbtn', inline).forEach(function (b) {
        b.addEventListener('click', function () { api.open(b.getAttribute('data-open'), b.getAttribute('data-id')); });
      });
      q('.orp-copylink', inline).addEventListener('click', function (e) {
        e.preventDefault();
        setUrlParam('module', id);
        try { navigator.clipboard.writeText(window.location.href); e.target.textContent = 'Ссылка скопирована'; } catch (err) { /* ignore */ }
      });
      setUrlParam('module', id);
      scrollTo(card);
    }

    function render() {
      var items = visibleModules();
      grid.innerHTML = items.map(function (m) { return moduleCard(m, X); }).join('') ||
        '<p class="orp-muted">Ничего не найдено.</p>';
      count.textContent = items.length + ' ' + plural(items.length, ['модуль', 'модуля', 'модулей']);
      qa('.orp-module-open', grid).forEach(function (b) {
        b.addEventListener('click', function () { openModule(b.getAttribute('data-id')); });
      });
    }

    qa('.orp-pill[data-year]').forEach(function (b) {
      b.addEventListener('click', function () {
        qa('.orp-pill[data-year]').forEach(function (x) { x.classList.remove('is-active'); });
        b.classList.add('is-active');
        selectedYear = b.getAttribute('data-year');
        render();
      });
    });
    search.addEventListener('input', render);
    render();
    api.openModule = openModule;
  }

  function plural(n, forms) {
    var a = Math.abs(n) % 100, b = a % 10;
    if (a > 10 && a < 20) return forms[2];
    if (b > 1 && b < 5) return forms[1];
    if (b === 1) return forms[0];
    return forms[2];
  }

  /* ---------- библиотека ---------- */

  function setupLibrary(D) {
    var type = q('#orpLibType'), search = q('#orpLibSearch'), grid = q('#orpLibGrid'), count = q('#orpLibCount');
    function render() {
      var query = search.value.trim().toLowerCase();
      var items = (D.library[type.value] || []).filter(function (r) { return JSON.stringify(r).toLowerCase().indexOf(query) > -1; });
      count.textContent = items.length + ' ' + plural(items.length, ['запись', 'записи', 'записей']);
      grid.innerHTML = items.map(function (r) {
        var title = r.title || r.name || r.id;
        var sub = [r.year, r.type, r.category, r.provider, r.access_normalized || r.access].filter(Boolean).join(' · ');
        var note = r.teaching || r.role || r.notes || '';
        var mods = Array.isArray(r.module_ids) ? r.module_ids.map(normId) : Array.isArray(r.modules) ? r.modules.map(normId) : parseModuleList(r.modules);
        return '<article class="orp-card">' +
          '<span class="orp-tag">' + esc(r.id) + '</span>' +
          '<h3 class="orp-h3">' + esc(title) + '</h3>' +
          '<div class="orp-muted">' + esc(sub) + '</div>' +
          (note ? '<p class="orp-note">' + esc(note) + '</p>' : '') +
          (mods.length ? '<div class="orp-chips orp-chips-sm">' + mods.slice(0, 8).map(function (m) { return '<button type="button" class="orp-minichip orp-lib-module" data-id="' + esc(m) + '">' + esc(m) + '</button>'; }).join('') + (mods.length > 8 ? '<span class="orp-muted">+' + (mods.length - 8) + '</span>' : '') + '</div>' : '') +
          (r.url ? '<a class="orp-btn orp-link" target="_blank" rel="noopener" href="' + esc(r.url) + '">Открыть источник</a>' : '') +
        '</article>';
      }).join('') || '<p class="orp-muted">Ничего не найдено.</p>';
      qa('.orp-lib-module', grid).forEach(function (b) {
        b.addEventListener('click', function () { API.open('module', b.getAttribute('data-id')); });
      });
    }
    type.addEventListener('change', render);
    search.addEventListener('input', render);
    render();
  }

  /* ---------- тесты ---------- */

  function setupTests(D, X, api) {
    var sel = q('#orpTestModule'), nSel = q('#orpTestN'), box = q('#orpTestBox'), count = q('#orpTestCount');
    var pool = D.questions.filter(function (qq) { return CFG.year === 'all' || String(qq.year) === CFG.year; });
    var modules = D.modules.filter(function (m) { return CFG.year === 'all' || String(m.pedagogical_year) === CFG.year; });
    count.textContent = pool.length + ' ' + plural(pool.length, ['задание', 'задания', 'заданий']);
    modules.forEach(function (m) {
      var id = normId(m.module_id);
      sel.insertAdjacentHTML('beforeend', '<option value="' + esc(id) + '">' + esc(id) + ' — ' + esc(m.module_title) + '</option>');
    });

    function runTest(items, label) {
      var i = 0, score = 0, wrong = [];
      function show() {
        if (i >= items.length) {
          var pct = Math.round(score / items.length * 100);
          sendResult({ kind: 'test', module: label, score: score, total: items.length, percent: pct });
          box.innerHTML = '<div class="orp-runner">' +
            '<h3 class="orp-h3 orp-h3-lg">Результат: ' + score + ' / ' + items.length + ' (' + pct + '%)</h3>' +
            (CFG.resultsUrl ? '<p class="orp-muted">Результат отправлен преподавателю.</p>' : '') +
            (wrong.length ? '<div class="orp-stage"><b>Разобрать ошибки</b><ol class="orp-list">' + wrong.map(function (w) { return '<li><b>' + esc(w.id) + '.</b> ' + esc(w.stem) + '<div class="orp-muted">Верно: ' + esc(w.answer) + '</div></li>'; }).join('') + '</ol></div>' : '') +
            '<button type="button" class="orp-primary" id="orpTestAgain">Пройти ещё раз</button></div>';
          q('#orpTestAgain', box).addEventListener('click', function () { runTest(shuffle(items), label); });
          scrollTo(box);
          return;
        }
        var qq = items[i];
        var opts = shuffle((qq.options || []).map(function (t, j) { return { text: t, key: 'ABCD'[j] }; }));
        box.innerHTML = '<div class="orp-runner">' +
          '<div class="orp-muted">' + esc(qq.id) + ' · ' + esc(normId(qq.module)) + ' · ' + (i + 1) + '/' + items.length + '</div>' +
          '<div class="orp-question">' + esc(qq.stem) + '</div>' +
          opts.map(function (o) { return '<button type="button" class="orp-choice" data-key="' + o.key + '">' + esc(o.text) + '</button>'; }).join('') +
          '<div id="orpTestFeedback"></div></div>';
        qa('.orp-choice', box).forEach(function (b) {
          b.addEventListener('click', function () {
            qa('.orp-choice', box).forEach(function (x) { x.disabled = true; });
            var ok = b.getAttribute('data-key') === qq.correct;
            if (ok) score++;
            else {
              var idx = 'ABCD'.indexOf(qq.correct);
              wrong.push({ id: qq.id, stem: qq.stem, answer: (qq.options || [])[idx] || qq.correct });
              qa('.orp-choice', box).forEach(function (x) { if (x.getAttribute('data-key') === qq.correct) x.classList.add('is-good'); });
            }
            b.classList.add(ok ? 'is-good' : 'is-bad');
            q('#orpTestFeedback', box).innerHTML = '<div class="orp-feedback"><b>' + (ok ? 'Верно' : 'Неверно') + '</b><br>' + esc(qq.explanation || '') +
              (qq.source_title ? '<div class="orp-source">Источник: ' + (qq.source_url ? '<a href="' + esc(qq.source_url) + '" target="_blank" rel="noopener">' + esc(qq.source_title) + '</a>' : esc(qq.source_title)) + '</div>' : '') +
              '</div><button type="button" class="orp-primary" id="orpNextTest">' + (i + 1 < items.length ? 'Далее' : 'Показать результат') + '</button>';
            q('#orpNextTest', box).addEventListener('click', function () { i++; show(); });
          });
        });
        if (i === 0) scrollTo(box);
      }
      show();
    }

    function start(moduleId, n) {
      var items = moduleId ? pool.filter(function (qq) { return normId(qq.module) === moduleId; }) : pool;
      if (!items.length) {
        box.innerHTML = '<div class="orp-runner"><p>Для выбранного модуля вопросы пока не найдены.</p></div>';
        return;
      }
      runTest(shuffle(items).slice(0, Math.min(n, items.length)), moduleId || 'Все модули');
    }

    q('#orpStartTest').addEventListener('click', function () { start(sel.value, Number(nSel.value) || 10); });
    api.startModuleTest = function (moduleId) {
      activatePanel('tests');
      sel.value = moduleId;
      setUrlParam('panel', 'tests');
      start(moduleId, 10);
    };
  }

  /* ---------- виртуальные пациенты ---------- */

  function setupVP(D, X, api) {
    var grid = q('#orpVpGrid'), runner = q('#orpVpRunner'), count = q('#orpVpCount');
    var items = D.virtual_patients || [];
    count.textContent = items.length + ' ' + plural(items.length, ['сценарий', 'сценария', 'сценариев']);
    grid.innerHTML = items.map(function (v) {
      return '<article class="orp-card"><span class="orp-tag">' + esc(v.id) + '</span><h3 class="orp-h3">' + esc(v.title) + '</h3>' +
        '<div class="orp-muted">' + esc(v.level || '') + '</div>' +
        ((v.modules || []).length ? '<div class="orp-chips orp-chips-sm">' + v.modules.map(function (m) { return '<span class="orp-minichip">' + esc(normId(m)) + '</span>'; }).join('') + '</div>' : '') +
        '<button type="button" class="orp-primary orp-vp-open" data-id="' + esc(v.id) + '">Начать сценарий</button></article>';
    }).join('');
    qa('.orp-vp-open', grid).forEach(function (b) { b.addEventListener('click', function () { startVP(b.getAttribute('data-id')); }); });

    function startVP(id) {
      var v = X.vps[id];
      if (!v) return;
      var by = {};
      v.nodes.forEach(function (n) { by[n.id] = n; });
      var score = 0, steps = 0;
      setUrlParam('vp', id);

      function head() {
        return '<div class="orp-cardtop"><span class="orp-tag">' + esc(v.id) + '</span><span class="orp-tag">' + esc(v.level || '') + '</span></div>' +
          '<h3 class="orp-h3 orp-h3-lg">' + esc(v.title) + '</h3>';
      }
      function show(nodeId) {
        var n = by[nodeId];
        if (!n) return;
        if (n.terminal) {
          sendResult({ kind: 'vp', module: v.id, score: score, total: steps, percent: null });
          runner.innerHTML = '<div class="orp-runner">' + head() +
            '<div class="orp-feedback">' + esc(n.outcome || '') + '</div>' +
            '<p><b>Суммарный балл ветки:</b> ' + score + ' за ' + steps + ' ' + plural(steps, ['решение', 'решения', 'решений']) + '</p>' +
            ((v.critical_errors || []).length ? '<div class="orp-stage"><b>Критические ошибки сценария</b><ul class="orp-list">' + v.critical_errors.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ul></div>' : '') +
            ((v.objectives || []).length ? '<div class="orp-stage"><b>Учебные цели</b><ul class="orp-list">' + v.objectives.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ul></div>' : '') +
            ((v.sources || []).length ? '<div class="orp-source">Источники: ' + esc(v.sources.join('; ')) + '</div>' : '') +
            '<div class="orp-actions"><button type="button" class="orp-primary" id="orpVpRestart">Начать заново</button></div></div>';
          q('#orpVpRestart', runner).addEventListener('click', function () { startVP(id); });
          scrollTo(runner);
          return;
        }
        runner.innerHTML = '<div class="orp-runner">' + head() +
          '<div class="orp-muted">Шаг ' + (steps + 1) + '</div>' +
          '<div class="orp-question">' + esc(n.prompt) + '</div>' +
          (n.choices || []).map(function (c, j) { return '<button type="button" class="orp-choice" data-i="' + j + '">' + esc(c.text) + '</button>'; }).join('') +
          '<div id="orpVpFeedback"></div></div>';
        qa('.orp-choice', runner).forEach(function (btn) {
          btn.addEventListener('click', function () {
            var c = n.choices[Number(btn.getAttribute('data-i'))];
            score += Number(c.score || 0); steps++;
            qa('.orp-choice', runner).forEach(function (x) { x.disabled = true; });
            btn.classList.add(Number(c.score || 0) > 0 ? 'is-good' : 'is-bad');
            q('#orpVpFeedback', runner).innerHTML = '<div class="orp-feedback">' + esc(c.feedback || '') + '</div><button type="button" class="orp-primary" id="orpVpNext">Далее</button>';
            q('#orpVpNext', runner).addEventListener('click', function () { show(c.to); });
          });
        });
        scrollTo(runner);
      }
      show('1');
    }
    api.startVP = startVP;
  }

  /* ---------- OSCE ---------- */

  function tableHtml(rows) {
    if (!rows || !rows.length) return '';
    var heads = Object.keys(rows[0]);
    return '<div class="orp-tablewrap"><table class="orp-table"><thead><tr>' + heads.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function (r) { return '<tr>' + heads.map(function (h) { return '<td>' + esc(r[h]) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
  }

  function setupOSCE(D, X, api) {
    var grid = q('#orpOsceGrid'), runner = q('#orpOsceRunner'), count = q('#orpOsceCount');
    var items = (D.osce && D.osce.stations) || [];
    count.textContent = items.length + ' ' + plural(items.length, ['станция', 'станции', 'станций']);
    grid.innerHTML = items.map(function (s) {
      return '<article class="orp-card"><span class="orp-tag">' + esc(s.id) + '</span><h3 class="orp-h3">' + esc(s.title) + '</h3>' +
        '<div class="orp-muted">' + esc((s.meta && s.meta['Время']) || '') + (s.meta && s.meta['Связанные модули'] ? ' · ' + esc(s.meta['Связанные модули']) : '') + '</div>' +
        '<button type="button" class="orp-primary orp-osce-open" data-id="' + esc(s.id) + '">Открыть станцию</button></article>';
    }).join('');
    qa('.orp-osce-open', grid).forEach(function (b) { b.addEventListener('click', function () { openOSCE(b.getAttribute('data-id')); }); });

    function openOSCE(id) {
      var s = X.osce[id];
      if (!s) return;
      setUrlParam('osce', id);
      runner.innerHTML = '<div class="orp-runner">' +
        '<div class="orp-cardtop"><span class="orp-tag">' + esc(s.id) + '</span><span class="orp-tag">' + esc((s.meta && s.meta['Время']) || '') + '</span></div>' +
        '<h3 class="orp-h3 orp-h3-lg">' + esc(s.title) + '</h3>' +
        (s.meta && s.meta['Формат'] ? '<p class="orp-muted">' + esc(s.meta['Формат']) + '</p>' : '') +
        '<div class="orp-stage"><b>Задание ординатору</b><p>' + esc(s.task) + '</p></div>' +
        '<div class="orp-stage"><b>Материалы станции</b><p>' + esc(s.materials) + '</p></div>' +
        '<button type="button" class="orp-primary" id="orpOsceShowKey">Показать эталон и чек-лист</button>' +
        '<div id="orpOsceKey" class="orp-hidden">' +
          '<div class="orp-stage"><b>Эталон действий</b><p>' + esc(s.examiner_standard) + '</p></div>' +
          tableHtml(s.checklist) +
          '<div class="orp-stage"><b>Debrief</b><p>' + esc(s.debrief) + '</p></div>' +
        '</div>' +
        '<div class="orp-source">Источник: ' + esc(D.osce.source || '') + '</div></div>';
      q('#orpOsceShowKey', runner).addEventListener('click', function (e) {
        q('#orpOsceKey', runner).classList.remove('orp-hidden');
        e.currentTarget.classList.add('orp-hidden');
      });
      scrollTo(runner);
    }
    api.openOSCE = openOSCE;
  }

  /* ---------- Tumor Board ---------- */

  function setupTB(D, X, api) {
    var grid = q('#orpTbGrid'), runner = q('#orpTbRunner'), count = q('#orpTbCount');
    var items = (D.tumor_board && D.tumor_board.cases) || [];
    count.textContent = items.length + ' ' + plural(items.length, ['кейс', 'кейса', 'кейсов']);
    grid.innerHTML = items.map(function (c) {
      return '<article class="orp-card"><span class="orp-tag">' + esc(c.id) + '</span><h3 class="orp-h3">' + esc(c.title) + '</h3>' +
        '<div class="orp-muted">' + esc((c.meta && c.meta['Рекомендуемое время']) || '') + (c.meta && c.meta['Связанные модули'] ? ' · ' + esc(c.meta['Связанные модули']) : '') + '</div>' +
        '<button type="button" class="orp-primary orp-tb-open" data-id="' + esc(c.id) + '">Начать кейс</button></article>';
    }).join('');
    qa('.orp-tb-open', grid).forEach(function (b) { b.addEventListener('click', function () { startTB(b.getAttribute('data-id')); }); });

    function startTB(id) {
      var c = X.tb[id];
      if (!c) return;
      var visible = 1;
      setUrlParam('tb', id);
      function render() {
        var done = visible >= c.stages.length;
        runner.innerHTML = '<div class="orp-runner">' +
          '<div class="orp-cardtop"><span class="orp-tag">' + esc(c.id) + '</span><span class="orp-tag">' + esc((c.meta && c.meta['Рекомендуемое время']) || '') + '</span></div>' +
          '<h3 class="orp-h3 orp-h3-lg">' + esc(c.title) + '</h3>' +
          (c.meta && c.meta['Состав команды'] ? '<p class="orp-muted">Команда: ' + esc(c.meta['Состав команды']) + '</p>' : '') +
          '<p>' + esc(c.instruction || '') + '</p>' +
          c.stages.slice(0, visible).map(function (s) { return '<div class="orp-stage"><b>Этап ' + esc(s.stage) + '</b>' + (s.content || []).map(function (x) { return '<p>' + esc(x) + '</p>'; }).join('') + '</div>'; }).join('') +
          (done
            ? tableHtml(c.checklist) + '<div class="orp-stage"><b>Debrief</b><p>' + esc(c.debrief) + '</p></div>'
            : '<button type="button" class="orp-primary" id="orpTbNext">Зафиксировать решение и открыть этап ' + (visible + 1) + '</button>') +
          '<div class="orp-source">Источник: ' + esc(D.tumor_board.source || '') + '</div></div>';
        if (!done) q('#orpTbNext', runner).addEventListener('click', function () { visible++; render(); });
        scrollTo(runner);
      }
      render();
    }
    api.startTB = startTB;
  }

  /* ---------- календарь ---------- */

  function setupCalendar(D, X, api) {
    var box = q('#orpCalBox'), count = q('#orpCalCount'), controls = q('#orpCalControls');
    var rows = D.calendar || [];
    var modYear = {};
    D.modules.forEach(function (m) { modYear[normId(m.module_id)] = String(m.pedagogical_year); });
    var filter = 'all';
    count.textContent = rows.length + ' ' + plural(rows.length, ['занятие', 'занятия', 'занятий']);
    controls.innerHTML =
      '<button type="button" class="orp-pill is-active" data-cal="all">Все занятия</button>' +
      '<button type="button" class="orp-pill" data-cal="1">Модули 1-го года</button>' +
      '<button type="button" class="orp-pill" data-cal="2">Модули 2-го года</button>' +
      (D.calendar_docx ? '<a class="orp-btn orp-grow-right" href="' + esc(fileUrl(D.calendar_docx)) + '" target="_blank" rel="noopener">Календарный план 2026/2027 (DOCX)</a>' : '');
    function render() {
      var items = rows.filter(function (r) { return filter === 'all' || modYear[r.module] === filter; });
      box.innerHTML = '<div class="orp-tablewrap"><table class="orp-table orp-cal"><thead><tr><th>№</th><th>Дата</th><th>Тема</th><th>Лектор / формат</th><th>Раздел</th><th>Модуль</th></tr></thead><tbody>' +
        items.map(function (r) {
          var y = modYear[r.module] || '';
          var same = CFG.year === 'all' || CFG.year === y;
          var link = same
            ? '<button type="button" class="orp-minichip orp-cal-open" data-id="' + esc(r.module) + '">' + esc(r.module) + '</button>'
            : (CFG.yearUrls[y] ? '<a class="orp-minichip" href="' + esc(withParam(CFG.yearUrls[y], 'module', r.module)) + '">' + esc(r.module) + ' · ' + y + '-й год</a>' : '<span class="orp-minichip">' + esc(r.module) + ' · ' + y + '-й год</span>');
          return '<tr><td class="orp-num">' + esc(r.n) + '</td><td class="orp-num">' + esc(r.date) + '</td><td>' + esc(r.title) + '</td><td>' + esc(r.lecturer) + '</td><td>' + esc(r.section) + '</td><td>' + link + '</td></tr>';
        }).join('') + '</tbody></table></div>';
      qa('.orp-cal-open', box).forEach(function (b) { b.addEventListener('click', function () { api.open('module', b.getAttribute('data-id')); }); });
    }
    qa('.orp-pill[data-cal]', controls).forEach(function (b) {
      b.addEventListener('click', function () {
        qa('.orp-pill[data-cal]', controls).forEach(function (x) { x.classList.remove('is-active'); });
        b.classList.add('is-active'); filter = b.getAttribute('data-cal'); render();
      });
    });
    render();
  }

  /* ---------- сборка ---------- */

  var API = {
    open: function (kind, id) {
      if (kind === 'module') { activatePanel('modules'); API.openModule(id); }
      if (kind === 'vp') { activatePanel('vp'); API.startVP(id); }
      if (kind === 'osce') { activatePanel('osce'); API.openOSCE(id); }
      if (kind === 'tb') { activatePanel('tb'); API.startTB(id); }
    }
  };

  function init() {
    renderShell();
    qa('.orp-navbtn').forEach(function (b) {
      b.addEventListener('click', function () { activatePanel(b.getAttribute('data-panel')); setUrlParam('panel', b.getAttribute('data-panel')); });
    });
    notice('Загрузка учебных материалов…');

    fetch(CFG.dataUrl, { cache: 'no-cache' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (D) {
        notice('');
        var X = buildIndex(D);
        setupModules(D, X, API);
        setupLibrary(D);
        setupTests(D, X, API);
        setupVP(D, X, API);
        setupOSCE(D, X, API);
        setupTB(D, X, API);
        setupCalendar(D, X, API);

        // Глубокие ссылки: даём странице Tilda дорисоваться, затем открываем и прокручиваем.
        var p = new URLSearchParams(window.location.search);
        setTimeout(function () {
          if (p.get('module')) API.open('module', normId(p.get('module')));
          else if (p.get('vp')) API.open('vp', p.get('vp'));
          else if (p.get('osce')) API.open('osce', p.get('osce'));
          else if (p.get('tb')) API.open('tb', p.get('tb'));
          else if (p.get('panel')) activatePanel(p.get('panel'));
        }, 300);
      })
      .catch(function (err) {
        notice('Не удалось загрузить учебные материалы (' + err.message + '). Обновите страницу; если ошибка повторяется, сообщите на кафедру.', 'is-error');
      });
  }

  init();
})();
