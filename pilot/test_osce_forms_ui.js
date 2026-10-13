'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function control(){return {value:'',addEventListener(k,v){this[k]=v}};}
function card(){const answer=control(),save=control(),form=control();form.querySelector=s=>s==='[data-panswer]'?answer:save;return{answer,save,form,querySelector:()=>form};}
const a=card(),b=card(),calls=[];
const ctx={state:{practice:{module:'M01',version:'v',drafts:{}},edits:{},dirty:new Set(),pending:{},sel:{},panel:'practice'},document:{},api:async(p,body)=>{calls.push([p,body]);return{ id:7 };},action:async(_,fn)=>fn(),notify(){},esc:v=>String(v??''),stamp:()=>'',crypto:require('node:crypto').webcrypto,loadPractice:async()=>{},module:{exports:{}}};vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/web/practice.js','utf8'),ctx);
const one={id:'P:osce:S01',kind:'osce',prompts:['Task A'],attempts:[],title:'A'},two={...one,id:'P:osce:S02',title:'B'};
ctx.one=one;ctx.two=two;ctx.a=a;ctx.b=b;vm.runInContext('wirePractice(one,a);wirePractice(two,b)',ctx);
a.answer.value='Ответ A';b.answer.value='Ответ B';a.answer.input({target:a.answer});b.answer.input({target:b.answer});
(async()=>{await a.save.click({target:a.save});assert.equal(calls[0][1].activity,one.id);assert.equal(calls[0][1].text,'Ответ A');assert.equal(ctx.state.edits[two.id],'Ответ B');assert.ok(ctx.state.dirty.has(two.id));await b.save.click({target:b.save});assert.equal(calls[1][1].activity,two.id);assert.equal(calls[1][1].text,'Ответ B');const html=vm.runInContext('pDetail(one)',ctx);assert.match(html,/data-panswer/);assert.match(html,/panswer-P-osce-S01/);console.log('OSCE independent fields: drafts, dirty state, scoped IDs OK');})().catch(e=>{console.error(e);process.exitCode=1;});
