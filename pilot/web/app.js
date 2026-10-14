'use strict';
const app = document.querySelector('#app');
const identity = document.querySelector('#identity');
const notice = document.querySelector('#notice');
const state = {user:null, authConfig:{enabled:false,registration:false,hosted:false}, authView:'login', modules:[], module:null, caseId:'C1', edits:{}, dirty:new Set(), pending:{}, queue:[], filter:'pending', panel:new URLSearchParams(location.search).get('panel')||'materials', quiz:null, practice:null, sel:{}, practiceQueue:null, completionLoadId:0, practiceLoadId:0, teacherTab:null};
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stamp = s => new Date(s).toLocaleString('ru-RU',{dateStyle:'short',timeStyle:'short'});
const latest = a => a.reviews.length ? a.reviews[a.reviews.length-1] : null;
const label = a => !latest(a) ? 'На проверке' : latest(a).decision==='accepted' ? 'Ответ принят' : 'На доработку';
const badge = a => `<span class="badge ${esc(latest(a)?.decision || '')}">${label(a)}</span>`;
function notify(text,error=false){notice.textContent=text;notice.className=error?'error':'';notice.hidden=false;}
async function api(path,body){
 const r=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json','X-Pilot-Request':'1'},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await r.json();if(!r.ok) throw Object.assign(new Error(data.error||'Не удалось выполнить запрос.'),{status:r.status});return data;
}
async function action(button,fn){
 if(state.busy)return;state.busy=true;notice.hidden=true;
 const controls=[...document.querySelectorAll('button,input,select,textarea')].map(el=>[el,el.disabled]);
 controls.forEach(([el])=>el.disabled=true);
 try{await fn();}catch(e){notify(e.message||'Сеть недоступна. Текст оставлен в поле; повторите отправку.',true);}
 finally{controls.forEach(([el,was])=>el.disabled=was);state.busy=false;}
}
function safeLeave(){return !state.dirty.size || confirm('Есть несохранённый текст. Покинуть страницу и потерять его?');}
window.addEventListener('beforeunload',e=>{if(state.dirty.size){e.preventDefault();e.returnValue='';}});
function applyDemoBanner(){
 const b=document.querySelector('#demoBanner');
 if(!b)return;
 b.hidden=!!state.authConfig.enabled||!!state.authConfig.hosted;
}
function parseAuthFragment(){
 const hash=location.hash.replace(/^#/,'');
 if(!hash)return null;
 const eq=hash.indexOf('=');
 if(eq<1)return null;
 const kind=hash.slice(0,eq),token=hash.slice(eq+1);
 if((kind!=='verify'&&kind!=='reset')||!token)return null;
 history.replaceState(null,'',location.pathname+location.search);
 return {kind,token};
}
function header(){
 const tag=state.authConfig.enabled?'': ' · демо';
 identity.innerHTML=state.user?`<span>${esc(state.user.name)}${tag}</span><button id="logout">Выйти</button>`:'';
 document.querySelector('#logout')?.addEventListener('click',e=>{if(!safeLeave())return;action(e.target,async()=>{nextCompletionLoadId();const was=state.user;await api('/api/logout',{});invalidatePracticeLoads();invalidateCompletionLoads();if(state.user!==was)return;state.user=null;state.teacherTab=null;state.teacherCompletionModule=null;state.teacherCompletionReview=null;state.dirty.clear();state.edits={};state.pending={};login();});});
}
function showTokenPasswordForm(kind,token){
 header();
 const isVerify=kind==='verify';
 app.innerHTML=`<section class="paper login auth-form"><div class="eyebrow">Учебный кабинет</div><h1>${isVerify?'Подтверждение регистрации':'Новый пароль'}</h1><p class="muted">${isVerify?'Задайте пароль для входа в кабинет. Ссылка одноразовая.':'Введите новый пароль для входа.'}</p><form id="tokenForm"><label for="newpass">Пароль (не менее 12 символов)</label><input id="newpass" type="password" autocomplete="new-password" minlength="12" maxlength="128" required><label for="newpass2">Повторите пароль</label><input id="newpass2" type="password" autocomplete="new-password" minlength="12" maxlength="128" required><button class="primary" type="submit">${isVerify?'Сохранить и перейти ко входу':'Сохранить пароль'}</button></form><p class="auth-links"><button type="button" class="linkish" id="toLogin">Ко входу</button></p></section>`;
 document.querySelector('#toLogin').addEventListener('click',()=>{state.authView='login';login();});
 document.querySelector('#tokenForm').addEventListener('submit',e=>{e.preventDefault();action(e.submitter,async()=>{const p=document.querySelector('#newpass').value,p2=document.querySelector('#newpass2').value;if(p!==p2)throw new Error('Пароли не совпадают.');const path=isVerify?'/api/auth/verify':'/api/auth/reset';const data=await api(path,{token,password:p});state.user=null;notify(data.message||'Готово.');state.authView='login';login();});});
}
function login(){
 header();applyDemoBanner();
 if(state.authView==='register')return registerForm();
 if(state.authView==='forgot')return forgotForm();
 const hosted=!!state.authConfig.hosted||!!state.authConfig.enabled;
 const userField=hosted?`<label for="username">Электронная почта или логин</label><input id="username" type="text" inputmode="email" autocomplete="username" required>`:`<label for="username">Демонстрационный аккаунт</label><select id="username"><option value="student-a">Ординатор А</option><option value="student-b">Ординатор Б</option><option value="teacher">Преподаватель</option></select>`;
 const extras=hosted?`<p class="auth-links">${state.authConfig.registration?'<button type="button" class="linkish" id="goRegister">Регистрация</button> · ':''}<button type="button" class="linkish" id="goForgot">Забыли пароль?</button></p>`:`<details open><summary>Доступы для проверки</summary><p>Ординатор А: <code>demo-student-a</code><br>Ординатор Б: <code>demo-student-b</code><br>Преподаватель: <code>demo-teacher</code></p><p>Это тестовые аккаунты на этом компьютере.</p></details>`;
 app.innerHTML=`<section class="paper login"><div class="eyebrow">Учебный кабинет · пилот</div><h1>От решения задачи<br>к обратной связи</h1><p class="muted">Сохраните собственное рассуждение, сравните его с эталоном и получите комментарий преподавателя.</p><form id="login">${userField}<label for="password">Пароль</label><input id="password" type="password" autocomplete="current-password" required><button class="primary" type="submit">Войти в кабинет</button></form>${extras}</section>`;
 document.querySelector('#goRegister')?.addEventListener('click',()=>{state.authView='register';registerForm();});
 document.querySelector('#goForgot')?.addEventListener('click',()=>{state.authView='forgot';forgotForm();});
 document.querySelector('#login').addEventListener('submit',e=>{e.preventDefault();action(e.submitter,async()=>{const u=hosted?document.querySelector('#username').value.trim():document.querySelector('#username').value;state.user=await api('/api/login',{username:u,password:document.querySelector('#password').value});state.modules=await api('/api/modules');await home();});});
}
function registerForm(){
 header();applyDemoBanner();
 app.innerHTML=`<section class="paper login auth-form"><div class="eyebrow">Регистрация</div><h1>Участник ординатуры</h1><p class="muted">Укажите рабочую почту. Мы отправим ссылку для подтверждения и установки пароля.</p><form id="registerForm"><label for="regEmail">Электронная почта</label><input id="regEmail" type="email" autocomplete="email" required><label for="regName">Имя и фамилия</label><input id="regName" type="text" autocomplete="name" minlength="2" maxlength="120" required><button class="primary" type="submit">Отправить ссылку</button></form><p class="auth-links"><button type="button" class="linkish" id="toLogin">Уже есть аккаунт — войти</button></p></section>`;
 document.querySelector('#toLogin').addEventListener('click',()=>{state.authView='login';login();});
 document.querySelector('#registerForm').addEventListener('submit',e=>{e.preventDefault();action(e.submitter,async()=>{const email=document.querySelector('#regEmail').value.trim(),name=document.querySelector('#regName').value.trim();const data=await api('/api/auth/register',{email,name});mailSent('register',email,name,data.message);});});
}
function mailSent(kind,email,name,message){
 const isRegister=kind==='register';
 app.innerHTML=`<section class="paper login auth-form"><div class="eyebrow">Проверьте почту</div><h1>Запрос принят</h1><p>${esc(message)}</p><p>Указанный адрес: <strong>${esc(email)}</strong></p><p class="muted">Подождите несколько минут и проверьте папки «Входящие» и «Спам». Ссылка действует один час. Если вы уже завершили регистрацию, используйте вход или восстановление пароля.</p><button class="primary" id="resendMail">Запросить письмо повторно</button><p class="auth-links"><button class="linkish" id="changeMail">Исправить адрес</button><button class="linkish" id="mailToLogin">Перейти ко входу</button></p></section>`;
 document.querySelector('#resendMail').addEventListener('click',e=>action(e.currentTarget,async()=>{const data=await api('/api/auth/'+kind,isRegister?{email,name}:{email});notify(data.message);}));
 document.querySelector('#changeMail').addEventListener('click',()=>{state.authView=kind;login();});
 document.querySelector('#mailToLogin').addEventListener('click',()=>{state.authView='login';login();});
}
function forgotForm(){
 header();applyDemoBanner();
 app.innerHTML=`<section class="paper login auth-form"><div class="eyebrow">Восстановление</div><h1>Забыли пароль?</h1><p class="muted">Если аккаунт с этой почтой есть, мы отправим ссылку для нового пароля.</p><form id="forgotForm"><label for="fgEmail">Электронная почта</label><input id="fgEmail" type="email" autocomplete="email" required><button class="primary" type="submit">Отправить ссылку</button></form><p class="auth-links"><button type="button" class="linkish" id="toLogin">Вернуться ко входу</button></p></section>`;
 document.querySelector('#toLogin').addEventListener('click',()=>{state.authView='login';login();});
 document.querySelector('#forgotForm').addEventListener('submit',e=>{e.preventDefault();action(e.submitter,async()=>{const email=document.querySelector('#fgEmail').value.trim();const data=await api('/api/auth/forgot',{email});mailSent('forgot',email,'',data.message);});});
}
async function home(){header();if(state.user.role==='teacher'){invalidateCompletionLoads();await teacher();}else {const id=new URLSearchParams(location.search).get('module');if(id)await loadModule(id);else studentCatalog();}}
async function loadModule(id){invalidatePracticeLoads();invalidateCompletionLoads();let loaded;try{loaded=await api('/api/modules/'+encodeURIComponent(id));}catch(e){if(e.status===403){app.innerHTML=`<section class="paper"><h1>🔒 Модуль пока закрыт</h1><p>${esc(e.message)}</p><a href="/">Вернуться к модулям</a></section>`;return;}throw e;}state.module=loaded;state.caseId='C1';state.edits={};state.dirty.clear();state.quiz=null;state.quizStartKey=null;state.sel={};student();}
function caseQuestions(text){
 const raw=String(text||'').replace(/^Вопросы?\s*:\s*/i,'').trim();
 const matches=[...raw.matchAll(/(?:^|\s)(\d+)[).]\s+/g)];
 if(matches.length && matches.every((m,i)=>Number(m[1])===i+1))return matches.map((m,i)=>raw.slice(m.index+m[0].length,matches[i+1]?.index??raw.length).trim());
 return [raw||'Сформулируйте решение клинической задачи.'];
}
function caseAnswerFields(raw,count){
 try{const data=JSON.parse(raw);if(data.schema==='onco-case-answers/v1'&&Array.isArray(data.answers)&&data.answers.length===count&&data.answers.every(x=>typeof x==='string'))return data.answers;}catch(e){}
 return Array.from({length:count},(_,i)=>i===0?String(raw||''):'');
}
function answerText(raw){
 try{const data=JSON.parse(raw);if(data.schema==='onco-case-answers/v1'&&Array.isArray(data.answers))return data.answers.map((text,i)=>`Вопрос ${i+1}. ${data.questions?.[i]||''}\nОтвет: ${text}`).join('\n\n');}catch(e){}return raw;
}
function readCaseAnswers(questions,required=false){
 const answers=[...document.querySelectorAll('[data-case-answer]')].map(e=>e.value.trim());
 if(required&&answers.some(a=>!a))throw new Error('Заполните ответ на каждый вопрос задачи.');
 return JSON.stringify({schema:'onco-case-answers/v1',questions,answers});
}
function answerHistory(attempts){return attempts.map(a=>`<article class="attempt"><div class="status-row">${badge(a)}<span class="muted">Ответ №${a.id} · ${stamp(a.created_at)}</span></div><div class="text">${esc(answerText(a.answer))}</div>${a.reviews.map(r=>`<div class="review"><strong>${r.decision==='accepted'?'Ответ принят':'Возвращён на доработку'}</strong> · ${stamp(r.created_at)}<div class="text">${esc(r.comment||'Без комментария')}</div></div>`).join('')}</article>`).join('');}
function studentCases(){
 const m=state.module,c=m.cases.find(x=>x.id===state.caseId);if(!c){app.textContent='В модуле нет клинических задач.';return;}
 const attempts=m.attempts.filter(x=>x.case===c.id&&x.version===m.version);
 const current=attempts[0];
 const questions=caseQuestions(c.questions),fields=caseAnswerFields(state.edits[c.id]??m.drafts[c.id]??'',questions.length);
 const submitted=new Set(m.attempts.filter(x=>x.version===m.version).map(x=>x.case)).size;
 const accepted=m.cases.filter(x=>{const a=m.attempts.find(r=>r.case===x.id&&r.version===m.version);return a&&latest(a)?.decision==='accepted';}).length;
 moduleShell(`<div class="status-row"><span class="eyebrow">Собственное решение</span>${current?badge(current):'<span class="badge">Не отправлено</span>'}</div><h2>${esc(c.title)}</h2><div class="vignette text">${esc(c.vignette)}</div><p class="questions text">${esc(c.questions)}</p>${current&&latest(current)?.decision==='returned'?`<div class="review"><strong>Что доработать</strong><p class="text">${esc(latest(current).comment)}</p></div>`:''}<form id="answerForm">${questions.map((question,i)=>`<div class="question-answer-card"><label for="answer-${i}">Вопрос ${i+1}. ${esc(question)}</label><textarea id="answer-${i}" data-case-answer="${i}" maxlength="20000" required placeholder="Ваш ответ и обоснование…">${esc(fields[i])}</textarea></div>`).join('')}<p class="help">Черновик видите только вы. Отправленный ответ сохраняется в истории; исправление создаёт новую версию.</p><div class="actions"><button id="saveDraft" type="button">Сохранить черновик</button><button class="primary" type="submit">${current?'Отправить новую версию':'Отправить преподавателю'}</button></div></form>${Object.hasOwn(c,'answer')?`<details class="model" open><summary>Эталонный ответ</summary><div class="text">${esc(c.answer)}</div><p class="help">Ваш ответ сохранён. Сравните рассуждения; эталон не означает, что преподаватель уже принял работу.</p></details>`:'<div class="locked">Эталон откроется после сохранения вашего ответа и отправки преподавателю.</div>'}<details class="history" ${attempts.length?'open':''}><summary>История ответов · ${attempts.length}</summary>${attempts.length?answerHistory(attempts):'<p class="muted">Отправленных ответов пока нет.</p>'}</details><p class="clinical-note">Задание и эталон взяты из исходного учебного пакета. В этом пилоте проверяется работа кабинета; клиническое содержание требует преподавательской приёмки.</p>`, `<div class="sidebar-card"><h2 class="sidebar-heading">Клинические задачи</h2><div class="case-list">${m.cases.map((x,i)=>{const a=m.attempts.find(r=>r.case===x.id&&r.version===m.version);return `<button class="case-link ${x.id===c.id?'active':''}" data-case="${esc(x.id)}" ${x.id===c.id?'aria-current="step"':''}><strong>Задача ${i+1}</strong>${esc(x.title.replace(/^Задача\s+\d+\.\s*/,''))}<small>${a?label(a):'Ожидает вашего решения'}</small></button>`;}).join('')}</div></div>`);

 document.querySelectorAll('[data-case]').forEach(b=>b.addEventListener('click',()=>{state.caseId=b.dataset.case;student();}));
 document.querySelectorAll('[data-case-answer]').forEach(el=>el.addEventListener('input',()=>{state.edits[c.id]=readCaseAnswers(questions);state.dirty.add(c.id);}));
 document.querySelector('#saveDraft').addEventListener('click',e=>action(e.target,async()=>{const text=readCaseAnswers(questions);await api('/api/drafts',{module:m.id,case:c.id,version:m.version,text});m.drafts[c.id]=text;state.dirty.delete(c.id);notify('Черновик сохранён. Преподавателю он не отправлен.');}));
 document.querySelector('#answerForm').addEventListener('submit',e=>{e.preventDefault();action(e.submitter,async()=>{const text=readCaseAnswers(questions,true);if(!text)throw new Error('Напишите свой ответ перед отправкой.');const fingerprint=m.id+c.id+m.version+text;let p=state.pending[c.id];if(!p||p.fingerprint!==fingerprint)p=state.pending[c.id]={fingerprint,key:crypto.randomUUID()};const result=await api('/api/answers',{module:m.id,case:c.id,version:m.version,answer:text,key:p.key});state.dirty.delete(c.id);state.edits[c.id]='';delete state.pending[c.id];state.module=await api('/api/modules/'+m.id);student();notify(`Ответ №${result.id} сохранён и доступен преподавателю.`);});});
}
async function teacherAnswers(){
 const loadId=nextCompletionLoadId(),userId=state.user?.id;
 state.queue=await api('/api/queue');
 if(!shouldApplyTeacherApp(loadId,userId,'answers'))return;
 const latestCases=[];const seen=new Set();for(const a of state.queue){const k=[a.student,a.module,a.case,a.version].join(':');if(!seen.has(k)){seen.add(k);latestCases.push(a);}}
 const pending=latestCases.filter(a=>!latest(a)).length;
 const filtered=state.filter==='all'?latestCases:latestCases.filter(a=>state.filter==='pending'?!latest(a):latest(a)?.decision===state.filter);
 app.innerHTML=`<div class="eyebrow">Кабинет преподавателя</div><h1>Ответы ординаторов</h1><p class="muted intro">Проверьте рассуждение, оставьте комментарий и примите ответ либо верните его на доработку. Это оценка отдельной задачи; итоговый зачёт модуля здесь ещё не выставляется.</p><div class="metrics"><div><strong>${pending}</strong><span>ожидают проверки</span></div><div><strong>${state.queue.length}</strong><span>отправленных версий</span></div></div><section class="paper"><div class="queue-toolbar"><h2>Очередь проверки</h2><label>Показать <select id="queueFilter"><option value="pending">На проверке</option><option value="returned">На доработке</option><option value="accepted">Принятые</option><option value="all">Все ответы</option></select></label><button id="refresh">Обновить</button></div>${filtered.length?filtered.map(a=>`<button class="queue-item" data-review="${a.id}"><span class="status-row">${badge(a)}<small>${esc(a.student_name||a.student)} · ${esc(a.module)} · ${esc(a.case)} · ${stamp(a.created_at)}</small></span><strong>${esc(state.modules.find(m=>m.id===a.module)?.title||a.module)}</strong><span>${esc(answerText(a.answer).slice(0,150))}${a.answer.length>150?'…':''}</span></button>`).join(''):'<div class="empty">В этой категории пока нет ответов.<br>Новые работы появятся после отправки ординатором.</div>'}</section>`;
 document.querySelector('#queueFilter').value=state.filter;
 document.querySelector('#queueFilter').addEventListener('change',e=>{state.filter=e.target.value;action(e.target,teacher);});
 document.querySelector('#refresh').addEventListener('click',e=>action(e.target,teacher));
 document.querySelectorAll('[data-review]').forEach(b=>b.addEventListener('click',()=>action(b,()=>review(Number(b.dataset.review)))));
}
async function review(id){
 const loadId=state.completionLoadId,userId=state.user?.id,tab=state.teacherTab;
 const row=await api('/api/submissions/'+id),m=await api('/api/modules/'+row.module),c=m.cases.find(x=>x.id===row.case);
 if(!shouldApplyTeacherApp(loadId,userId,'answers'))return;
 const historyRows=state.queue.filter(a=>a.student===row.student&&a.module===row.module&&a.case===row.case);
 app.innerHTML=`<button class="back" id="back">← К очереди</button><div class="eyebrow">${esc(row.module)} · ${esc(row.student_name||row.student)}</div><h1>Проверка ответа №${row.id}</h1><section class="paper"><div class="status-row">${badge(row)}<span class="muted">Отправлен ${stamp(row.created_at)}</span></div><h2>${esc(c?.title||row.case)}</h2>${row.version!==m.version?'<div class="locked">Исходный материал изменился после отправки. Ниже текущая редакция; не принимайте работу без сверки прежнего задания.</div>':''}<div class="vignette text">${esc(c?.vignette||'')}</div><p class="questions text">${esc(c?.questions||'')}</p><h3>Ответ ординатора</h3><div class="text">${esc(answerText(row.answer))}</div><details class="model"><summary>Свериться с эталоном</summary><div class="text">${esc(c?.answer||'')}</div></details><div class="separator"></div><label for="comment">Комментарий преподавателя</label><textarea id="comment" maxlength="10000" placeholder="Что получилось и что стоит уточнить…"></textarea><p class="help">При возврате укажите, что именно необходимо доработать.</p><div class="actions"><button class="primary" data-decision="accepted">Принять ответ</button><button data-decision="returned">Вернуть на доработку</button></div><details class="history" open><summary>История этой задачи · ${historyRows.length}</summary>${answerHistory(historyRows)}</details></section>`;
 document.querySelector('#comment').addEventListener('input',()=>state.dirty.add('review'));
 document.querySelector('#back').addEventListener('click',e=>{if(!safeLeave())return;state.dirty.clear();state.teacherTab='answers';action(e.target,teacher);});
 const pending={};
 document.querySelectorAll('[data-decision]').forEach(b=>b.addEventListener('click',()=>action(b,async()=>{const comment=document.querySelector('#comment').value.trim(),decision=b.dataset.decision;if(decision==='returned'&&!comment)throw new Error('Укажите, что нужно доработать.');const fp=decision+comment;if(!pending[fp])pending[fp]=crypto.randomUUID();await api('/api/reviews',{submission_id:id,decision,comment,key:pending[fp]});state.dirty.clear();await teacher();notify(decision==='accepted'?'Ответ принят. Ординатор увидит отметку в своём кабинете.':'Ответ возвращён с комментарием. История сохранена.');})));
}
function applyAuthDeepLink(){
 const p=new URLSearchParams(location.search).get('auth');
 if(p==='register'||p==='forgot'||p==='login')state.authView=p;
}
async function start(){
 applyAuthDeepLink();
 try{state.authConfig=await api('/api/auth/config');}catch(e){state.authConfig={enabled:false,registration:false,hosted:true};}
 applyDemoBanner();
 const frag=parseAuthFragment();
 if(frag){showTokenPasswordForm(frag.kind,frag.token);return;}
 if(state.authView!=='login'){login();return;}
 try{state.user=await api('/api/session');state.modules=await api('/api/modules');await home();}catch(e){login();}
}
