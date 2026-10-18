'use strict';
// Логбук письменной практики (P:-активности): семинар, OSCE, Tumor Board.
const pKindLabel={seminar:'Семинар',osce:'OSCE',tumor_board:'Tumor Board'};
const pDecLabel={discussed:'Обсуждено на семинаре',accepted:'Принято',returned:'На доработку'};
const pDecBtn={discussed:'Отметить обсуждение',accepted:'Принять работу',returned:'Вернуть на доработку'};
const pDecisions={seminar:['discussed','returned'],osce:['accepted','returned'],tumor_board:['accepted','returned']};
const personName=id=>state.teacherNames?.[id]||({'student-a':'Ординатор А','student-b':'Ординатор Б','teacher':'Преподаватель'}[id]||id);
function localToday(){const d=new Date(),p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`;}
const pLastEv=a=>{const r=(a.attempts||[])[0];return r?.logbook?.length?r.logbook[r.logbook.length-1]:null;};
function invalidatePracticeLoads(){state.practiceLoadId=(state.practiceLoadId||0)+1;state.practice=null;state.practiceLoading=false;}
function shouldApplyPracticeResponse(loadId,userId,moduleId){return loadId===state.practiceLoadId&&state.user?.id===userId&&state.module?.id===moduleId;}
function mergePracticeServerData(d){
 const drafts={...(d.drafts||{})};
 for(const id of state.dirty){
  if(state.edits[id]!==undefined)drafts[id]=state.edits[id];
  else if(state.practice?.drafts?.[id]!==undefined)drafts[id]=state.practice.drafts[id];
 }
 for(const [id,text] of Object.entries(state.edits)){if(text!=='')drafts[id]=text;}
 state.practice={...d,drafts};
}
const pStatusText=a=>{const e=pLastEv(a);return e?pDecLabel[e.decision]||e.decision:(a.attempts||[]).length?'Отправлено · ждёт отметки':a.kind==='osce'?'Ответ по желанию':'Ожидает вашего ответа';};
const pBadge=a=>{const e=pLastEv(a);return e?`<span class="badge ${esc(e.decision)}">${esc(pDecLabel[e.decision]||e.decision)}</span>`:(a.attempts||[]).length?'<span class="badge">На проверке</span>':a.kind==='osce'?'<span class="badge">Необязательная практика</span>':'<span class="badge">Не отправлено</span>';};
function practiceData(){const p=state.practice;return p&&state.module&&p.module===state.module.id?p:null;}
async function loadPractice(){
 const moduleId=state.module?.id,userId=state.user?.id;
 if(!moduleId||!userId)return;
 const loadId=++state.practiceLoadId;state.practiceLoading=true;
 try{
  const d=await api('/api/practice/'+encodeURIComponent(moduleId));
  if(!shouldApplyPracticeResponse(loadId,userId,moduleId))return;
  mergePracticeServerData(d);student();
 }catch(e){
  if(!shouldApplyPracticeResponse(loadId,userId,moduleId))return;
  mergePracticeServerData({module:moduleId,version:'',activities:[],drafts:{},error:e.message||'Сервис временно недоступен.'});student();
 }finally{if(loadId===state.practiceLoadId)state.practiceLoading=false;}
}
function pActButton(a,selId){
 if(a.locked)return `<div class="case-link locked-item" aria-disabled="true"><strong>${esc(a.title)}</strong><small>Закрыто до ответа на предыдущий этап</small></div>`;
 return `<button class="case-link ${selId===a.id?'active':''}" data-act="${esc(a.id)}" ${selId===a.id?'aria-current="step"':''}><strong>${esc(a.title)}</strong><small>${esc(pStatusText(a))}</small></button>`;
}
function pTbCatalog(tb,selId,selKind,boards,tbStageExpected){
 const caseExp=(boards||[]).length;
 if(!tb.length){
  const miss=caseExp||tbStageExpected?'Задания привязаны к модулю, но не выгружены в логбук — это не подтверждённое исключение из программы, содержание уточняется преподавателем.':'Tumor Board к модулю не привязан. Связь требует содержательной проверки преподавателем.';
  return `<details class="reading-group practice-tb-catalog"><summary>Tumor Board · 0 кейсов · 0 этапов</summary><div class="locked">${miss}</div></details>`;
 }
 const groups=new Map(),meta=new Map((boards||[]).map(b=>[b.id,b]));
 for(const a of tb){const g=a.group_id||'';if(!groups.has(g))groups.set(g,[]);groups.get(g).push(a);}
 const caseN=groups.size,stageN=tb.length;
 let count=`${caseN} кейсов · ${stageN} этапов`;
 if(caseExp>caseN||tbStageExpected>stageN)count+=` · в логбуке${caseExp>caseN?` ${caseN} из ${caseExp} кейсов`:''}${tbStageExpected>stageN?` · ${stageN} из ${tbStageExpected} этапов`:''}`;
 const warn=(caseExp>caseN||tbStageExpected>stageN)?'<div class="locked">Часть привязанных заданий не выгружена в логбук — содержание требует проверки преподавателем.</div>':'';
 let cases='';
 for(const [gid,stages] of groups){
  const title=meta.get(gid)?.title||String(stages[0]?.title||gid).replace(/ — этап \d+ из \d+$/,'');
  const open=stages.some(a=>a.id===selId)?' open':'';
  cases+=`<details class="reading-group"${open}><summary>${esc(gid)} · ${esc(title)} · ${stages.length} этапов</summary><div class="case-list activity-list">${stages.map(a=>pActButton(a,selId)).join('')}</div></details>`;
 }
 return `<details class="reading-group practice-tb-catalog"${selKind==='tumor_board'?' open':''}><summary>Tumor Board · ${count}</summary>${warn}${cases}</details>`;
}
function pEventMarkup(e){
 const score=e.max_score>0&&e.score!=null?` · балл ${e.score} из ${e.max_score}`:'';
 const date=e.meeting_date?` · занятие ${esc(e.meeting_date)}`:'';
 const marks=(e.rubric||[]).map(r=>`<li>${esc(r.label)} — ${(e.marks||{})[r.id]??'—'} из ${r.max_score}${r.critical?' · критическая ошибка':''}</li>`).join('');
 return `<div class="review"><strong>${esc(pDecLabel[e.decision]||e.decision)}</strong> · ${esc(personName(e.teacher))} · ${stamp(e.created_at)}${date}${score}<div class="text">${esc(e.comment||'Без комментария')}</div>${marks?`<details><summary>Баллы по критериям</summary><ul class="marks-list">${marks}</ul></details>`:''}</div>`;
}
function pAttemptMarkup(r){
 const e=r.logbook?.length?r.logbook[r.logbook.length-1]:null;
 const badge=e?`<span class="badge ${esc(e.decision)}">${esc(pDecLabel[e.decision]||e.decision)}</span>`:'<span class="badge">На проверке</span>';
 return `<article class="attempt"><div class="status-row">${badge}<span class="muted">Ответ №${r.id} · ${stamp(r.created_at)}</span></div><div class="text">${esc(r.answer)}</div>${(r.logbook||[]).map(pEventMarkup).join('')||'<p class="help">Отметки преподавателя пока нет.</p>'}</article>`;
}
function pDetail(a,inline=false){
 const stage=a.kind==='tumor_board'?`<span class="muted">Этап ${a.stage_index} из ${a.stage_total} · ${esc(a.group_id)}</span>`:'';
 if(a.locked)return `<div class="status-row"><span class="badge">${esc(pKindLabel[a.kind]||'Практика')}</span>${stage}</div><h3>${esc(a.title)}</h3><div class="locked"><strong>Этап пока закрыт.</strong> Он откроется после отправки вашего ответа на предыдущий этап; содержание заранее не показывается.</div>`;
 const attempts=a.attempts||[];
 const prompts=(a.prompts||[]).map(t=>`<p class="questions text">${esc(t)}</p>`).join('');
 const instr=a.instruction?`<div class="vignette text">${esc(a.instruction)}</div>`:'';
 const note={seminar:'Письменная подготовка к устному разбору: отправьте ответ — преподаватель зафиксирует дату и итог обсуждения на семинаре.',osce:'OSCE — дополнительная практика по желанию. Можно изучить задание без письменного ответа. Если решите отправить ответ, после него откроются эталон экзаменатора и разбор.',tumor_board:'Запишите своё решение по данным этого этапа. Следующий этап откроется после отправки.'}[a.kind]||'';
 const draft=state.edits[a.id]!==undefined?state.edits[a.id]:(state.practice.drafts||{})[a.id]||'';
 const standard=a.standard?`<details class="model"><summary>Эталон экзаменатора</summary><div class="text">${esc(a.standard)}</div><p class="help">Сравните со своим ответом — отметку в логбуке ставит преподаватель.</p></details>`:(a.kind==='osce'?'<div class="locked">Эталон экзаменатора и разбор откроются после отправки вашего ответа.</div>':'');
 const debrief=a.debrief?`<details class="model"><summary>Разбор после выполнения</summary><div class="text">${esc(a.debrief)}</div></details>`:'';
 const rubric=(a.rubric||[]).length?`<details class="reading-group"><summary>Критерии оценки преподавателя · ${a.rubric.length}</summary><ul class="marks-list">${a.rubric.map(r=>`<li>${esc(r.label)} — до ${r.max_score} балл.${r.critical?' · критическая ошибка':''}</li>`).join('')}</ul></details>`:'';
 return `<div class="status-row"><span class="badge">${esc(pKindLabel[a.kind]||'Практика')}</span>${stage}${pBadge(a)}</div><h3>${esc(a.title)}</h3><div class="eyebrow">Задание из учебного пакета</div>${prompts}${instr}<p class="help">${note}</p><form data-pform><label for="panswer-${esc(a.id.replace(/[^a-z0-9]/gi,'-'))}">${attempts.length?'Новая версия вашего ответа':'Ваш ответ'}</label><textarea id="panswer-${esc(a.id.replace(/[^a-z0-9]/gi,'-'))}" data-panswer maxlength="20000" required placeholder="Запишите собственное рассуждение до сверки с эталоном…">${esc(draft)}</textarea><div class="actions"><button data-psave type="button">Сохранить черновик</button><button class="primary" type="submit">${attempts.length?'Отправить новую версию':'Отправить преподавателю'}</button></div><p class="help">Черновик видите только вы. Отправленный ответ неизменен; правка создаёт новую версию.</p></form>${standard}${debrief}${rubric}<details class="history" ${attempts.length?'open':''}><summary>История ответов и отметок · ${attempts.length}</summary>${attempts.length?attempts.map(pAttemptMarkup).join(''):'<p class="muted">Отправленных ответов пока нет.</p>'}</details>`;
}
function wirePractice(sel,scope=document){
 if(scope===document)document.querySelectorAll('[data-act]').forEach(b=>b.addEventListener('click',()=>{
  if(b.dataset.act===state.sel[state.panel])return;
  state.sel[state.panel]=b.dataset.act;student();
 }));
 if(scope===document)document.querySelector('#practiceRetry')?.addEventListener('click',e=>action(e.target,loadPractice));
 const form=scope===document?document.querySelector('.activity-detail [data-pform]'):scope.querySelector('[data-pform]');if(!form||!sel||!state.practice||state.practice.error)return;
 const p=state.practice,a=sel;
 form.querySelector('[data-panswer]').addEventListener('input',e=>{state.edits[a.id]=e.target.value;state.dirty.add(a.id);});
 form.querySelector('[data-psave]').addEventListener('click',e=>action(e.target,async()=>{const text=form.querySelector('[data-panswer]').value;await api('/api/practice/drafts',{module:p.module,activity:a.id,version:p.version,text});p.drafts[a.id]=text;state.dirty.delete(a.id);notify('Черновик сохранён. Преподавателю он не отправлен.');}));
 form.addEventListener('submit',e=>{e.preventDefault();action(e.submitter,async()=>{
  const text=form.querySelector('[data-panswer]').value.trim();
  if(!text)throw new Error('Напишите свой ответ перед отправкой.');
  const fingerprint=a.id+p.version+text;let k=state.pending[a.id];
  if(!k||k.fingerprint!==fingerprint)k=state.pending[a.id]={fingerprint,key:crypto.randomUUID()};
  const row=await api('/api/practice/answers',{module:p.module,activity:a.id,version:p.version,answer:text,key:k.key});
  state.dirty.delete(a.id);state.edits[a.id]='';delete state.pending[a.id];
  await loadPractice();notify(`Ответ №${row.id} отправлен и доступен преподавателю.`);
 });});
}
function seminarPanel(){
 const c=state.module.materials,p=practiceData();
 if(!p){moduleShell('<div class="eyebrow">Подготовка к занятию</div><h2>Вопросы к семинару</h2><p class="muted">Загружаем логбук практики…</p>');loadPractice();return;}
 const acts=(p.activities||[]).filter(a=>a.kind==='seminar');
 const sel=acts.find(a=>a.id===state.sel.seminar)||acts[0]||null;
 state.sel.seminar=sel?sel.id:undefined;
 const fallback=c.oral.length?`<p class="muted">Вопросы из исходного пакета (запись ответов в логбук для них ещё не подключена):</p><ol class="oral-list">${c.oral.map(q=>`<li>${esc(q)}</li>`).join('')}</ol>`:'<p class="muted">Вопросы в исходном пакете не указаны.</p>';
 const body=`${p.error?`<div class="locked">Логбук практики сейчас недоступен: ${esc(p.error)} Ответы здесь не сохранены — попробуйте позже.</div>`:''}${acts.length?`<div class="case-list activity-list">${acts.map(a=>pActButton(a,state.sel.seminar)).join('')}</div><div class="activity-detail">${pDetail(sel)}</div>`:fallback}`;
 moduleShell(`<div class="eyebrow">Подготовка к занятию</div><h2>Вопросы к семинару</h2><p>Подготовьте письменный ответ на каждый вопрос: <strong>они будут разбираться с преподавателем</strong> — он зафиксирует обсуждение датой и комментарием. Черновик виден только вам.</p>${body}<h3>Что подготовить к обсуждению</h3><p class="text">${esc(c.seminar_basis)}</p>${c.calendar.length?`<details class="reading-group"><summary>Занятия из календарного плана</summary>${c.calendar.map(e=>`<p><strong>${esc(e.date)}</strong> · ${esc(e.lecturer)}<br>${esc(e.title)}</p>`).join('')}<p class="help">Лектор из календаря не назначается автоматически проверяющим семинара.</p></details>`:''}<div class="actions"><button id="practiceRetry" type="button">Обновить отметки</button></div>`);
 wirePractice(sel);
}
function practicePanel(){
 const c=state.module.materials,p=practiceData();
 if(!p){moduleShell('<div class="eyebrow">Подготовка и оценка на семинаре</div><h2>OSCE и Tumor Board</h2><p class="muted">Загружаем логбук практики…</p>');loadPractice();return;}
 const osce=(p.activities||[]).filter(a=>a.kind==='osce');
 const tb=(p.activities||[]).filter(a=>a.kind==='tumor_board');
 const all=tb;
 const sel=all.find(a=>a.id===state.sel.practice&&!a.locked)||all.find(a=>!a.locked)||all[0]||null;
 state.sel.practice=sel?sel.id:undefined;
 const tbExpected=c.tumor_board.reduce((s,b)=>s+(b.stage_count||0),0);
 const sec=(title,arr,expected,miss)=>{
  if(arr.length)return `<h3>${title} · ${arr.length}${expected>arr.length?` из ${expected}`:''}</h3>${expected>arr.length?'<div class="locked">Часть привязанных заданий не выгружена в логбук — содержание требует проверки преподавателем.</div>':''}<div class="case-list activity-list">${arr.map(x=>pActButton(x,state.sel.practice)).join('')}</div>`;
  return `<h3>${title} · 0</h3>${expected?'<div class="locked">Задания привязаны к модулю, но не выгружены в логбук — это не подтверждённое исключение из программы, содержание уточняется преподавателем.</div>':`<div class="locked">${miss}</div>`}`;
 };
 const vps=`<h3>Виртуальные пациенты · ${c.virtual_patients.length}</h3>${c.virtual_patients.map(v=>`<details class="reading-group"><summary>${esc(v.id+' · '+v.title)}</summary>${listText(v.objectives)}</details>`).join('')||'<p class="muted">В исходнике не назначены.</p>'}<p class="help">Виртуальные пациенты остаются превью: выполненной письменной практикой этот просмотр не считается.</p>`;
 moduleShell(`<div class="eyebrow">Подготовка и оценка на семинаре</div><h2>OSCE и Tumor Board</h2><p><strong>OSCE пока необязателен.</strong> Изучайте станции для подготовки; письменный ответ можно отправить по желанию. OSCE не входит в обязательные условия будущего зачёта модуля.</p><p>Отправленные работы преподаватель может оценить на семинаре и отметить в логбуке.</p>${p.error?`<div class="locked">Логбук практики сейчас недоступен: ${esc(p.error)} Ответы здесь не сохранены — попробуйте позже.</div>`:''}${osce.length?osce.map(a=>`<details class="material-card osce-station" data-osce-answer="${esc(a.id)}"><summary>${esc(a.title)} · свободный ответ</summary>${pDetail(a,true)}</details>`).join(''):sec('OSCE',osce,c.osce.length,'OSCE к модулю не привязан. Нужно уточнение содержания; это не подтверждённое исключение из программы.')}${pTbCatalog(tb,state.sel.practice,sel?.kind,c.tumor_board,tbExpected)}${sel?`<div class="activity-detail">${pDetail(sel)}</div>`:''}${vps}<div class="actions"><button id="practiceRetry" type="button">Обновить отметки</button></div>`);
 wirePractice(sel);
 document.querySelectorAll('[data-osce-answer]').forEach(card=>wirePractice(osce.find(a=>a.id===card.dataset.osceAnswer),card));
}
async function teacherPracticeQueue(){
 let rows=null,err='';
 try{rows=await api('/api/practice/queue');}catch(e){err=e.message||'Сервис логбука недоступен.';}
 state.practiceQueue=rows||[];
 const list=state.practiceQueue.map(r=>{
  const e=r.logbook?.length?r.logbook[r.logbook.length-1]:null;
  const badge=e?`<span class="badge ${esc(e.decision)}">${esc(pDecLabel[e.decision]||e.decision)}</span>`:'<span class="badge">На проверке</span>';
  return `<button class="queue-item" data-prev="${r.id}"><span class="status-row">${badge}${r.stale?'<span class="badge warn">не та редакция</span>':''}<small>${esc(personName(r.student))} · ${esc(r.module)} · ${esc(pKindLabel[r.kind]||'Практика')} · ${stamp(r.created_at)}</small></span><strong>${esc(r.title||r.case)}</strong><span>${esc((r.answer||'').slice(0,150))}${(r.answer||'').length>150?'…':''}</span></button>`;
 }).join('');
 app.insertAdjacentHTML('beforeend',`<section class="paper teacher-practice"><h2>Логбук практики: семинар · OSCE · Tumor Board</h2><p class="muted">Письменная подготовка ординаторов. Зафиксируйте решение, дату занятия и комментарий; баллы берутся из чек-листа задания на сервере.</p>${err?`<div class="locked">Логбук практики сейчас недоступен: ${esc(err)}</div>`:list||'<p class="muted">Отправленных ответов по практике пока нет.</p>'}</section>`);
 document.querySelectorAll('[data-prev]').forEach(b=>b.addEventListener('click',()=>action(b,()=>practiceReview(Number(b.dataset.prev)))));
}
function practiceQueueRows(rows,query,moduleId,status){
 const latestRows=queueLatestRows(rows);
 const q=queueNorm(query);
 return latestRows.filter(r=>{
  const decision=r.logbook?.at(-1)?.decision;
  return (status==='all'||(status==='pending'?!decision:decision===status))&&
   (!moduleId||moduleId==='all'||r.module===moduleId)&&
   (!q||queueNorm(`${r.student_name||''} ${r.student} ${r.module} ${moduleTitle(r.module)}`).includes(q));
 }).sort((a,b)=>a.id-b.id);
}
async function teacherPracticeView(){
 const loadId=nextCompletionLoadId(),userId=state.user?.id;
 const valid=()=>shouldApplyTeacherApp(loadId,userId,'practice');
 const shell=`<div class="eyebrow">Кабинет преподавателя</div><h1>Логбук практики</h1><p class="muted intro">Семинар, OSCE и Tumor Board. OSCE необязателен и не входит в условия итогового зачёта модуля.</p>${teacherNavMarkup()}`;
 app.innerHTML=shell+'<section class="paper" role="status">Загружаем работы…</section>';wireTeacherNav();
 let rows;
 try{rows=await api('/api/practice/queue');}
 catch(e){if(!valid())return;app.innerHTML=shell+`<section class="paper"><p role="alert">Не удалось загрузить логбук: ${esc(e.message)}</p><button id="practiceQueueRetry" type="button">Повторить</button></section>`;wireTeacherNav();document.querySelector('#practiceQueueRetry').addEventListener('click',e=>action(e.target,teacherPracticeView));return;}
 if(!valid())return;
 state.practiceQueue=rows;
 const mods=[...new Set(rows.map(r=>r.module))].sort();
 state.practiceFilter=state.practiceFilter||'pending';state.practiceModule=state.practiceModule||'all';
 if(!mods.includes(state.practiceModule))state.practiceModule='all';
 app.innerHTML=shell+`<section class="paper teacher-practice"><div class="queue-controls"><label class="queue-search">Поиск<input type="search" id="practiceSearch" autocomplete="off" placeholder="Ординатор или модуль"></label><label>Модуль<select id="practiceModule"><option value="all">Все модули</option>${mods.map(id=>`<option value="${esc(id)}">${esc(id+' · '+moduleTitle(id))}</option>`).join('')}</select></label><label>Статус<select id="practiceFilter"><option value="pending">На проверке</option><option value="returned">На доработке</option><option value="accepted">Принято</option><option value="discussed">Обсуждено</option><option value="all">Все</option></select></label><button id="practiceReset" type="button">Сбросить фильтры</button><button id="practiceRefresh" type="button">Обновить</button></div><p id="practiceCount" role="status" aria-live="polite"></p><div id="practiceResults"></div></section>`;
 wireTeacherNav();
 const search=document.querySelector('#practiceSearch'),mod=document.querySelector('#practiceModule'),filter=document.querySelector('#practiceFilter'),result=document.querySelector('#practiceResults');
 search.value=state.practiceSearch||'';mod.value=state.practiceModule;filter.value=state.practiceFilter;
 const update=()=>{
  if(!valid())return;
  const shown=practiceQueueRows(rows,state.practiceSearch,state.practiceModule,state.practiceFilter);
  document.querySelector('#practiceCount').textContent=queueCountText(shown.length,queueLatestRows(rows).length);
  result.innerHTML=shown.map(r=>{const ev=r.logbook?.at(-1);return `<button class="queue-item" data-prev="${r.id}"><span class="status-row"><span class="badge ${esc(ev?.decision||'')}">${esc(ev?pDecLabel[ev.decision]:'На проверке')}</span>${r.stale?'<span class="badge warn">Архивная редакция</span>':''}</span><strong>${esc(r.student_name||personName(r.student))} · ${esc(r.module)}</strong><span>${esc(r.title||r.case)} · ${esc(pKindLabel[r.kind]||'Практика')}</span><small>${stamp(r.created_at)}</small></button>`;}).join('')||`<p class="empty">${rows.length?'По заданным фильтрам ничего не найдено.':'Отправленных работ пока нет.'}</p>`;
 };
 search.addEventListener('input',()=>{state.practiceSearch=search.value;update();});
 mod.addEventListener('change',()=>{state.practiceModule=mod.value;update();});
 filter.addEventListener('change',()=>{state.practiceFilter=filter.value;update();});
 document.querySelector('#practiceReset').addEventListener('click',()=>{state.practiceSearch='';state.practiceModule='all';state.practiceFilter='pending';search.value='';mod.value='all';filter.value='pending';update();});
 document.querySelector('#practiceRefresh').addEventListener('click',e=>action(e.target,teacherPracticeView));
 result.addEventListener('click',e=>{const b=e.target.closest('[data-prev]');if(b&&result.contains(b)&&valid())action(b,()=>practiceReview(Number(b.dataset.prev)));});
 update();
}
async function practiceReview(id){
 const loadId=nextCompletionLoadId(),userId=state.user?.id;
 const d=await api('/api/practice/submissions/'+id);
 if(!shouldApplyTeacherApp(loadId,userId,'practice'))return;
 const row=d.row,a=d.activity||{},hist=d.history||[];
 const stale=row.stale===true||row.version!==d.current_version;
 const decs=pDecisions[a.kind]||['accepted','returned'];
 const stage=a.kind==='tumor_board'&&a.stage_index?` · этап ${a.stage_index} из ${a.stage_total}`:'';
 const lastEv=row.logbook?.length?row.logbook[row.logbook.length-1]:null;
 const rowBadge=lastEv?`<span class="badge ${esc(lastEv.decision)}">${esc(pDecLabel[lastEv.decision]||lastEv.decision)}</span>`:'<span class="badge">На проверке</span>';
 const prompts=(a.prompts||[]).map(t=>`<p class="questions text">${esc(t)}</p>`).join('');
 const instr=a.instruction?`<div class="vignette text">${esc(a.instruction)}</div>`:'';
 const standard=a.standard?`<details class="model"><summary>Эталон экзаменатора</summary><div class="text">${esc(a.standard)}</div></details>`:'';
 const debrief=a.debrief?`<details class="model"><summary>Разбор после выполнения</summary><div class="text">${esc(a.debrief)}</div></details>`:'';
 const total=(a.rubric||[]).reduce((s,r)=>s+(r.max_score||0),0);
 const rubric=(a.rubric||[]).map(r=>`<div class="rubric-row"><div class="rubric-label"><strong>${esc(r.label)}</strong>${r.critical?' <span class="badge warn">критический критерий</span>':''}</div><label class="rubric-input">Балл, 0–${r.max_score}<input class="mark" data-rubric="${esc(r.id)}" data-max="${r.max_score}" type="number" min="0" max="${r.max_score}" step="1" inputmode="numeric" aria-label="Балл: ${esc(r.label)}"></label></div>`).join('');
 const rubricBlock=rubric?`<h3>Чек-лист оценки</h3><p class="help">Критерии и максимумы берутся из задания на сервере. Критический критерий без полного балла не позволяет принять работу.</p>${rubric}<p class="help" id="markTotal">Итого: 0 из ${total}</p>`:'';
 const today=localToday();
 const form=stale?`<div class="locked"><strong>Проверка недоступна.</strong> Задание изменилось после отправки этого ответа: отправлен в редакции ${esc(row.version)}, текущая ${esc(d.current_version)}. Откройте актуальный ответ из очереди.</div>`:
  `<div class="separator"></div><label for="meetingDate">Дата занятия / проверки</label><input id="meetingDate" type="date" required min="2000-01-01" max="${today}" value="${today}">${rubricBlock}<label for="pcomment">Комментарий преподавателя</label><textarea id="pcomment" maxlength="10000" placeholder="Что зафиксировать в журнале…"></textarea><p class="help">При возврате укажите, что именно доработать.</p><div class="actions">${decs.map((x,i)=>`<button ${i===0?'class="primary" ':''}data-pdec="${x}">${pDecBtn[x]}</button>`).join('')}</div>`;
 app.innerHTML=`<button class="back" id="back">← К кабинету</button><div class="eyebrow">${esc(row.module)} · ${esc(row.student_name||personName(row.student))} · ${esc(pKindLabel[a.kind]||'Практика')}${esc(stage)}</div><h1>${esc(a.title||row.case)}</h1><section class="paper"><div class="status-row">${rowBadge}<span class="muted">Ответ №${row.id} · отправлен ${stamp(row.created_at)}</span></div>${prompts}${instr}<h3>Ответ ординатора</h3><div class="text">${esc(row.answer)}</div>${standard}${debrief}${form}<details class="history" open><summary>Все ответы по этой активности · ${hist.length}</summary>${hist.length?hist.map(pAttemptMarkup).join(''):'<p class="muted">Других ответов нет.</p>'}</details></section>`;
 document.querySelector('#back').addEventListener('click',e=>{if(!safeLeave())return;state.dirty.delete('preview');state.teacherTab='practice';action(e.target,teacher);});
 if(stale)return;
 const dateEl=document.querySelector('#meetingDate'),comEl=document.querySelector('#pcomment');
 [dateEl,comEl].forEach(el=>el.addEventListener('input',()=>state.dirty.add('preview')));
 document.querySelectorAll('input.mark').forEach(i=>i.addEventListener('input',()=>{state.dirty.add('preview');let s=0;document.querySelectorAll('input.mark').forEach(x=>{const n=parseInt(x.value,10);if(!isNaN(n))s+=n;});const t=document.querySelector('#markTotal');if(t)t.textContent=`Итого: ${s} из ${total}`;}));
 const pending={};
 document.querySelectorAll('[data-pdec]').forEach(b=>b.addEventListener('click',()=>action(b,async()=>{
  const decision=b.dataset.pdec,comment=comEl.value.trim(),meeting=dateEl.value;
  if(decision==='returned'&&!comment)throw new Error('При возврате укажите, что нужно доработать.');
  if(!meeting)throw new Error('Укажите дату занятия или проверки.');
  if(meeting>today)throw new Error('Дата не может быть в будущем.');
  const marks={};let filled=0,blank=0;
  document.querySelectorAll('input.mark').forEach(i=>{
   const v=i.value.trim();
   if(v===''){blank++;return;}
   const n=Number(v),max=Number(i.dataset.max);
   if(!Number.isInteger(n)||n<0||n>max)throw new Error(`Балл должен быть целым числом от 0 до ${max}.`);
   marks[i.dataset.rubric]=n;filled++;
  });
  if(a.rubric&&a.rubric.length){
   if(blank)throw new Error('Выставьте целый балл по каждому критерию чек-листа.');
   if(decision==='accepted'){const bad=a.rubric.find(r=>r.critical&&(marks[r.id]??0)<r.max_score);if(bad)throw new Error(`Критический критерий «${bad.label}» выполнен не полностью. Принять работу нельзя — выставьте полный балл или верните на доработку.`);}
  }
  const fp=JSON.stringify([id,decision,comment,meeting,marks]);
  if(!pending[fp])pending[fp]=crypto.randomUUID();
  await api('/api/practice/reviews',{submission_id:id,decision,comment,meeting_date:meeting,marks,key:pending[fp]});
  if(!shouldApplyTeacherApp(loadId,userId,'practice'))return;
  state.dirty.delete('preview');
  await practiceReview(id);
  notify(decision==='discussed'?'Обсуждение отмечено в логбуке.':decision==='accepted'?'Работа принята и записана в логбук.':'Ответ возвращён с комментарием.');
 })));
}
if(typeof module!=='undefined'&&module.exports){module.exports={pLastEv,pStatusText,shouldApplyPracticeResponse,mergePracticeServerData,invalidatePracticeLoads};}
