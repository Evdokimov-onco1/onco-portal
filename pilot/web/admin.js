function adminAuditText(a){
 if(a.action==='grant_admin')return 'Права администратора выданы владельцем сервера.';
 try{const d=JSON.parse(a.details);return `${d.role==='teacher'?'Преподаватель':'Ординатор'} · ${d.enabled?'Доступ включён':'Доступ отключён'}${d.role==='teacher'?` · Модули: ${d.modules.join(', ')||'не назначены'}`:''}`;}catch{return 'Настройки доступа изменены.';}
}
// Admin responses contain profile/access metadata only, never password hashes.
async function adminHome(){
 const uid=state.user?.id;
 if(!state.user?.is_admin)throw new Error('Нужны права администратора.');
 const data=await api('/api/admin/overview');
 if(state.user?.id!==uid||!state.user?.is_admin)return;
 header();
 const users=data.users, names=new Map(users.map(u=>[u.id,u.name]));
 app.innerHTML=`<div class="eyebrow">Кафедра онкологии · Управление</div><h1>Кабинет администратора</h1><p class="muted">Пользователи, доступ и назначения преподавателей. Пароли и учебные ответы в этом разделе не показываются.</p><div class="metrics"><div><strong>${users.length}</strong><span>учётных записей</span></div><div><strong>${users.filter(u=>u.enabled).length}</strong><span>активных</span></div><div><strong>${users.filter(u=>u.role==='teacher').length}</strong><span>преподавателей</span></div><div><strong>${data.modules.length}</strong><span>учебных модулей</span></div></div><section class="paper"><div class="queue-toolbar"><h2>Пользователи</h2><button id="adminRefresh">Обновить</button></div><label for="adminSearch">Поиск по имени или почте</label><input id="adminSearch" type="search" placeholder="Имя или email"><div id="adminUsers" class="admin-users"></div></section><section id="adminEditor" class="paper" hidden></section><section class="paper admin-history"><h2>Последние изменения доступа</h2>${data.audit.length?data.audit.map(a=>`<article class="attempt"><strong>${esc(a.action==='grant_admin'?'Выданы права администратора':'Изменён доступ')}</strong> · ${stamp(a.created)}<p class="muted">${esc(names.get(a.actor)||(a.actor==='server-bootstrap'?'Владелец сервера':a.actor))} → ${esc(names.get(a.target)||a.target)}</p><p class="text">${esc(adminAuditText(a))}</p></article>`).join(''):'<p class="muted">Пока нет изменений.</p>'}</section>`;
 document.querySelector('#adminRefresh').addEventListener('click',e=>action(e.target,adminHome));
 const renderUsers=()=>{
  const q=document.querySelector('#adminSearch').value.trim().toLocaleLowerCase('ru');
  const filtered=users.filter(u=>(u.name+' '+(u.email||u.id)).toLocaleLowerCase('ru').includes(q));
  document.querySelector('#adminUsers').innerHTML=filtered.length?filtered.map(u=>`<article class="admin-user"><div><strong>${esc(u.name)}</strong><p class="muted">${esc(u.email||u.id)}</p><span class="badge">${u.is_admin?'Администратор':u.role==='teacher'?'Преподаватель':'Ординатор'}</span> <span class="badge">${!u.enabled?'Доступ отключён':u.email_verified?'Почта подтверждена':'Ожидает подтверждения'}</span></div>${!u.is_admin?`<button data-admin-edit="${esc(u.id)}">Настроить доступ</button>`:'<span class="muted">Права меняет владелец сервера</span>'}</article>`).join(''):'<p class="empty">Пользователи не найдены.</p>';
  document.querySelectorAll('[data-admin-edit]').forEach(b=>b.addEventListener('click',()=>editUser(users.find(u=>u.id===b.dataset.adminEdit))));
 };
 document.querySelector('#adminSearch').addEventListener('input',renderUsers);renderUsers();
 function editUser(u){
  const panel=document.querySelector('#adminEditor');panel.hidden=false;
  panel.innerHTML=`<h2>Доступ: ${esc(u.name)}</h2><p class="muted">${esc(u.email||u.id)}</p><form id="adminUserForm"><label for="adminRole">Роль</label><select id="adminRole"><option value="student" ${u.role==='student'?'selected':''}>Ординатор</option><option value="teacher" ${u.role==='teacher'?'selected':''}>Преподаватель</option></select><label class="admin-check"><input id="adminEnabled" type="checkbox" ${u.enabled?'checked':''}> Доступ включён</label><fieldset id="adminAssignments"><legend>Модули преподавателя</legend><p class="muted">Преподаватель видит работы только по назначенным модулям.</p><div class="admin-module-list">${data.modules.map(m=>`<label class="admin-check"><input type="checkbox" name="adminModule" value="${esc(m.id)}" ${u.modules.includes(m.id)?'checked':''}> ${esc(m.id+' · '+m.title)}</label>`).join('')}</div></fieldset><p class="help">Изменение доступа завершит текущие сессии этого пользователя. Ответы и прогресс сохранятся.</p><div class="actions"><button class="primary" type="submit">Сохранить доступ</button><button id="adminCancel" type="button">Закрыть</button></div></form>`;
  const role=document.querySelector('#adminRole');const toggle=()=>document.querySelector('#adminAssignments').hidden=role.value!=='teacher';toggle();role.addEventListener('change',toggle);
  document.querySelector('#adminCancel').addEventListener('click',()=>{panel.hidden=true;});
  document.querySelector('#adminUserForm').addEventListener('submit',e=>{e.preventDefault();action(e.submitter,async()=>{
   const body={id:u.id,version:u.auth_version,role:role.value,enabled:document.querySelector('#adminEnabled').checked,modules:role.value==='teacher'?Array.from(document.querySelectorAll('[name="adminModule"]:checked'),x=>x.value):[]};
   await api('/api/admin/users',body);if(state.user?.id!==uid)return;await adminHome();notify('Доступ сохранён. Пользователю нужно войти заново.');
  });});
  panel.scrollIntoView({behavior:'smooth',block:'start'});
 }
}
