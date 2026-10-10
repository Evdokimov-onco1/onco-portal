'use strict';
/* Проверка логики зачётного теста модуля из src/portal.js без браузера:
 * функция setupTests вырезается из исходника и выполняется в Node vm,
 * DOM заменён минимальными заглушками элементов (innerHTML, value,
 * disabled/hidden, обработчики кликов). Формула порога не копируется —
 * проверяется реальный код движка. */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'src', 'portal.js'), 'utf8');
const CUT = SRC.indexOf('function setupTests');
const END = SRC.indexOf('виртуальные пациенты ----------', CUT);
assert(CUT > 0 && END > CUT, 'блок setupTests не найден в portal.js');
const SETUP_SRC = SRC.slice(CUT, SRC.lastIndexOf('/*', END)) + '\n; setupTests;';

/* ---------- минимальные элементы ---------- */

function El() {
  this.attrs = {}; this._ev = {}; this._els = [];
  this._html = ''; this._text = '';
  this.value = ''; this.disabled = false; this.hidden = false;
}
El.prototype.addEventListener = function (t, f) { (this._ev[t] = this._ev[t] || []).push(f); };
El.prototype.emit = function (t) { (this._ev[t] || []).forEach(f => f({})); };
El.prototype.click = function () {
  if (this.disabled) return;
  (this._ev.click || []).forEach(f => f({ target: this, currentTarget: this, preventDefault: function () {} }));
};
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.insertAdjacentHTML = function (pos, html) { if (pos === 'beforeend') this.innerHTML = this._html + html; };
El.prototype.scrollIntoView = function () {};
Object.defineProperty(El.prototype, 'innerHTML', {
  get() { return this._html; },
  set(v) { this._html = String(v); this._els = scan(this._html); }
});
Object.defineProperty(El.prototype, 'textContent', {
  get() { return this._text; },
  set(v) { this._text = String(v); }
});
Object.defineProperty(El.prototype, 'classList', {
  get() {
    const self = this;
    const list = () => (self.attrs.class || '').split(/\s+/).filter(Boolean);
    return {
      add: c => { const s = new Set(list()); s.add(c); self.attrs.class = [...s].join(' '); },
      toggle: (c, f) => { const s = new Set(list()); (f === undefined ? !s.has(c) : f) ? s.add(c) : s.delete(c); self.attrs.class = [...s].join(' '); },
      contains: c => list().includes(c)
    };
  }
});

// Плоский разбор тегов сгенерированной разметки (атрибуты только в кавычках).
function scan(html) {
  const els = [];
  const re = /<([a-zA-Z][\w-]*)((?:"[^"]*"|[^>"]*)*)>/g;
  let m;
  while ((m = re.exec(html))) {
    const e = new El();
    const ar = /([\w-]+)(?:\s*=\s*"([^"]*)")?/g;
    let am;
    while ((am = ar.exec(m[2]))) e.attrs[am[1]] = am[2] === undefined ? '' : am[2];
    if ('disabled' in e.attrs) e.disabled = true;
    if ('hidden' in e.attrs) e.hidden = true;
    const rest = html.slice(re.lastIndex), lt = rest.indexOf('<');
    e._text = lt < 0 ? rest : rest.slice(0, lt);
    els.push(e);
  }
  return els;
}
function match(e, sel) {
  if (sel[0] === '#') return e.attrs.id === sel.slice(1);
  if (sel[0] === '.') return (e.attrs.class || '').split(/\s+/).includes(sel.slice(1));
  return false;
}
function collectDeep(el, sel, out) {
  out = out || [];
  (el._els || []).forEach(e => { if (match(e, sel)) out.push(e); collectDeep(e, sel, out); });
  return out;
}
function findDeep(el, sel) { return collectDeep(el, sel)[0] || null; }

/* ---------- утилиты движка (копии для окружения vm) ---------- */

const normId = s => { const m = String(s || '').match(/[МM]\s*-?\s*0*(\d+)/); if (!m) return String(s || '').trim(); const n = m[1]; return 'M' + (n.length < 2 ? '0' + n : n); };
const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const plural = (n, f) => { const a = Math.abs(n) % 100, b = a % 10; if (a > 10 && a < 20) return f[2]; if (b > 1 && b < 5) return f[1]; if (b === 1) return f[0]; return f[2]; };

