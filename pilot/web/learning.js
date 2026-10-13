'use strict';
const panels=[['materials','Лекция и материалы'],['cases','Клинические задачи'],['quiz','Тест'],['seminar','Семинар'],['practice','OSCE / Tumor Board'],['tools','Инструменты и навыки'],['progress','Прогресс']];
const listText=items=>`<ul>${items.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`;
const moduleUrl=(id,panel='materials')=>'/?'+new URLSearchParams({module:id,panel});
function catalogCards(year,query=''){
 const rows=state.modules.filter(m=>String(m.year)===String(year)&&`${m.id} ${m.title}`.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru').trim()));
 return rows.map(m=>`<a class="module-card" href="${esc(moduleUrl(m.id))}"><span class="eyebrow">${esc(m.id)} · ${esc(m.year)} год</span><h2>${esc(m.title)}</h2><span class="module-card__open">Открыть модуль <span aria-hidden="true">→</span></span></a>`).join('')||'<p class="empty">По вашему запросу модулей не найдено.</p>';
}
function studentCatalog(){
 invalidatePracticeLoads();invalidateCompletionLoads();
 const requested=new URLSearchParams(location.search).get('year');
 state.catalogYear=['1','2'].includes(requested)?requested:'1';
 document.title='Модули ординатуры · ONCO';
 app.innerHTML=`<div class="eyebrow">Учебный кабинет</div><h1>Модули ординатуры</h1><p class="muted intro">Выберите год обучения и тему. Каждый модуль — отдельная страница с материалами, заданиями и прогрессом.</p><section class="catalog-controls" aria-label="Выбор модуля"><div class="year-switch" aria-label="Год обучения">${['1','2'].map(y=>`<button data-year="${y}" aria-pressed="${y===state.catalogYear}">${y} год <span>${state.modules.filter(m=>String(m.year)===y).length}</span></button>`).join('')}</div><label class="module-search">Найти модуль<input id="moduleSearch" type="search" placeholder="Название темы или номер модуля"></label></section><p class="help" id="catalogCount" role="status"></p><div class="module-grid" id="moduleGrid"></div>`;
 const draw=()=>{document.querySelector('#moduleGrid').innerHTML=catalogCards(state.catalogYear,document.querySelector('#moduleSearch').value);document.querySelector('#catalogCount').textContent=`${state.catalogYear} год · найдено модулей: ${document.querySelectorAll('.module-card').length}`;};
 document.querySelector('#moduleSearch').addEventListener('input',draw);
 document.querySelectorAll('[data-year]').forEach(b=>b.addEventListener('click',()=>{state.catalogYear=b.dataset.year;document.querySelectorAll('[data-year]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));history.replaceState(null,'','/?'+new URLSearchParams({year:state.catalogYear}));draw();}));draw();
}
function navMarkup(){return `<nav class="module-nav" aria-label="Разделы модуля">${panels.map(([id,title])=>`<button data-panel="${id}" ${state.panel===id?'aria-current="page" class="selected"':''}>${title}</button>`).join('')}</nav>`;}
function wireNav(){
 document.querySelectorAll('[data-panel]').forEach(b=>b.addEventListener('click',()=>{
  if(state.panel===b.dataset.panel)return;
  if(!safeLeave())return;
  invalidateCompletionLoads();state.panel=b.dataset.panel;student();
 }));
 window.history.replaceState(null,'',moduleUrl(state.module.id,state.panel));
}
function moduleShell(content,extraSidebar=''){
 const m=state.module;
 document.title=`${m.id} · ${m.title} · ONCO`;
 app.innerHTML=`<a class="module-back" href="/?year=${esc(m.year)}">← Все модули ${esc(m.year)} года</a><div class="eyebrow">Ординатура · ${esc(m.year)} год · ${esc(m.id)}</div><h1>${esc(m.title)}</h1><div class="module-workspace"><section class="paper learning-content ${state.panel==='materials'?'materials-workspace':''}">${content}</section><aside class="module-sidebar"><div class="sidebar-card"><div class="eyebrow">В этом модуле</div>${navMarkup()}</div>${extraSidebar}<details class="sidebar-card route-summary"><summary>Мой учебный маршрут</summary><p>Изучите материалы, решите задачи и пройдите тест.</p><div><strong>${new Set(m.attempts.filter(a=>a.version===m.version).map(a=>a.case)).size} / ${m.cases.length}</strong> задач отправлено</div><div><strong>${m.question_count}</strong> вопросов в полном тесте</div><div><strong>${m.quizzes.filter(q=>q.submitted_at).length}</strong> тестовых попыток завершено</div></details><label for="module">Другой модуль ${esc(m.year)} года</label><select id="module">${state.modules.filter(x=>String(x.year)===String(m.year)).map(x=>`<option value="${esc(x.id)}" ${x.id===m.id?'selected':''}>${esc(x.id+' · '+x.title)}</option>`).join('')}</select></aside></div>`;
 document.querySelector('#module').addEventListener('change',e=>{if(!safeLeave()){e.target.value=m.id;return;}state.dirty.clear();location.assign(moduleUrl(e.target.value));});wireNav();
}
function resourceMarkup(r){
 const open=state.module.opened[r.id];
 return `<li class="resource-item"><div>${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer" data-resource="${esc(r.id)}">${esc(r.title)}</a>`:`<strong>${esc(r.title)}</strong>`}${r.note?`<p class="muted">${esc(r.note)}</p>`:''}</div><small class="resource-status" data-open-state="${esc(r.id)}">${open?'Открытие записано':r.url?'Открыть ↗':'Ссылка не указана'}</small></li>`;
}
function wireResources(){
 document.querySelectorAll('[data-resource]').forEach(a=>a.addEventListener('click',()=>{
  const moduleId=state.module?.id,userId=state.user?.id,panel=state.panel,id=a.dataset.resource,loadId=state.completionLoadId;
  api('/api/resources/open',{module:moduleId,version:state.module.materials.version,resource:id}).then(()=>{
   if(state.user?.id!==userId||state.module?.id!==moduleId||state.panel!==panel||state.user?.role!=='student')return;
   if(loadId!==state.completionLoadId)return;
   state.module.opened[id]=new Date().toISOString();const badge=document.querySelector(`[data-open-state="${id}"]`);if(badge)badge.textContent='Открытие записано';
  }).catch(()=>notify('Материал открыт, но отметка не сохранена. Повторите открытие после восстановления связи.',true));
 }));
}
function formatTimecode(sec){
 const s=Math.max(0,Math.floor(Number(sec)||0));
 return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;
}
function parseTimecode(s){
 const t=String(s||'').trim();
 if(/^\d+$/.test(t))return Number(t);
 const p=t.split(':').map(x=>/^\d+$/.test(x)?Number(x):NaN);
 if(p.length<2||p.length>3||p.some(Number.isNaN))return null;
 if(p.length===2)return p[1]<60?p[0]*60+p[1]:null;
 return p[1]<60&&p[2]<60?p[0]*3600+p[1]*60+p[2]:null;
}
function videoFeedbackPayload(moduleId,v,timecode,comment){
 return {schema:'onco-video-feedback/v1',module:moduleId,lecture_id:v.lecture_id||null,
  video_id:v.video_id||null,video_url:v.url||'',timecode_seconds:timecode,
  comment:String(comment||'').trim(),boundary_status:v.boundary_status||'provisional',
  generated_at:new Date().toISOString()};
}
function suggestedVideoMarkup(v){
 const open=state.module.opened[v.id];
 const offset=v.launch_offset_seconds!=null?` · старт ~${formatTimecode(v.launch_offset_seconds)}`:'';
 const warn=v.truncation_risk?`<p class="help warn">${esc(v.truncation_warning||'Возможен обрыв записи — полнота лекции не подтверждена.')}</p>`:'';
 return `<li class="resource-item suggested-video"><div><strong>${esc(v.title)}</strong><p class="muted">${esc(v.speaker||'')}${esc(offset)}</p><p class="help">Запись предварительно сопоставлена с модулем; границы лекции ориентировочные. Зачёта нет, пока преподаватель не подтвердит запись.</p>${warn}<div class="actions">${v.mp4_url?`<button type="button" data-vplay="${esc(v.id)}">Показать запись в плеере</button>`:''}${v.url?`<a class="video-fallback" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer" data-resource="${esc(v.id)}">Открыть на YouTube с таймкодом ↗</a>`:''}</div><details class="video-feedback"><summary>Замечание к границам записи</summary><label>Таймкод (мм:сс)<input type="text" class="vfb-time" inputmode="numeric" placeholder="12:34"></label><div class="actions"><button type="button" class="vfb-capture" data-vcap="${esc(v.id)}">Подставить текущее время плеера</button></div><label>Комментарий<textarea class="vfb-comment" maxlength="2000" placeholder="Что проверить по границе…"></textarea></label><div class="actions"><button type="button" data-vfb="${esc(v.id)}">Скачать замечание (JSON)</button></div><p class="help muted">В файле только модуль, запись, таймкод и комментарий — без имени и аккаунта.</p></details></div><small class="resource-status" data-open-state="${esc(v.id)}">${open?'Открытие записано':v.url?'Открыть с таймкодом ↗':'Ссылка не указана'}</small></li>`;
}
function wireSuggestedPlayer(){
 const section=document.querySelector('[data-suggested-player]');
 if(!section)return;
 const video=section.querySelector('video'),status=section.querySelector('[data-vplayer-status]'),go=section.querySelector('[data-vplayer-go]'),warn=section.querySelector('[data-vplayer-warn]');
 const items=(state.module?.materials?.faculty_videos||[]).filter(v=>v.kind==='suggested_video');
 section._vidSeq=0;section._vidLecture=null;section._vidReady=false;
 video.addEventListener?.('error',()=>{
  if(video._vidSeq!==section._vidSeq)return;
  section._vidReady=false;if(go)go.hidden=true;
  if(status)status.textContent='Не удалось загрузить запись — откройте её на YouTube по ссылке у лекции.';
 });
 document.querySelectorAll('[data-vplay]').forEach(b=>b.addEventListener('click',()=>{
  const v=items.find(x=>x.id===b.dataset.vplay);
  if(!v||!v.mp4_url)return;
  const seq=++section._vidSeq;section._vidLecture=v.id;section._vidReady=false;
  video._vidSeq=seq;
  const moduleId=state.module?.id,userId=state.user?.id,matVersion=state.module?.materials?.version;
  video.hidden=false;if(go)go.hidden=true;
  if(warn){warn.hidden=!v.truncation_risk;if(v.truncation_risk)warn.textContent=v.truncation_warning||'Возможен обрыв записи — полнота лекции не подтверждена.';}
  if(status)status.textContent='Загрузка записи «'+v.title+'»…';
  video.pause?.();
  const onMeta=()=>{
   video.removeEventListener?.('loadedmetadata',onMeta);
   if(section._vidSeq!==seq||section._vidLecture!==v.id||video.isConnected===false)return;
   try{video.currentTime=v.launch_offset_seconds||0;}catch(e){}
   section._vidReady=true;
   if(status)status.textContent=`Готово: старт ~${formatTimecode(v.launch_offset_seconds||0)}. Воспроизведение — только по вашей кнопке.`;
   if(go)go.hidden=false;
  };
  video.addEventListener?.('loadedmetadata',onMeta);
  video.src=v.mp4_url;
  video.load?.();
  api('/api/resources/open',{module:moduleId,version:matVersion,resource:v.id}).then(()=>{
   if(state.user?.id!==userId||state.module?.id!==moduleId)return;
   state.module.opened[v.id]=new Date().toISOString();
   const badge=document.querySelector(`[data-open-state="${v.id}"]`);if(badge)badge.textContent='Открытие записано';
  }).catch(()=>{if(state.module?.id===moduleId&&state.user?.id===userId)notify('Запись открыта, но отметка не сохранена. Повторите после восстановления связи.',true);});
 }));
 go?.addEventListener('click',()=>{
  const seq=section._vidSeq,lec=section._vidLecture;
  const p=video.play?.();
  if(p&&p.catch)p.catch(()=>{
   if(section._vidSeq!==seq||section._vidLecture!==lec||video.isConnected===false)return;
   if(status)status.textContent='Не удалось запустить запись — откройте её на YouTube по ссылке у лекции.';
  });
 });
}
function wireVideoFeedback(){
 const section=document.querySelector('[data-suggested-player]');
 const video=section?.querySelector('video');
 document.querySelectorAll('[data-vcap]').forEach(b=>b.addEventListener('click',()=>{
  const v=(state.module?.materials?.faculty_videos||[]).find(x=>x.id===b.dataset.vcap);
  const box=b.closest('.video-feedback');
  if(!v||!box)return;
  if(!video||section._vidLecture!==v.id||!section._vidReady||!Number.isFinite(video.currentTime)){notify('Сначала загрузите в плеере запись этой лекции и дождитесь готовности.',true);return;}
  box.querySelector('.vfb-time').value=formatTimecode(video.currentTime);
  notify('Подставлено время плеера '+formatTimecode(video.currentTime)+'.');
 }));
 document.querySelectorAll('[data-vfb]').forEach(b=>b.addEventListener('click',()=>{
  const v=(state.module?.materials?.faculty_videos||[]).find(x=>x.id===b.dataset.vfb);
  const box=b.closest('.video-feedback');
  if(!v||!box)return;
  const tc=parseTimecode(box.querySelector('.vfb-time')?.value);
  if(tc===null||!Number.isFinite(tc)){notify('Укажите таймкод в секундах или в формате мм:сс.',true);return;}
  const comment=String(box.querySelector('.vfb-comment')?.value||'').trim();
  if(!comment){notify('Напишите комментарий к замечанию.',true);return;}
  const payload=videoFeedbackPayload(state.module.id,v,tc,comment);
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url;a.download=`video-feedback-${state.module.id}-${v.lecture_id||v.id}.json`;
  document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  notify('Скачивание запрошено — передайте файл преподавателю.');
 }));
}
function materialsPanel(){
 const c=state.module.materials,archives=c.groups.find(g=>g.id==='lectures');
 const sugg=c.faculty_videos.filter(v=>v.kind==='suggested_video'),others=c.faculty_videos.filter(v=>v.kind!=='suggested_video');
 moduleShell(`<div class="material-heading"><div class="eyebrow">01 · Изучить</div><h2>Лекция и материалы</h2><p class="muted">Выберите нужный блок. Дополнительные источники открываются по нажатию.</p></div><section class="material-card"><div class="eyebrow">Лекция</div><h3>${esc(c.lecture||state.module.title)}</h3>${sugg.length?`<section class="faculty suggested-lectures"><h3>Записи занятий · предварительная привязка</h3><p class="help">Записи предварительно сопоставлены с модулем; таймкоды ориентировочные. Для зачёта нужна явная привязка преподавателя на вкладке «Завершение модуля».</p><ul class="resources">${sugg.map(suggestedVideoMarkup).join('')}</ul><div class="suggested-player" data-suggested-player><video controls preload="none" playsinline hidden></video><p class="help" data-vplayer-status>Выберите запись — видео загрузится только после вашего действия.</p><p class="help warn" data-vplayer-warn hidden></p><div class="actions"><button type="button" data-vplayer-go hidden>▶ Запустить запись</button></div></div></section>`:''}<details class="faculty"><summary>Кафедральные видеозаписи · ${others.length}</summary>${others.length?`<p class="help">Ниже записи с сайта кафедры, предварительно сопоставленные по теме. Привязка преподавателем и воспроизведение ещё не подтверждены.</p><ul class="resources">${others.slice(0,3).map(resourceMarkup).join('')}</ul>${others.length>3?`<details class="reading-group"><summary>Ещё записей по теме: ${others.length-3}</summary><ul class="resources">${others.slice(3).map(resourceMarkup).join('')}</ul></details>`:''}`:'<p class="muted">Точная кафедральная запись к этому модулю пока не сопоставлена. Видеоархивы ниже доступны для дополнительной подготовки.</p>'}</details></section>${c.groups.filter(g=>g.id!=='lectures').map((g,i)=>`<details class="reading-group material-card"><summary>${esc(({guidelines:'Рекомендации и нормативные документы',reviews:'Что читать: обзоры и учебники'})[g.id]||g.title)} <span>${g.items.length}</span></summary>${g.items.length?`<ul class="resources">${g.items.map(resourceMarkup).join('')}</ul>`:'<p class="muted">В исходном пакете материалы этого типа не указаны.</p>'}</details>`).join('')}<details class="reading-group material-card"><summary>${esc(archives.title)} <span>${archives.items.length}</span></summary><p class="help">Это общие архивы и платформы; они не заменяют точную ссылку на кафедральную лекцию.</p><ul class="resources">${archives.items.map(resourceMarkup).join('')}</ul></details><p class="help">Отметка фиксирует открытие ссылки. Она не доказывает просмотр видео или изучение материала.</p><section class="material-card next-step"><div><div class="eyebrow">Следующий шаг</div><h3>Клинические задачи семинара</h3><p class="muted">Сформулируйте решение и отправьте его преподавателю.</p></div><button class="primary" data-panel="cases">Перейти к задачам →</button></section>`);
 wireResources();
 wireSuggestedPlayer();
 wireVideoFeedback();
}
function toolsPanel(){
 const c=state.module.materials;
 const cards=items=>items.map(t=>`<li class="resource-item"><div>${t.url?`<a href="${esc(t.url)}" target="_blank" rel="noopener noreferrer">${esc(t.name)}</a>`:`<strong>${esc(t.name)}</strong>`}<p class="muted">${esc(t.teaching||t.notes||'')}</p>${t.safety?`<p class="help">${esc(t.safety)}</p>`:''}</div></li>`).join('');
 moduleShell(`<div class="eyebrow">Практические ресурсы</div><h2>Инструменты и чек-лист</h2><h3>Клинические инструменты</h3><ul class="resources">${cards(c.tools)}</ul>${c.tools.length?'':'<p class="muted">Отдельные инструменты в исходнике не назначены.</p>'}<h3>Внешние симуляторы</h3><ul class="resources">${cards(c.simulators)}</ul><h3>Навыки для самопроверки</h3>${listText(c.checklist)}<p class="help">Чек-лист описывает ожидаемые навыки. Преподавательская отметка выполнения будет добавлена в логбук.</p>`);
}
function quizResult(q){
 return `<div class="quiz-result ${q.passed?'pass':'fail'}"><div class="eyebrow">Полная попытка сохранена</div><h2>${q.passed?'Тест зачтён':'Тест пока не зачтён'}</h2><p><strong>${q.score} из ${q.total} · ${Math.round(100*q.score/q.total)}%</strong></p><p>Для зачёта нужно не менее ${Math.ceil(.7*q.total)} правильных ответов. Решение рассчитано по точной доле, до округления.</p><p class="help">${stamp(q.submitted_at)} · результат теста не заменяет подтверждение модуля преподавателем.</p></div><details class="reading-group"><summary>Разобрать ответы</summary>${q.questions.map((x,i)=>`<section class="quiz-review"><strong>${i+1}. ${esc(x.stem)}</strong><p>Ваш ответ: ${esc(q.answers[x.id])} · Верный: ${esc(x.correct)}</p><p class="text">${esc(x.explanation||'')}</p>${/^https?:\/\//.test(x.source_url||'')?`<a href="${esc(x.source_url)}" target="_blank" rel="noopener noreferrer">${esc(x.source_title||'Источник')}</a>`:''}</section>`).join('')}</details>`;
}
function quizPanel(){
 const m=state.module,q=state.quiz;
 if(q&&!q.submitted_at){
  state.quizIndex=Math.max(0,Math.min(state.quizIndex||0,q.questions.length-1));
  const question=q.questions[state.quizIndex],answered=Object.keys(q.answers).length;
  moduleShell(`<div class="eyebrow">Полный тест · ${m.id}</div><h2>Вопрос ${state.quizIndex+1} из ${q.total}</h2><p class="muted">${answered} ответов сохранено · порог зачёта 70%</p><div class="question-dots" aria-label="Перейти к вопросу">${q.questions.map((x,i)=>`<button data-q-index="${i}" ${i===state.quizIndex?'aria-current="step"':''} class="${q.answers[x.id]?'answered':''}">${i+1}</button>`).join('')}</div><fieldset class="quiz-question"><legend>${esc(question.stem)}</legend>${question.options.map((text,i)=>{const code=String.fromCharCode(65+i);return `<label class="quiz-option"><input type="radio" name="quiz-answer" value="${code}" ${q.answers[question.id]===code?'checked':''}><span>${code}. ${esc(text)}</span></label>`;}).join('')}</fieldset><p class="help" id="quizSaveState">${state.dirty.has('quiz')?'Есть несохранённый ответ — повторите сохранение.':'Ответ сохраняется после выбора. Можно продолжить попытку после повторного входа.'}</p><div class="actions"><button id="quizPrev" ${state.quizIndex===0?'disabled':''}>← Назад</button><button id="quizSave">Сохранить ответы</button>${state.quizIndex<q.total-1?'<button id="quizNext">Далее →</button>':''}<button class="primary" id="quizSubmit" ${answered!==q.total?'disabled':''}>Завершить тест</button></div><p class="help">Завершение доступно после ответа на все ${q.total} вопросов. До завершения правильные ответы не выдаются.</p>`);
  const save=async()=>{state.quiz=await api('/api/quizzes/save',{id:q.id,answers:q.answers});state.dirty.delete('quiz');state.module.quizzes=state.module.quizzes.map(a=>a.id===q.id?state.quiz:a);quizPanel();};
  document.querySelectorAll('[name="quiz-answer"]').forEach(r=>r.addEventListener('change',()=>{q.answers[question.id]=r.value;state.dirty.add('quiz');action(r,save);}));
  document.querySelectorAll('[data-q-index]').forEach(b=>b.addEventListener('click',()=>{state.quizIndex=Number(b.dataset.qIndex);quizPanel();}));
  document.querySelector('#quizPrev').addEventListener('click',()=>{state.quizIndex--;quizPanel();});
  document.querySelector('#quizNext')?.addEventListener('click',()=>{state.quizIndex++;quizPanel();});
  document.querySelector('#quizSave').addEventListener('click',e=>action(e.target,save));
  document.querySelector('#quizSubmit').addEventListener('click',e=>action(e.target,async()=>{state.quiz=await api('/api/quizzes/submit',{id:q.id,answers:q.answers});state.dirty.delete('quiz');state.module=await api('/api/modules/'+m.id);quizPanel();notify('Попытка завершена и сохранена. Результат доступен преподавателю.');}));
  return;
 }
 const ongoing=m.quizzes.filter(a=>!a.submitted_at),done=m.quizzes.filter(a=>a.submitted_at);
 moduleShell(`<div class="eyebrow">03 · Самоконтроль</div><h2>Полный тест модуля</h2><p>Все <strong>${m.question_count} вопросов</strong> из банка этого модуля. Для зачёта нужно <strong>не менее 70%</strong>. Повторные попытки сохраняются в истории.</p>${q?.submitted_at?quizResult(q):''}${ongoing.map(a=>`<button class="queue-item" data-quiz="${esc(a.id)}"><strong>Продолжить начатую попытку</strong>${Object.keys(a.answers).length} из ${a.total} ответов · ${stamp(a.created_at)}</button>`).join('')}<div class="actions"><button class="primary" id="quizStart" ${!m.question_count?'disabled':''}>${done.length?'Начать новую попытку':'Начать полный тест'}</button></div><h3>История попыток · ${done.length}</h3>${done.map(a=>`<button class="queue-item" data-quiz="${esc(a.id)}"><span class="badge ${a.passed?'accepted':'returned'}">${a.passed?'Зачтён':'Не зачтён'}</span> <strong>${a.score} из ${a.total} · ${Math.round(a.score/a.total*100)}%</strong><small>${stamp(a.submitted_at)}</small></button>`).join('')||'<p class="muted">Завершённых попыток ещё нет.</p>'}`);
 document.querySelector('#quizStart').addEventListener('click',e=>action(e.target,async()=>{if(!state.quizStartKey)state.quizStartKey=crypto.randomUUID();state.quiz=await api('/api/quizzes/start',{module:m.id,key:state.quizStartKey});state.quizStartKey=null;state.quizIndex=0;state.module=await api('/api/modules/'+m.id);quizPanel();}));
 document.querySelectorAll('[data-quiz]').forEach(b=>b.addEventListener('click',()=>action(b,async()=>{state.quiz=await api('/api/quizzes/'+encodeURIComponent(b.dataset.quiz));state.quizIndex=0;quizPanel();})));
}
function progressPanel(){
 moduleShell(`<div id="completion-root"><p class="muted">Загружаем чек-лист с сервера…</p></div>`);
 loadCompletion();
}
function student(){
 if(!panels.some(([id])=>id===state.panel))state.panel='materials';
 if(state.panel==='cases'){studentCases();return;}
 ({materials:materialsPanel,quiz:quizPanel,seminar:seminarPanel,practice:practicePanel,tools:toolsPanel,progress:progressPanel}[state.panel])();
}
async function teacher(){
 if(!['answers','practice','completion'].includes(state.teacherTab))state.teacherTab='answers';
 if(state.teacherTab==='completion'){await teacherCompletionView();return;}
 if(state.teacherTab==='practice'){
  const loadId=nextCompletionLoadId(),userId=state.user?.id;
  app.innerHTML=`<div class="eyebrow">Кабинет преподавателя</div><h1>Логбук практики</h1><p class="muted intro">Семинар, OSCE и Tumor Board. OSCE необязателен и не входит в условия итогового зачёта модуля.</p>${teacherNavMarkup()}<div id="teacher-practice-slot"></div>`;
  wireTeacherNav();
  const slot=document.querySelector('#teacher-practice-slot');
  let rows=null,err='';
  try{rows=await api('/api/practice/queue');}catch(e){err=e.message||'Сервис логбука недоступен.';}
  if(!shouldApplyTeacherApp(loadId,userId,'practice'))return;
  state.practiceQueue=rows||[];
  const list=state.practiceQueue.map(r=>{
   const e=r.logbook?.length?r.logbook[r.logbook.length-1]:null;
   const badge=e?`<span class="badge ${esc(e.decision)}">${esc(pDecLabel[e.decision]||e.decision)}</span>`:'<span class="badge">На проверке</span>';
   return `<button class="queue-item" data-prev="${r.id}"><span class="status-row">${badge}${r.stale?'<span class="badge warn">не та редакция</span>':''}<small>${esc(personName(r.student))} · ${esc(r.module)} · ${esc(pKindLabel[r.kind]||'Практика')} · ${stamp(r.created_at)}</small></span><strong>${esc(r.title||r.case)}</strong><span>${esc((r.answer||'').slice(0,150))}${(r.answer||'').length>150?'…':''}</span></button>`;
  }).join('');
  slot.innerHTML=`<section class="paper teacher-practice"><h2>Очередь логбука</h2>${err?`<div class="locked">Логбук практики сейчас недоступен: ${esc(err)}</div>`:list||'<p class="muted">Отправленных ответов по практике пока нет.</p>'}</section>`;
  slot.querySelectorAll('[data-prev]').forEach(b=>b.addEventListener('click',()=>action(b,()=>practiceReview(Number(b.dataset.prev)))));
  return;
 }
 await teacherAnswers();
 const loadId=state.completionLoadId,userId=state.user?.id;
 if(!shouldApplyTeacherApp(loadId,userId,'answers'))return;
 app.insertAdjacentHTML('afterbegin',teacherNavMarkup());
 wireTeacherNav();
 const rows=await api('/api/test-results');
 if(!shouldApplyTeacherApp(loadId,userId,'answers'))return;
 app.insertAdjacentHTML('beforeend',`<section class="paper teacher-tests"><h2>Тестовые попытки ординаторов</h2><p class="muted">Полные попытки: результат рассчитан на сервере по всем вопросам. Итоговый зачёт модуля — на вкладке «Завершение модуля».</p>${rows.length?rows.map(q=>`<details class="reading-group"><summary>${esc(q.student==='student-a'?'Ординатор А':'Ординатор Б')} · ${esc(q.module)} · ${q.submitted_at?(q.passed?'зачтён':'не зачтён'):'в процессе'}${q.submitted_at?' · '+q.score+'/'+q.total:''}</summary>${q.submitted_at?quizResult(q):`<p>${Object.keys(q.answers).length} из ${q.total} ответов сохранено.</p>`}</details>`).join(''):'<p class="muted">Попыток пока нет. Они появятся после запуска теста ординатором.</p>'}</section>`);
}
if(typeof module!=='undefined'&&module.exports){module.exports={formatTimecode,parseTimecode,videoFeedbackPayload,suggestedVideoMarkup,wireSuggestedPlayer,wireVideoFeedback};}
start();
