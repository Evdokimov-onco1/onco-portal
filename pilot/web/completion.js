'use strict';
const completionPerson=id=>({'student-a':'Ординатор А','student-b':'Ординатор Б','teacher':'Преподаватель'}[id]||id);
const checkPanel={lecture:'materials',source:'materials',cases:'cases',seminar:'seminar',tumor_board:'practice',quiz:'quiz'};
const teacherCheckTab={cases:'answers',seminar:'practice',tumor_board:'practice'};
const teacherCheckTabLabel={answers:'Клинические ответы',practice:'Логбук практики'};
const completionStatusLabel={blocked:'Условия не выполнены',ready:'Готов к отправке',submitted:'Ожидает преподавателя',returned:'Возвращён на доработку',completed:'Модуль подтверждён'};
function nextCompletionLoadId(){const n=Number(state.completionLoadId);state.completionLoadId=(Number.isFinite(n)?n:0)+1;return state.completionLoadId;}
function invalidateCompletionLoads(){nextCompletionLoadId();state.completion=null;state.completionLecture=null;state.teacherCompletionReview=null;}
function shouldApplyCompletionResponse(loadId,userId,moduleId){return loadId===state.completionLoadId&&state.user?.id===userId&&state.user?.role==='student'&&state.module?.id===moduleId&&state.panel==='progress';}
function shouldApplyTeacherApp(loadId,userId,tab){return loadId===state.completionLoadId&&state.user?.id===userId&&state.user?.role==='teacher'&&state.teacherTab===tab;}
function shouldApplyTeacherCompletion(loadId,userId){return shouldApplyTeacherApp(loadId,userId,'completion');}
function clearCompletionLectureDraft(){state.dirty.delete('completionLecture');delete state.edits.completionLecturePick;}
function completionStatusBadge(st){
 const eff=st?.status||'blocked';
 const cls=eff==='completed'?'accepted':eff==='returned'?'returned':eff==='submitted'?'':eff==='ready'?'discussed':'';
 return `<span class="badge ${esc(cls)}">${esc(completionStatusLabel[eff]||eff)}</span>`;
}
function checkListMarkup(checks,linkPanels){
 return `<ul class="progress-list completion-checks">${(checks||[]).map(c=>{
  const panel=linkPanels?checkPanel[c.id]:null;
  const prog=c.total>1?`${c.done} из ${c.total}`:(c.ok?'выполнено':'не выполнено');
  return `<li class="completion-check ${c.ok?'ok':'pending'}"><strong>${esc(c.label)}</strong><span>${esc(prog)}${c.reason?` · ${esc(c.reason)}`:''}</span>${panel&&!c.ok?`<button type="button" class="completion-goto" data-goto-panel="${esc(panel)}">Открыть раздел «${esc({materials:'Лекция и чтение',cases:'Задачи',seminar:'Семинар',practice:'OSCE / Tumor Board',quiz:'Тест'}[panel]||panel)}»</button>`:''}</li>`;
 }).join('')}</ul>`;
}
function teacherCheckListMarkup(checks){
 return `<ul class="progress-list completion-checks">${(checks||[]).map(c=>{
  const tab=teacherCheckTab[c.id];
  const prog=c.total>1?`${c.done} из ${c.total}`:(c.ok?'выполнено':'не выполнено');
  return `<li class="completion-check ${c.ok?'ok':'pending'}"><strong>${esc(c.label)}</strong><span>${esc(prog)}${c.reason?` · ${esc(c.reason)}`:''}</span>${tab&&!c.ok?`<button type="button" class="completion-goto" data-goto-teacher-tab="${esc(tab)}">Открыть «${esc(teacherCheckTabLabel[tab]||tab)}»</button>`:''}</li>`;
 }).join('')}</ul>`;
}
function completionHistoryMarkup(history,currentVersion){
 if(!history?.length)return '<p class="muted">Заявок на подтверждение ещё не было.</p>';
 return history.map(row=>{
  const stale=row.version!==currentVersion;
  const last=row.events?.length?row.events[row.events.length-1]:null;
  const evs=row.events.map(e=>`<div class="review ${stale?'history-stale':''}"><strong>Историческое решение: ${e.decision==='confirmed'?'подтверждено преподавателем':'возврат на доработку'}</strong> · ${stamp(e.created_at)}${stale?' · заявка к прошлой редакции материалов':''}<div class="text">${esc(e.comment||'Без комментария')}</div><p class="help muted">Это не текущий статус модуля — только запись прошлого решения.</p></div>`).join('');
  return `<article class="attempt ${stale?'history-stale':''}"><div class="status-row"><span class="muted">Заявка №${row.id} · ${stamp(row.created_at)}</span>${stale?'<span class="badge warn">архивная заявка</span>':''}${last?`<span class="badge">${last.decision==='confirmed'?'Было подтверждено':'Был возврат'}</span>`:''}</div>${evs||'<p class="help">Решение преподавателя ещё не заявлено.</p>'}</article>`;
 }).join('');
}
function queueRequestBadge(r){
 const historical=!r.current_request||r.stale;
 if(historical){
  const last=r.events?.length?r.events[r.events.length-1]:null;
  if(last)return `<span class="badge warn">${last.decision==='confirmed'?'Историческое: подтверждено':'Историческое: возврат'}</span>`;
  return '<span class="badge warn">Историческая заявка</span>';
 }
 return completionStatusBadge({status:r.effective_status||'submitted'});
}
function wireCompletionGoto(root){
 root.querySelectorAll('[data-goto-panel]').forEach(b=>b.addEventListener('click',()=>{invalidateCompletionLoads();state.panel=b.dataset.gotoPanel;student();}));
 root.querySelectorAll('[data-goto-teacher-tab]').forEach(b=>b.addEventListener('click',()=>{
  if(state.teacherTab===b.dataset.gotoTeacherTab)return;
  if(!safeLeave())return;
  invalidateCompletionLoads();
  state.teacherTab=b.dataset.gotoTeacherTab;
  state.teacherCompletionReview=null;
  teacher();
 }));
}
function wireLectureOpen(root,materialsVersion){
 root.querySelectorAll('[data-lecture-resource]').forEach(a=>a.addEventListener('click',()=>{
  const resource=a.dataset.lectureResource,moduleId=state.module?.id,userId=state.user?.id,panel=state.panel,loadId=state.completionLoadId;
  api('/api/resources/open',{module:moduleId,version:materialsVersion,resource}).then(()=>{
   if(!shouldApplyCompletionResponse(loadId,userId,moduleId)||state.panel!==panel)return;
   state.module.opened[resource]=new Date().toISOString();notify('Открытие лекции записано.');
   loadCompletion();
  }).catch(()=>notify('Ссылка открыта, но отметка не сохранена. Повторите после восстановления связи.',true));
 }));
}
function renderStudentCompletion(root,data,err){
 const m=state.module;
 if(err){
  root.innerHTML=`<div class="locked">Не удалось загрузить прогресс: ${esc(err)} <button type="button" id="completionRetry">Повторить</button></div>`;
  root.querySelector('#completionRetry')?.addEventListener('click',e=>action(e.target,loadCompletion));
  return;
 }
 const st=data;
 const lecture=st.lecture?`<p class="help">Подтверждённая лекция: <a href="${esc(st.lecture.url)}" target="_blank" rel="noopener noreferrer" data-lecture-resource="${esc(st.lecture.resource)}">${esc(st.lecture.title)}</a> · привязана ${stamp(st.lecture.created_at)}</p>`:'<p class="help">Кафедральная лекция будет доступна после явной привязки преподавателем — общие архивы не засчитываются.</p>';
 const canSubmit=st.student_ready&&(st.status==='ready'||st.status==='returned');
 const submitted=st.status==='submitted';
 const done=st.status==='completed';
 const note=done?'<p class="help">Текущие условия и актуальная заявка подтверждены преподавателем. Прошлые подтверждения при изменении материалов сами по себе зачёт не дают.</p>':submitted?'<p class="help">Заявка у преподавателя. Дождитесь подтверждения или возврата с комментарием.</p>':'';
 root.innerHTML=`<div class="eyebrow">Подготовка к подтверждению</div><h2>Прогресс модуля</h2><div class="status-row">${completionStatusBadge(st)}</div><p class="muted">Чек-лист обновляется с сервера при каждом входе в раздел. Письменные ответы по Tumor Board обязательны на всех этапах; OSCE остаётся необязательным и не блокирует завершение.</p>${lecture}${checkListMarkup(st.checks,true)}${note}${canSubmit?`<div class="actions"><button class="primary" id="completionSubmit">Заявить о готовности модуля</button></div><p class="help">Кнопка доступна, когда выполнены все пункты. Преподаватель проверит работы и подтвердит зачёт на вкладке «Завершение модуля».</p>`:''}${!st.student_ready&&!done?'<div class="locked">Выполните все пункты чек-листа, затем отправьте заявку. Итоговое подтверждение — отдельная вкладка у преподавателя, не путать с приёмом отдельных задач.</div>':''}<h3>История заявок</h3><p class="help muted">Ниже — архив прошлых заявок и решений; текущий статус модуля показан выше.</p>${completionHistoryMarkup(st.history,st.version)}<div class="actions"><button type="button" id="completionRetry">Обновить с сервера</button></div>`;
 wireCompletionGoto(root);
 wireLectureOpen(root,st.lecture?.materials_version||m.materials.version);
 root.querySelector('#completionRetry')?.addEventListener('click',e=>action(e.target,loadCompletion));
 const btn=root.querySelector('#completionSubmit');
 if(btn)btn.addEventListener('click',e=>action(e.target,async()=>{
  const fp=st.version+m.id;let p=state.pending.completionSubmit;
  if(!p||p.fingerprint!==fp)p=state.pending.completionSubmit={fingerprint:fp,key:crypto.randomUUID()};
  await api('/api/completion/submit',{module:m.id,version:st.version,key:p.key});
  delete state.pending.completionSubmit;
  await loadCompletion();
  notify('Заявка отправлена преподавателю.');
 }));
}
async function loadCompletion(){
 const moduleId=state.module?.id,userId=state.user?.id;
 if(!moduleId||!userId||state.user.role!=='student'||state.panel!=='progress')return;
 const root=document.querySelector('#completion-root');
 if(!root)return;
 const loadId=nextCompletionLoadId();
 try{
  const data=await api('/api/completion/'+encodeURIComponent(moduleId));
  if(!shouldApplyCompletionResponse(loadId,userId,moduleId))return;
  state.completion=data;
  renderStudentCompletion(root,data);
 }catch(e){
  if(!shouldApplyCompletionResponse(loadId,userId,moduleId))return;
  renderStudentCompletion(root,null,e.message);
 }
}
function teacherNavMarkup(){
 const tabs=[['answers','Клинические ответы'],['practice','Логбук практики'],['completion','Завершение модуля']];
 return `<nav class="module-nav teacher-nav" aria-label="Разделы кабинета преподавателя">${tabs.map(([id,t])=>`<button type="button" data-teacher-tab="${id}" ${state.teacherTab===id?'class="selected" aria-current="page"':''}>${t}</button>`).join('')}</nav>`;
}
function wireTeacherNav(){
 document.querySelectorAll('[data-teacher-tab]').forEach(b=>b.addEventListener('click',()=>{
  if(state.teacherTab===b.dataset.teacherTab)return;
  if(!safeLeave())return;
  invalidateCompletionLoads();
  clearCompletionLectureDraft();
  state.teacherTab=b.dataset.teacherTab;
  state.teacherCompletionReview=null;
  teacher();
 }));
}
function lectureCandidatePreview(candidates,sel){
 const c=candidates.find(x=>x.id===sel);
 if(!c?.url)return '<p class="help" id="completionCandPreview">Выберите запись и откройте ссылку для проверки перед подтверждением привязки.</p>';
 return `<p class="help" id="completionCandPreview">Проверка перед привязкой: <a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">Открыть выбранную запись ↗</a></p>`;
}
async function teacherCompletionView(){
 const loadId=nextCompletionLoadId(),userId=state.user?.id;
 state.teacherTab='completion';
 const mod=state.teacherCompletionModule||state.modules[0]?.id||'M01';
 app.innerHTML=`<div class="eyebrow">Кабинет преподавателя</div><h1>Завершение модулей</h1><p class="muted intro">Привяжите кафедральную лекцию, проверьте готовность ординатора и подтвердите зачёт. Письменные ответы по Tumor Board обязательны на всех этапах; в логбуке преподаватель оценивает только финальный этап каждого кейса.</p>${teacherNavMarkup()}<div id="teacher-completion-pane"><p class="muted">Загрузка…</p></div>`;
 wireTeacherNav();
 const pane=document.querySelector('#teacher-completion-pane');
 if(state.teacherCompletionReview){await teacherCompletionReview(state.teacherCompletionReview,loadId);return;}
 let queue=[],qErr='';
 try{queue=await api('/api/completion/queue');}catch(e){qErr=e.message||'Очередь недоступна.';}
 if(!shouldApplyTeacherCompletion(loadId,userId))return;
 let lecture=null,lErr='';
 try{lecture=await api('/api/completion/lecture/'+encodeURIComponent(mod));}catch(e){lErr=e.message||'Не удалось загрузить кандидатов лекции.';}
 if(!shouldApplyTeacherCompletion(loadId,userId))return;
 state.completionLecture=lecture;
 const candidates=lecture?.candidates||[];
 const bindSel=state.edits.completionLecturePick??lecture?.current?.resource??'';
 const sameAsCurrent=lecture?.current?.resource&&bindSel===lecture.current.resource;
 const mapBlock=`<section class="paper completion-lecture"><h2>Привязка лекции · ${esc(mod)}</h2><label for="completionMod">Модуль</label><select id="completionMod">${state.modules.map(x=>`<option value="${esc(x.id)}" ${x.id===mod?'selected':''}>${esc(x.id+' · '+x.title)}</option>`).join('')}</select>${lErr?`<div class="locked">${esc(lErr)}</div>`:''}${lecture?.current?`<p class="help">Текущая привязка: <a href="${esc(lecture.current.url)}" target="_blank" rel="noopener noreferrer">${esc(lecture.current.title)}</a> · ${stamp(lecture.current.created_at)}</p>`:'<p class="help">Привязки нет — ординатор не сможет засчитать лекцию, пока вы не выберете запись из списка кафедральных видео с действующей ссылкой.</p>'}${candidates.length?`<label for="completionCand">Кандидат из материалов модуля</label><select id="completionCand"><option value="">— выберите запись —</option>${candidates.map(c=>`<option value="${esc(c.id)}" ${c.id===bindSel?'selected':''}>${esc(c.title)}</option>`).join('')}</select>${lectureCandidatePreview(candidates,bindSel)}<div class="actions"><button class="primary" id="completionBind" type="button" ${!bindSel||sameAsCurrent?'disabled':''}>Подтвердить привязку</button></div>`:'<div class="locked">Нет допустимых кафедральных записей с URL в текущих материалах. Сначала добавьте в модуль кафедральные видео с рабочей ссылкой.</div>'}</section>`;
 const queueItems=queue.length?queue.map(r=>{
  const badge=queueRequestBadge(r);
  return `<button type="button" class="queue-item" data-cr="${esc(r.student)}:${esc(r.module)}"><span class="status-row">${badge}${r.stale?'<span class="badge warn">устарела</span>':''}${!r.current_request?'<span class="badge warn">не текущая заявка</span>':''}<small>${esc(completionPerson(r.student))} · ${esc(r.module)} · заявка №${r.id} · ${stamp(r.created_at)}</small></span><strong>${esc(state.modules.find(m=>m.id===r.module)?.title||r.module)}</strong></button>`;
 }).join(''):'<div class="empty">Активных заявок нет. Они появятся после отправки ординатором из раздела «Прогресс».</div>';
 pane.innerHTML=`${mapBlock}<section class="paper"><h2>Очередь заявок</h2>${qErr?`<div class="locked">${esc(qErr)}</div>`:''}${queueItems}</section>`;
 document.querySelector('#completionMod')?.addEventListener('change',e=>{
  const prev=state.teacherCompletionModule||mod;
  if(!safeLeave()){e.target.value=prev;return;}
  clearCompletionLectureDraft();
  state.teacherCompletionModule=e.target.value;
  teacherCompletionView();
 });
 const candSel=document.querySelector('#completionCand');
 const syncCand=()=>{
  const resource=candSel?.value||'';
  state.edits.completionLecturePick=resource;
  if(resource)state.dirty.add('completionLecture');else{state.dirty.delete('completionLecture');delete state.edits.completionLecturePick;}
  const preview=document.querySelector('#completionCandPreview');
  if(preview)preview.outerHTML=lectureCandidatePreview(candidates,resource);
  const bindBtn=document.querySelector('#completionBind');
  if(bindBtn)bindBtn.disabled=!resource||resource===lecture?.current?.resource;
 };
 candSel?.addEventListener('change',syncCand);
 document.querySelector('#completionBind')?.addEventListener('click',e=>action(e.target,async()=>{
  const resource=candSel?.value;
  if(!resource)throw new Error('Выберите запись из списка кандидатов.');
  if(resource===lecture?.current?.resource)throw new Error('Эта лекция уже привязана — выберите другую запись или оставьте текущую.');
  const fp=mod+lecture.materials_version+resource;let p=state.pending.completionBind;
  if(!p||p.fingerprint!==fp)p=state.pending.completionBind={fingerprint:fp,key:crypto.randomUUID()};
  await api('/api/completion/lecture',{module:mod,materials_version:lecture.materials_version,resource,key:p.key});
  delete state.pending.completionBind;
  clearCompletionLectureDraft();
  notify('Привязка лекции сохранена.');
  teacherCompletionView();
 }));
 pane.querySelectorAll('[data-cr]').forEach(b=>b.addEventListener('click',()=>{
  if(!safeLeave())return;
  clearCompletionLectureDraft();
  const [student,module]=b.dataset.cr.split(':');
  state.teacherCompletionReview={student,module};
  teacherCompletionView();
 }));
}
async function teacherCompletionReview(target,parentLoadId){
 const loadId=parentLoadId||nextCompletionLoadId(),userId=state.user?.id;
 const pane=document.querySelector('#teacher-completion-pane');
 let st,err='';
 try{st=await api('/api/completion/students/'+encodeURIComponent(target.student)+'/'+encodeURIComponent(target.module));}catch(e){err=e.message;}
 if(!shouldApplyTeacherCompletion(loadId,userId))return;
 if(err){pane.innerHTML=`<div class="locked">${esc(err)}</div><button class="back" type="button" id="crBack">← К очереди</button>`;document.querySelector('#crBack')?.addEventListener('click',()=>{if(!safeLeave())return;state.teacherCompletionReview=null;teacherCompletionView();});return;}
 const req=st.request;
 const stale=req&&req.version!==st.version;
 const canConfirm=req&&!stale&&st.student_ready&&st.teacher_ready&&st.status==='submitted';
 const commentKey='completion-review-'+target.student+'-'+target.module;
 const draft=state.edits[commentKey]??'';
 const studentBlock=`<h3>Готовность ординатора</h3>${checkListMarkup(st.checks,false)}<h3>Готовность преподавателя</h3>${teacherCheckListMarkup(st.teacher_checks)}<p class="help">${st.teacher_checks.filter(c=>!c.ok).map(c=>c.reason).filter(Boolean).join(' ')||'Все проверки преподавателя выполнены для текущей редакции.'}</p>`;
 const form=stale||!req?`<div class="locked">${stale?'Заявка относится к устаревшей редакции модуля — подтверждение недоступно.':'Нет актуальной заявки ординатора для этой редакции.'}</div>`:
  `<div class="separator"></div><label for="crComment">Комментарий</label><textarea id="crComment" maxlength="10000" placeholder="Комментарий к решению…">${esc(draft)}</textarea><div class="actions"><button class="primary" type="button" data-cr-dec="confirmed" ${canConfirm?'':'disabled'}>Подтвердить зачёт</button><button type="button" data-cr-dec="returned">Вернуть на доработку</button></div><p class="help">Подтверждение возможно только при выполненных условиях с обеих сторон и актуальной заявке. Возврат требует комментария.</p>`;
 pane.innerHTML=`<button class="back" type="button" id="crBack">← К очереди и привязке</button><section class="paper"><div class="status-row">${completionStatusBadge(st)}<span class="muted">${esc(completionPerson(target.student))} · ${esc(target.module)}</span></div>${studentBlock}${form}<h3>История заявок</h3><p class="help muted">Архив прошлых решений; текущий статус модуля — в строке выше.</p>${completionHistoryMarkup(st.history,st.version)}</section>`;
 wireCompletionGoto(pane);
 document.querySelector('#crBack')?.addEventListener('click',()=>{if(!safeLeave())return;state.teacherCompletionReview=null;state.dirty.delete(commentKey);teacherCompletionView();});
 const ta=document.querySelector('#crComment');
 ta?.addEventListener('input',()=>{state.edits[commentKey]=ta.value;state.dirty.add(commentKey);});
 document.querySelectorAll('[data-cr-dec]').forEach(b=>b.addEventListener('click',()=>action(b,async()=>{
  const decision=b.dataset.crDec,comment=(ta?.value||'').trim();
  if(decision==='returned'&&!comment)throw new Error('Укажите, что нужно доработать.');
  const fp=req.id+':'+decision+':'+comment;let p=state.pending.completionReview;
  if(!p||p.fingerprint!==fp)p=state.pending.completionReview={fingerprint:fp,key:crypto.randomUUID()};
  await api('/api/completion/review',{request_id:req.id,decision,comment,key:p.key});
  if(!shouldApplyTeacherCompletion(loadId,userId))return;
  state.dirty.delete(commentKey);delete state.edits[commentKey];
  notify(decision==='confirmed'?'Зачёт модуля подтверждён.':'Заявка возвращена ординатору.');
  state.teacherCompletionReview={student:target.student,module:target.module};
  teacherCompletionView();
 })));
}
if(typeof module!=='undefined'&&module.exports){module.exports={checkPanel,completionStatusLabel,shouldApplyCompletionResponse,shouldApplyTeacherCompletion,shouldApplyTeacherApp,invalidateCompletionLoads,nextCompletionLoadId};}
