'use strict';
// Kimi supplied the initial filtering/cards candidate; Codex corrected navigation,
// event binding, retry behaviour and integrated the existing queue state contract.
function filterTeacherStudents(rows, query, status) {
 const q=String(query||'').trim().toLocaleLowerCase('ru');
 return rows.filter(s=>(!status||status==='all'||s.status===status)&&
  (!q||`${s.name} ${s.id}`.toLocaleLowerCase('ru').includes(q)));
}
const teacherStudentStatus={blocked:'В работе',ready:'Готов к заявке',submitted:'Заявка на зачёт',returned:'На доработке',completed:'Модуль зачтён'};
function teacherStudentCard(s){
 const date=s.latest_submission_at&&Number.isFinite(Date.parse(s.latest_submission_at))?stamp(s.latest_submission_at):'Отправок пока нет';
 return `<article class="student-progress-card paper"><div class="status-row"><h2>${esc(s.name)}</h2><span class="badge ${s.status==='completed'?'accepted':''}">${esc(teacherStudentStatus[s.status]||s.status)}</span></div><p class="muted student-id">${esc(s.id)}</p><div class="student-progress-metrics"><p>Подготовка <strong>${esc(s.checks_done)} из ${esc(s.checks_total)}</strong></p><p>Проверка преподавателем <strong>${esc(s.teacher_done)} из ${esc(s.teacher_total)}</strong></p></div><p class="muted">${esc(date)}</p><div class="actions"><button type="button" data-open="${esc(s.id)}">Открыть прогресс</button>${s.pending_clinical>0?`<button type="button" data-clinical="${esc(s.id)}">Клинические ответы · ${esc(s.pending_clinical)}</button>`:''}${s.pending_practice>0?`<button type="button" data-practice="${esc(s.id)}">Практика · ${esc(s.pending_practice)}</button>`:''}</div></article>`;
}
async function teacherStudentsView(){
 const loadId=nextCompletionLoadId(),userId=state.user?.id;
 const valid=()=>shouldApplyTeacherApp(loadId,userId,'students');
 const shell=`<div class="eyebrow">Кабинет преподавателя</div><h1>Ординаторы и прогресс</h1><p class="muted intro">Выберите свой модуль: здесь видны и ожидающие проверки работы, и ординаторы, которые ещё не отправили ответ. Итоговый зачёт подтверждается отдельно.</p>${teacherNavMarkup()}`;
 app.innerHTML=shell+'<section class="paper" role="status">Загружаем прогресс…</section>';
 wireTeacherNav();
 let data;
 try{data=await api('/api/teacher/students'+(state.teacherStudentsModule?'?module='+encodeURIComponent(state.teacherStudentsModule):''));}
 catch(e){
  if(!valid())return;
  app.innerHTML=shell+`<section class="paper"><p role="alert">Не удалось загрузить прогресс: ${esc(e.message)}</p><button id="teacher-students-retry" type="button">Повторить</button></section>`;
  wireTeacherNav();
  document.querySelector('#teacher-students-retry').addEventListener('click',e=>action(e.target,teacherStudentsView));
  return;
 }
 if(!valid())return;
 state.teacherStudentsModule=data.module;
 state.teacherNames=Object.fromEntries(data.students.map(s=>[s.id,s.name]));
 if(!data.modules.length){app.innerHTML=shell+'<section class="paper"><h2>Нет назначенных модулей</h2><p>Попросите администратора назначить вам учебные модули.</p></section>';wireTeacherNav();return;}
 const selected=data.module;
 app.innerHTML=shell+`<section class="paper"><div class="queue-controls teacher-students-toolbar"><label>Модуль<select id="teacher-students-module">${data.modules.map(m=>`<option value="${esc(m.id)}">${esc(m.id+' · '+m.title)}</option>`).join('')}</select></label><label class="queue-search">Поиск по имени или логину<input id="teacher-students-search" type="search" autocomplete="off"></label><label>Статус<select id="teacher-students-status"><option value="all">Все</option>${Object.entries(teacherStudentStatus).map(([id,label])=>`<option value="${id}">${label}</option>`).join('')}</select></label><button id="teacher-students-reset" type="button">Сбросить фильтры</button><button id="teacher-students-refresh" type="button">Обновить</button></div><p id="teacher-students-count" role="status" aria-live="polite"></p></section><div class="student-progress-list"></div>`;
 wireTeacherNav();
 const mod=document.querySelector('#teacher-students-module'),search=document.querySelector('#teacher-students-search'),status=document.querySelector('#teacher-students-status'),list=document.querySelector('.student-progress-list');
 mod.value=selected; search.value=state.teacherStudentsSearch||'';status.value=state.teacherStudentsStatus||'all';
 const update=()=>{
  if(!valid())return;
  const rows=filterTeacherStudents(data.students,state.teacherStudentsSearch,state.teacherStudentsStatus);
  document.querySelector('#teacher-students-count').textContent=`Показано ${rows.length} из ${data.students.length}`;
  list.innerHTML=!data.students.length?'<section class="paper">Ординаторы ещё не зарегистрированы.</section>':!rows.length?'<section class="paper">По заданным фильтрам ничего не найдено.</section>':rows.map(teacherStudentCard).join('');
 };
 search.addEventListener('input',()=>{state.teacherStudentsSearch=search.value;update();});
 status.addEventListener('change',()=>{state.teacherStudentsStatus=status.value;update();});
 mod.addEventListener('change',e=>{state.teacherStudentsModule=mod.value;action(e.target,teacherStudentsView);});
 document.querySelector('#teacher-students-refresh').addEventListener('click',e=>action(e.target,teacherStudentsView));
 document.querySelector('#teacher-students-reset').addEventListener('click',()=>{state.teacherStudentsSearch='';state.teacherStudentsStatus='all';search.value='';status.value='all';update();});
 list.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b||!list.contains(b)||!valid())return;
  action(b,async()=>{
   if(b.dataset.open){state.teacherCompletionModule=selected;state.teacherCompletionReview={student:b.dataset.open,module:selected};state.teacherTab='completion';await teacherCompletionView();}
   else if(b.dataset.clinical){const f=queueFilters();f.query=b.dataset.clinical;f.module=selected;f.status='pending';state.teacherTab='answers';await teacher();}
   else if(b.dataset.practice){state.practiceSearch=b.dataset.practice;state.practiceModule=selected;state.practiceFilter='pending';state.teacherTab='practice';await teacher();}
  });
 });
 update();
}
if(typeof module!=='undefined'&&module.exports)module.exports={filterTeacherStudents};