function makeApp(D, seed) {
  const els = {};
  ['orpTestModule', 'orpTestN', 'orpTestBox', 'orpTestCount', 'orpTestHint', 'orpStartTest'].forEach(id => { els[id] = new El(); });
  let s = seed || 12345;
  const MathDet = Object.create(Math);
  MathDet.random = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648;
  const sandbox = {
    esc, normId, plural, Math: MathDet,
    q: (sel, ctx) => ctx ? findDeep(ctx, sel) : els[sel.slice(1)] || null,
    qa: (sel, ctx) => collectDeep(ctx, sel),
    sendResult() {}, activatePanel() {}, setUrlParam() {}, scrollTo() {},
    CFG: { year: 'all', resultsUrl: '' }
  };
  vm.createContext(sandbox);
  const shuffleStart = SRC.indexOf('var shuffle = function');
  const shuffleEnd = SRC.indexOf('var q = function', shuffleStart);
  assert(shuffleStart > 0 && shuffleEnd > shuffleStart);
  vm.runInContext(SRC.slice(shuffleStart, shuffleEnd), sandbox);
  const setupTests = vm.runInContext(SETUP_SRC, sandbox);
  const api = {};
  setupTests(D, {}, api);
  return { els, api };
}

/* ---------- данные: реальный банк M05 + синтетика ---------- */

const real = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', 'orp-data.json'), 'utf8'));
const M05 = real.questions.filter(x => normId(x.module) === 'M05');
assert.equal(M05.length, 16, 'в реальном банке M05 должно быть 16 вопросов');
const mkModule = (id, year) => ({ module_id: id, module_title: 'Синтетический ' + id, pedagogical_year: year, clinical_cases: [] });
const mkQ = (id, mod, year, i) => ({ id, module: mod, year, stem: 'Вопрос ' + id, options: ['а', 'б', 'в', 'г'], correct: 'ABCD'[i % 4], explanation: 'Пояснение ' + id });
function bank() {
  const qs = M05.map(q => Object.assign({}, q));
  for (let i = 1; i <= 10; i++) qs.push(mkQ('T10-' + i, 'M10', 2, i));
  for (let i = 1; i <= 23; i++) qs.push(mkQ('T99-' + i, 'M99', 1, i));
  return { questions: qs, modules: [real.modules.find(m => normId(m.module_id) === 'M05'), mkModule('M10', 2), mkModule('M99', 1), mkModule('M00', 1)] };
}
const byId = D => { const m = {}; D.questions.forEach(x => { m[x.id] = x; }); return m; };

/* ---------- драйвер попытки ---------- */

function selectAndStart(app, moduleId, n) {
  app.els.orpTestModule.value = moduleId;
  app.els.orpTestModule.emit('change');
  if (n != null) app.els.orpTestN.value = String(n);
  app.els.orpStartTest.click();
  const begin = findDeep(app.els.orpTestBox, '#orpTestBegin');
  assert(begin, 'ожидался экран правил с кнопкой «Начать»');
  begin.click();
}
function runAttempt(app, idx, nCorrect, twice) {
  const box = app.els.orpTestBox, seen = [];
  let guard = 0;
  while (!/Результат:/.test(box.innerHTML)) {
    assert(guard++ < 100, 'проход вопросов не завершился');
    const muted = collectDeep(box, '.orp-muted')[0];
    const id = muted._text.split('·')[0].trim();
    seen.push(id);
    const choices = collectDeep(box, '.orp-choice');
    const btn = choices.find(b => (b.getAttribute('data-key') === idx[id].correct) === (seen.length <= nCorrect));
    assert(btn, 'нет подходящего варианта для ' + id);
    btn.click();
    if (twice) { btn.click(); btn.emit('click'); } // Проверяем также флаг answered, минуя disabled в заглушке.
    findDeep(box, '#orpNextTest').click();
  }
  return seen;
}

/* ---------- сценарии ---------- */

test('выбор модуля скрывает счётчик и объясняет правило зачёта', () => {
  const app = makeApp(bank());
  app.els.orpTestModule.value = 'M05'; app.els.orpTestModule.emit('change');
  assert.strictEqual(app.els.orpTestN.disabled, true);
  assert.strictEqual(app.els.orpTestN.hidden, true);
  assert.match(app.els.orpTestHint.textContent, /Зачёт модуля M05[\s\S]*минимум 12 из 16/);
  app.els.orpTestModule.value = ''; app.els.orpTestModule.emit('change');
  assert.strictEqual(app.els.orpTestN.hidden, false);
  assert.match(app.els.orpTestHint.textContent, /Тренировка[\s\S]*не засчитывается/);
});

test('зачёт M05 из общего банка: 16 вопросов без дублей, 12/16 зачтён', () => {
  const D = bank(), app = makeApp(D), idx = byId(D);
  selectAndStart(app, 'M05');
  const seen = runAttempt(app, idx, 12);
  assert.equal(seen.length, 16);
  assert.equal(new Set(seen).size, 16);
  assert.match(app.els.orpTestBox.innerHTML, /Результат: 12 \/ 16 \(75%\)[\s\S]*Тест зачтён/);
  assert.doesNotMatch(app.els.orpTestBox.innerHTML, /доставлено|отправлен преподавателю/i);
});

