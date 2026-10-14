'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),data=JSON.parse(fs.readFileSync(path.join(root,'data/orp-data.json')));
const elements={};const element=id=>elements[id]??=( {innerHTML:'',value:'',hidden:false,addEventListener(type,fn){this[type]=fn;}});
const calls=[];const context={URLSearchParams,Set,Object,Date,console,crypto:require('node:crypto').webcrypto,location:{search:'',assign:x=>calls.push(['assign',x])},history:{replaceState(){}},window:{addEventListener(){},history:{replaceState(){}}},document:{querySelector:s=>s==='[data-suggested-player]'?null:element(s),querySelectorAll:s=>s==='[data-case-answer]'?[element('field-0')]:[]},invalidatePracticeLoads(){},invalidateCompletionLoads(){},nextCompletionLoadId(){},api:async(p,b)=>{calls.push([p,b]);return{};},confirm:()=>false};
vm.createContext(context);for(const file of ['app.js','learning.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'web',file),'utf8').replace(/\nstart\(\);\s*$/,''),context);
context.api=async(p,b)=>{calls.push([p,b]);return{};};
vm.runInContext(`state.modules=${JSON.stringify(data.modules.map(m=>({id:m.module_id,title:m.module_title,year:m.pedagogical_year})))};`,context);
assert.equal((vm.runInContext('catalogCards(1)',context).match(/class="module-card /g)||[]).length,34);
assert.equal((vm.runInContext('catalogCards(2)',context).match(/class="module-card /g)||[]).length,27);
assert.match(vm.runInContext('catalogCards(1,"M01")',context),/module=M01/);
assert.doesNotMatch(vm.runInContext('catalogCards(2,"M01")',context),/class="module-card /);
assert.match(vm.runInContext('catalogCards(1,"нет такой темы")',context),/не найдено/);
vm.runInContext(`state.modules.push({id:'unsafe',year:1,title:'<script>bad</script>'});`,context);
assert.doesNotMatch(vm.runInContext('catalogCards(1)',context),/<script>/);
for(const m of data.modules){
 const materials={lecture:m.lecture,faculty_videos:[],groups:Object.entries(m.reading).map(([id,items])=>({id,title:id,items:items.map((r,i)=>({...r,id:id+'-'+i}))})),version:'test'};
 vm.runInContext(`state.module=${JSON.stringify({id:m.module_id,title:m.module_title,year:m.pedagogical_year,materials,opened:{},cases:m.clinical_cases.map((c,i)=>({id:'C'+(i+1),title:c.title,vignette:c.vignette,questions:c.questions})),attempts:[],quizzes:[],question_count:1,drafts:{},version:'test'})};state.caseId='C1';state.panel='materials'; materialsPanel();`,context);
 const html=element('#app').innerHTML;
 assert.match(html,/Рекомендации и нормативные документы/);assert.match(html,/Что читать/);assert.match(html,/module-workspace/);assert.match(html,/Клинические задачи семинара/);
 const detail=html.match(/<details class="reading-group material-card"[^>]*>/g)||[];
 assert.ok(detail.length>=4);assert.ok(detail.every(tag=>!tag.includes(' open')));
 vm.runInContext("state.panel='cases';studentCases();",context);
 assert.match(element('#app').innerHTML,/module-workspace/);assert.match(element('#app').innerHTML,/id="answerForm"/);assert.doesNotMatch(element('#app').innerHTML,/class="model"/);
}
(async()=>{element('field-0').value='Тестовый черновик';await element('#saveDraft').click({target:element('#saveDraft')});await new Promise(r=>setImmediate(r));assert.equal(calls.at(-1)[0],'/api/drafts');assert.equal(JSON.parse(calls.at(-1)[1].text).answers[0],'Тестовый черновик');console.log('Module pages: catalog 34/27, search, escaping, 61 material/case pages, draft save OK');})().catch(e=>{console.error(e);process.exitCode=1;});

assert.equal(vm.runInContext("caseQuestions('Вопросы: 1) Первый? 2) Второй? 3) Третий?').length",context),3);
assert.deepEqual(Array.from(vm.runInContext("caseAnswerFields('Старый черновик',3)",context)),['Старый черновик','','']);
assert.equal(vm.runInContext("answerText(JSON.stringify({schema:'onco-case-answers/v1',questions:['Почему?'],answers:['Потому']}))",context),'Вопрос 1. Почему?\nОтвет: Потому');
vm.runInContext("state.modules=[{id:'M01',title:'Первый',year:1,locked:false},{id:'M02',title:'Второй',year:1,locked:true,previous:'M01'}]",context);
const lockedMarkup=vm.runInContext('catalogCards(1)',context);assert.match(lockedMarkup,/aria-disabled="true"/);assert.doesNotMatch(lockedMarkup,/href="[^"]*module=M02/);

vm.runInContext("state.modules=[{id:'M60',title:'Последний первого года',year:1,locked:false},{id:'M61',title:'Второй год',year:2,locked:true,previous:'M60'}];location.search='?year=2';studentCatalog();",context);
assert.match(element('#app').innerHTML,/🔒 2 год/);
assert.match(element('#yearProgress').innerHTML,/Второй год закрыт/);
assert.match(element('#moduleGrid').innerHTML,/После зачёта M60/);
assert.doesNotMatch(element('#moduleGrid').innerHTML,/href=/);
vm.runInContext("location.search='?year=1';studentCatalog();",context);
assert.match(element('#yearProgress').innerHTML,/Все модули первого года доступны в любом порядке/);
assert.match(element('#moduleGrid').innerHTML,/module=M60/);
