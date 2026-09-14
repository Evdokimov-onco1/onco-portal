(function(){
const root=document.getElementById('oncoResidencyPortal');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modNorm=s=>String(s||'').replace('М','M').replace('-','');

function activatePanel(id){
  root.querySelectorAll('.orp-navbtn').forEach(b=>b.classList.toggle('is-active',b.dataset.panel===id));
  root.querySelectorAll('.orp-panel').forEach(p=>p.classList.toggle('is-active',p.dataset.panelId===id));
  root.scrollIntoView({behavior:'smooth',block:'start'});
}
root.querySelectorAll('.orp-navbtn').forEach(b=>b.addEventListener('click',()=>activatePanel(b.dataset.panel)));

let year='all';
const moduleGrid=root.querySelector('#orpModuleGrid'), moduleSearch=root.querySelector('#orpModuleSearch');
function moduleCard(m){
 return `<article class="orp-card">
 <div class="orp-cardtop"><span class="orp-tag">${esc(m.module_id)}</span><span class="orp-tag">${esc(m.pedagogical_year)} год</span></div>
 <h3 class="orp-h3">${esc(m.module_title)}</h3><div class="orp-muted">${esc(m.actual_lecture_date)}</div>
 <div class="orp-stats"><span class="orp-tag">задачи ${m.clinical_case_titles.length}</span><span class="orp-tag">тесты ${m.test_questions}</span><span class="orp-tag">VP ${m.virtual_patients.length}</span></div>
 <button class="orp-primary orp-module-open" data-id="${esc(m.module_id)}">Открыть модуль</button>
 </article>`;
}
function renderModules(){
 const q=moduleSearch.value.trim().toLowerCase();
 moduleGrid.innerHTML=D.modules.filter(m=>(year==='all'||m.pedagogical_year===year)&&(`${m.module_id} ${m.module_title}`).toLowerCase().includes(q)).map(moduleCard).join('');
 moduleGrid.querySelectorAll('.orp-module-open').forEach(b=>b.addEventListener('click',()=>openModule(b.dataset.id)));
}
root.querySelectorAll('.orp-pill[data-year]').forEach(b=>b.addEventListener('click',()=>{
 root.querySelectorAll('.orp-pill[data-year]').forEach(x=>x.classList.remove('is-active')); b.classList.add('is-active'); year=b.dataset.year; renderModules();
}));
moduleSearch.addEventListener('input',renderModules);


const moduleRunner=root.querySelector('#orpModuleRunner');
function openModule(id){
 const m=D.modules.find(x=>x.module_id===id); if(!m)return;
 let tools=[];
 if(m.clinical_tools){
   if(Array.isArray(m.clinical_tools)) tools=[...m.clinical_tools];
   else Object.values(m.clinical_tools).forEach(v=>{if(Array.isArray(v))tools.push(...v)});
 }
 const cases=(m.clinical_case_titles||[]).map(x=>`<li>${esc(x)}</li>`).join('');
 const oral=(m.oral_discussion_questions||[]).slice(0,8).map(x=>`<li>${esc(x)}</li>`).join('');
 const links=[];
 if((m.virtual_patients||[]).length)links.push(`VP: ${esc(m.virtual_patients.join(', '))}`);
 if((m.osce_links||[]).length)links.push(`OSCE: ${esc(m.osce_links.join(', '))}`);
 if((m.tumorboard_links||[]).length)links.push(`Tumor Board: ${esc(m.tumorboard_links.join(', '))}`);
 moduleRunner.innerHTML=`<div class="orp-runner">
   <div class="orp-cardtop"><span class="orp-tag">${esc(m.module_id)}</span><span class="orp-tag">${esc(m.pedagogical_year)} год</span><span class="orp-tag">${esc(m.actual_lecture_date)}</span></div>
   <h3 class="orp-h3">${esc(m.module_title)}</h3>
   <div class="orp-stage"><b>Лекция</b><p>${esc(m.lecture||'')}</p></div>
   <div class="orp-stage"><b>Семинар и клинические задачи</b><ol class="orp-list">${cases}</ol></div>
   ${oral?`<div class="orp-stage"><b>Вопросы для устного разбора</b><ol class="orp-list">${oral}</ol></div>`:''}
   <div class="orp-stage"><b>Самоконтроль</b><p>${m.test_questions} тестовых заданий по модулю.</p><button class="orp-primary" id="orpModuleTest">Запустить тест по модулю</button></div>
   <div class="orp-stage"><b>Практическая интеграция</b><p>${links.length?links.join('<br>'):'Связанные интеграционные элементы не назначены.'}</p></div>
   <div class="orp-stage"><b>Клинические инструменты</b><p>${tools.length?esc(tools.slice(0,3).join(', ')):'—'}</p></div>
 </div>`;
 const btn=moduleRunner.querySelector('#orpModuleTest');
 if(btn)btn.addEventListener('click',()=>{
   activatePanel('tests'); tm.value=m.module_id;
   let pool=D.questions.filter(q=>modNorm(q.module)===m.module_id);
   pool=[...pool].sort(()=>Math.random()-.5).slice(0,Math.min(10,pool.length)); runTest(pool);
 });
 moduleRunner.scrollIntoView({behavior:'smooth',block:'start'});
}

const libType=root.querySelector('#orpLibType'),libSearch=root.querySelector('#orpLibSearch'),libGrid=root.querySelector('#orpLibGrid');
function renderLibrary(){
 const q=libSearch.value.trim().toLowerCase(), arr=D.library[libType.value]||[];
 libGrid.innerHTML=arr.filter(r=>JSON.stringify(r).toLowerCase().includes(q)).map(r=>{
   const title=r.title||r.name||r.id, sub=r.year||r.access_normalized||r.access||r.category||'';
   return `<article class="orp-card"><span class="orp-tag">${esc(r.id)}</span><h3 class="orp-h3">${esc(title)}</h3><div class="orp-muted">${esc(sub)}</div>
   ${r.url?`<a class="orp-btn orp-link" target="_blank" rel="noopener" href="${esc(r.url)}">Открыть источник</a>`:''}</article>`;
 }).join('');
}
libType.addEventListener('change',renderLibrary); libSearch.addEventListener('input',renderLibrary);

const tm=root.querySelector('#orpTestModule');
D.modules.forEach(m=>tm.insertAdjacentHTML('beforeend',`<option value="${esc(m.module_id)}">${esc(m.module_id)} — ${esc(m.module_title)}</option>`));
root.querySelector('#orpStartTest').addEventListener('click',()=>{
 let pool=D.questions.filter(q=>!tm.value||modNorm(q.module)===tm.value);
 const n=Math.min(Number(root.querySelector('#orpTestN').value),pool.length);
 pool=[...pool].sort(()=>Math.random()-.5).slice(0,n); runTest(pool);
});
function runTest(qs){
 let i=0,score=0,box=root.querySelector('#orpTestBox');
 function show(){
  if(i>=qs.length){box.innerHTML=`<div class="orp-runner"><h3 class="orp-h3">Результат: ${score} / ${qs.length}</h3></div>`;return}
  const q=qs[i], opts=q.options.map((x,j)=>({text:x,key:'ABCD'[j]})).sort(()=>Math.random()-.5);
  box.innerHTML=`<div class="orp-runner"><div class="orp-muted">${esc(q.id)} · ${i+1}/${qs.length}</div><div class="orp-question">${esc(q.stem)}</div>
  ${opts.map(o=>`<button class="orp-choice" data-key="${o.key}">${esc(o.text)}</button>`).join('')}<div id="orpTestFeedback"></div></div>`;
  box.querySelectorAll('.orp-choice').forEach(b=>b.addEventListener('click',()=>{
   box.querySelectorAll('.orp-choice').forEach(x=>x.disabled=true);
   const ok=b.dataset.key===q.correct;if(ok)score++;b.classList.add(ok?'is-good':'is-bad');
   box.querySelector('#orpTestFeedback').innerHTML=`<div class="orp-feedback"><b>${ok?'Верно':'Неверно'}</b><br>${esc(q.explanation)}</div><button class="orp-primary" id="orpNextTest">Далее</button>`;
   box.querySelector('#orpNextTest').addEventListener('click',()=>{i++;show()});
  }));
 } show();
}

const vpGrid=root.querySelector('#orpVpGrid'), vpRunner=root.querySelector('#orpVpRunner');
vpGrid.innerHTML=D.virtual_patients.map(v=>`<article class="orp-card"><span class="orp-tag">${esc(v.id)}</span><h3 class="orp-h3">${esc(v.title)}</h3><div class="orp-muted">${esc(v.level)}</div><button class="orp-primary orp-vp-open" data-id="${esc(v.id)}">Начать сценарий</button></article>`).join('');
vpGrid.querySelectorAll('.orp-vp-open').forEach(b=>b.addEventListener('click',()=>startVP(b.dataset.id)));
function startVP(id){
 const v=D.virtual_patients.find(x=>x.id===id), by=Object.fromEntries(v.nodes.map(n=>[n.id,n])); let score=0,history=[];
 function show(nodeId){
   const n=by[nodeId];
   if(n.terminal){
     vpRunner.innerHTML=`<div class="orp-runner"><h3 class="orp-h3">${esc(v.id)}. ${esc(v.title)}</h3><div class="orp-feedback">${esc(n.outcome)}</div><p><b>Суммарный балл ветки:</b> ${score}</p><button class="orp-btn" id="orpVpRestart">Начать заново</button></div>`;
     vpRunner.querySelector('#orpVpRestart').addEventListener('click',()=>startVP(id)); vpRunner.scrollIntoView({behavior:'smooth'}); return;
   }
   vpRunner.innerHTML=`<div class="orp-runner"><div class="orp-muted">${esc(v.id)} · ${esc(v.level)}</div><div class="orp-question">${esc(n.prompt)}</div>
   ${n.choices.map((c,j)=>`<button class="orp-choice" data-i="${j}">${esc(c.text)}</button>`).join('')}<div id="orpVpFeedback"></div></div>`;
   vpRunner.querySelectorAll('.orp-choice').forEach(btn=>btn.addEventListener('click',()=>{
     const c=n.choices[Number(btn.dataset.i)]; score+=Number(c.score||0); history.push({node:nodeId,choice:c.text,score:c.score});
     vpRunner.querySelectorAll('.orp-choice').forEach(x=>x.disabled=true);
     btn.classList.add((c.score||0)>0?'is-good':'is-bad');
     vpRunner.querySelector('#orpVpFeedback').innerHTML=`<div class="orp-feedback">${esc(c.feedback||'')}</div><button class="orp-primary" id="orpVpNext">Далее</button>`;
     vpRunner.querySelector('#orpVpNext').addEventListener('click',()=>show(c.to));
   }));
   vpRunner.scrollIntoView({behavior:'smooth'});
 } show('1');
}

const osceGrid=root.querySelector('#orpOsceGrid'), osceRunner=root.querySelector('#orpOsceRunner');
osceGrid.innerHTML=D.osce.stations.map(s=>`<article class="orp-card"><span class="orp-tag">${esc(s.id)}</span><h3 class="orp-h3">${esc(s.title)}</h3><div class="orp-muted">${esc(s.meta['Время']||'')}</div><button class="orp-primary orp-osce-open" data-id="${esc(s.id)}">Открыть станцию</button></article>`).join('');
osceGrid.querySelectorAll('.orp-osce-open').forEach(b=>b.addEventListener('click',()=>openOSCE(b.dataset.id)));
function openOSCE(id){
 const s=D.osce.stations.find(x=>x.id===id);
 const rows=s.checklist.map(r=>`<tr>${Object.values(r).map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('');
 const heads=s.checklist.length?Object.keys(s.checklist[0]).map(h=>`<th>${esc(h)}</th>`).join(''):'';
 osceRunner.innerHTML=`<div class="orp-runner"><div class="orp-cardtop"><span class="orp-tag">${esc(s.id)}</span><span class="orp-tag">${esc(s.meta['Время']||'')}</span></div><h3 class="orp-h3">${esc(s.title)}</h3>
 <div class="orp-stage"><b>Задание ординатору</b><p>${esc(s.task)}</p></div>
 <div class="orp-stage"><b>Материалы станции</b><p>${esc(s.materials)}</p></div>
 <button class="orp-primary" id="orpShowOsceKey">Показать эталон и чек-лист</button>
 <div id="orpOsceKey" class="orp-hidden"><div class="orp-stage"><b>Эталон действий экзаменатора</b><p>${esc(s.examiner_standard)}</p></div>
 <div class="orp-tablewrap"><table class="orp-table"><thead><tr>${heads}</tr></thead><tbody>${rows}</tbody></table></div>
 <div class="orp-stage"><b>Debrief</b><p>${esc(s.debrief)}</p></div></div>
 <div class="orp-source">Источник: ${esc(D.osce.source)}</div></div>`;
 osceRunner.querySelector('#orpShowOsceKey').addEventListener('click',e=>{osceRunner.querySelector('#orpOsceKey').classList.remove('orp-hidden');e.currentTarget.classList.add('orp-hidden')});
 osceRunner.scrollIntoView({behavior:'smooth'});
}

const tbGrid=root.querySelector('#orpTbGrid'), tbRunner=root.querySelector('#orpTbRunner');
tbGrid.innerHTML=D.tumor_board.cases.map(c=>`<article class="orp-card"><span class="orp-tag">${esc(c.id)}</span><h3 class="orp-h3">${esc(c.title)}</h3><div class="orp-muted">${esc(c.meta['Рекомендуемое время']||'')}</div><button class="orp-primary orp-tb-open" data-id="${esc(c.id)}">Начать кейс</button></article>`).join('');
tbGrid.querySelectorAll('.orp-tb-open').forEach(b=>b.addEventListener('click',()=>startTB(b.dataset.id)));
function startTB(id){
 const c=D.tumor_board.cases.find(x=>x.id===id); let visible=1;
 function render(){
  const stages=c.stages.slice(0,visible).map(s=>`<div class="orp-stage"><b>Этап ${s.stage}</b>${s.content.map(x=>`<p>${esc(x)}</p>`).join('')}</div>`).join('');
  const done=visible>=c.stages.length;
  const heads=c.checklist.length?Object.keys(c.checklist[0]).map(h=>`<th>${esc(h)}</th>`).join(''):'';
  const rows=c.checklist.map(r=>`<tr>${Object.values(r).map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('');
  tbRunner.innerHTML=`<div class="orp-runner"><div class="orp-cardtop"><span class="orp-tag">${esc(c.id)}</span><span class="orp-tag">${esc(c.meta['Рекомендуемое время']||'')}</span></div><h3 class="orp-h3">${esc(c.title)}</h3>
  <p>${esc(c.instruction)}</p>${stages}
  ${!done?'<button class="orp-primary" id="orpNextTb">Зафиксировать решение и открыть следующий этап</button>':`<div class="orp-tablewrap"><table class="orp-table"><thead><tr>${heads}</tr></thead><tbody>${rows}</tbody></table></div><div class="orp-stage"><b>Debrief</b><p>${esc(c.debrief)}</p></div>`}
  <div class="orp-source">Источник: ${esc(D.tumor_board.source)}</div></div>`;
  if(!done)tbRunner.querySelector('#orpNextTb').addEventListener('click',()=>{visible++;render()});
  tbRunner.scrollIntoView({behavior:'smooth'});
 } render();
}

renderModules();renderLibrary();
try{
 const qp=new URLSearchParams(window.location.search), mid=qp.get('module');
 if(mid && D.modules.some(m=>m.module_id===mid)){activatePanel('modules');openModule(mid);}
}catch(e){}
})();