test('зачёт M05 из карточки модуля: все 16, 11/16 не зачтён', () => {
  const D = bank(), app = makeApp(D), idx = byId(D);
  app.api.startModuleTest('M05');
  assert.strictEqual(app.els.orpTestN.hidden, true);
  findDeep(app.els.orpTestBox, '#orpTestBegin').click();
  const seen = runAttempt(app, idx, 11);
  assert.equal(new Set(seen).size, 16);
  assert.match(app.els.orpTestBox.innerHTML, /Результат: 11 \/ 16 \(69%\)[\s\S]*Тест не зачтён/);
});

test('граница порога: 7/10 зачтён, 16/23 не зачтён до округления', () => {
  const D = bank(), app = makeApp(D), idx = byId(D);
  selectAndStart(app, 'M10');
  runAttempt(app, idx, 7);
  assert.match(app.els.orpTestBox.innerHTML, /Результат: 7 \/ 10 \(70%\)[\s\S]*Тест зачтён/);
  selectAndStart(app, 'M99');
  runAttempt(app, idx, 16);
  const html = app.els.orpTestBox.innerHTML;
  assert.match(html, /Результат: 16 \/ 23 \(70%\)/);
  assert.match(html, /Тест не зачтён/);
});

test('повторная попытка проходит весь банк заново и сбрасывает счёт', () => {
  const D = bank(), app = makeApp(D), idx = byId(D);
  app.api.startModuleTest('M05');
  findDeep(app.els.orpTestBox, '#orpTestBegin').click();
  runAttempt(app, idx, 11);
  assert.match(app.els.orpTestBox.innerHTML, /Тест не зачтён/);
  findDeep(app.els.orpTestBox, '#orpTestAgain').click();
  const seen = runAttempt(app, idx, 16);
  assert.equal(new Set(seen).size, 16);
  assert.match(app.els.orpTestBox.innerHTML, /Результат: 16 \/ 16 \(100%\)[\s\S]*Тест зачтён/);
});

test('пустой банк и модуль без вопросов не падают и не зачитываются', () => {
  const empty = makeApp({ questions: [], modules: [] });
  empty.els.orpStartTest.click();
  assert.match(empty.els.orpTestBox.innerHTML, /В банке пока нет вопросов/);
  const app = makeApp(bank());
  app.els.orpTestModule.value = 'M00'; app.els.orpTestModule.emit('change');
  app.els.orpStartTest.click();
  assert.match(app.els.orpTestBox.innerHTML, /не найдены/);
  assert.doesNotMatch(app.els.orpTestBox.innerHTML, /Тест зачтён/);
});

test('тренировка «все модули»: смешанная выборка без зачёта', () => {
  const D = bank(), app = makeApp(D), idx = byId(D);
  selectAndStart(app, '', 20);
  const seen = runAttempt(app, idx, 20);
  assert.equal(seen.length, 20);
  assert.equal(new Set(seen).size, 20);
  assert(new Set(seen.map(id => normId(idx[id].module))).size > 1, 'выборка должна быть смешанной');
  assert.match(app.els.orpTestBox.innerHTML, /тренировка[\s\S]*не засчитывается/i);
  assert.doesNotMatch(app.els.orpTestBox.innerHTML, /Тест зачтён/);
});

test('двойной клик по ответу не начисляет очки дважды', () => {
  const D = bank(), app = makeApp(D), idx = byId(D);
  app.api.startModuleTest('M05');
  findDeep(app.els.orpTestBox, '#orpTestBegin').click();
  runAttempt(app, idx, 16, true);
  assert.match(app.els.orpTestBox.innerHTML, /Результат: 16 \/ 16 \(100%\)/);
});

test('попытка не мутирует данные банка', () => {
  const D = bank(), snap = JSON.stringify(D.questions);
  const app = makeApp(D), idx = byId(D);
  app.api.startModuleTest('M05');
  findDeep(app.els.orpTestBox, '#orpTestBegin').click();
  runAttempt(app, idx, 12);
  assert.equal(JSON.stringify(D.questions), snap);
});


test('смена выбора во время попытки не меняет её банк и вердикт', () => {
  const D = bank(), app = makeApp(D), idx = byId(D);
  selectAndStart(app, 'M05', 5);
  app.els.orpTestModule.value = ''; app.els.orpTestModule.emit('change');
  app.els.orpTestN.value = '5';
  const seen = runAttempt(app, idx, 12);
  assert.equal(seen.length, 16);
  assert(seen.every(id => idx[id].module === 'M05'));
  assert.match(app.els.orpTestBox.innerHTML, /Тест зачтён/);
  assert.doesNotMatch(app.els.orpTestBox.innerHTML, /Это тренировка/);
});
