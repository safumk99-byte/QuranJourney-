(()=>{'use strict';
const $=id=>document.getElementById(id),A=window.QuranJourneyAuth;
const today=()=>{let d=new Date();return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,10)};
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let qs=[],ranges=[],hist=[];
const type=()=> $('examType').value;
function msg(t,k=''){ $('message').innerHTML=t?'<div class="message '+k+'">'+esc(t)+'</div>':''}
const sid=()=> $('student').value;
async function api(p,o={}){return A.api(p,o)}
function setupType(){
 const t=type(),monthly=t==='monthly',single=t==='juz',semester=t==='semester';
 const setVisible=(id,visible)=>{const el=$(id);el.hidden=!visible;el.style.setProperty('display',visible?(id==='semesterRangeField'?'grid':'block'):'none','important')};
 setVisible('monthField',monthly);
 setVisible('singleJuzField',single);
 setVisible('semesterRangeField',semester);
 $('rangesBtn').textContent=monthly?'Load Monthly New Lessons':single?'Check Selected Juz':'Check Semester Juz Range';
 $('month').required=monthly;
}
function initJuz(){
 for(const id of ['singleJuz','startJuz','endJuz'])$(id).innerHTML=Array.from({length:30},(_,i)=>'<option value="'+(i+1)+'">Juz '+(i+1)+'</option>').join('');
 $('singleJuz').value='1';$('startJuz').value='1';$('endJuz').value='5';
}
async function students(){try{let a=await api('/students');$('student').innerHTML='<option value="">Select student</option>'+a.map(s=>'<option value="'+s.id+'">'+esc(s.name)+' · '+esc(s.class_name||'No class')+'</option>').join('')}catch(e){msg(e.message||'Cannot load students','error')}}
function renderQ(){ $('questions').innerHTML=qs.map((q,i)=>'<article class="q"><b>Question '+(i+1)+'</b><div class="ayah" dir="rtl" lang="ar">'+esc(q.text)+'</div><p class="muted">'+esc(q.expected||'')+'</p><div class="grid"><label>Maximum marks<input type="number" min="1" max="1000" data-max="'+i+'" value="'+(q.max_marks||5)+'"></label><label>Marks awarded<input type="number" min="0" max="'+(q.max_marks||5)+'" data-award="'+i+'" value="'+(q.awarded_marks??'')+'" placeholder="Teacher marks"></label></div><label>Teacher note<textarea data-note="'+i+'" rows="2">'+esc(q.note||'')+'</textarea></label></article>').join('')}
function readQ(){qs=qs.map((q,i)=>({...q,max_marks:Number($('[data-max="'+i+'"]').value),awarded_marks:$('[data-award="'+i+'"]').value===''?null:Number($('[data-award="'+i+'"]').value),note:$('[data-note="'+i+'"]').value.trim()}))}
function selectedRange(){return type()==='juz'?{juz_no:Number($('singleJuz').value)}:{start_juz:Number($('startJuz').value),end_juz:Number($('endJuz').value)}}
async function loadRanges(){
 if(!sid())return msg('Select a student first.','error');
 if(type()==='monthly'){
  const v=$('month').value;if(!v)return msg('Select exam month first.','error');
  const [year,month]=v.split('-').map(Number);
  try{ranges=await api('/students/'+sid()+'/exam/monthly-learning?year='+year+'&month='+month);
   $('ranges').innerHTML=ranges.length?ranges.map(r=>'<div class="range"><b>'+esc(r.date)+'</b> · Surah '+r.start_surah+':'+r.start_ayah+' – '+r.end_surah+':'+r.end_ayah+' · '+esc(r.pages)+' pages</div>').join(''):'ഈ മാസത്തിൽ New Lesson രേഖകളൊന്നും കണ്ടെത്തിയില്ല.';
  }catch(e){msg(e.message||'Cannot load monthly New Lessons','error')}
 }else{
  const scope=selectedRange();
  if(type()==='semester'&&scope.end_juz<scope.start_juz)return msg('End Juz must be greater than or equal to Start Juz.','error');
  const label=type()==='juz'?'Juz '+scope.juz_no:'Juz '+scope.start_juz+' – '+scope.end_juz;
  $('ranges').innerHTML='<div class="range">'+(type()==='semester'?'Semester':'Juz Completion')+' Exam: '+label+'<br><span class="muted">Generation സമയത്ത് ഈ പരിധി വിദ്യാർത്ഥിയുടെ Saved Learning Range-ൽ ഉണ്ടെന്ന് പരിശോധിക്കും.</span></div>';
 }
}
async function generate(){
 if(!sid())return msg('Select a student first.','error');
 const n=Number($('count').value);if(!Number.isInteger(n)||n<1||n>100)return msg('Question count must be 1–100.','error');
 if(!$('date').value)return msg('Select exam date.','error');
 $('generate').disabled=true;
 try{
  const payload={date:$('date').value,exam_type:type(),question_count:n};
  if(type()==='monthly'){
   const mv=$('month').value;if(!mv)return msg('Select exam month.','error');
   const [year,month]=mv.split('-').map(Number);
   if($('date').value.slice(0,7)!==mv)return msg('Exam date must be within the selected month.','error');
   payload.year=year;payload.month=month;
  }else Object.assign(payload,selectedRange());
  const r=await api('/students/'+sid()+'/exam/generate',{method:'POST',body:JSON.stringify(payload)});
  qs=r.questions||[];renderQ();msg(qs.length+' questions generated. Set marks and save.','success');
 }catch(e){msg(e.message||'Generation failed','error')}finally{$('generate').disabled=false}
}
async function save(){
 if(!sid()||!qs.length)return msg('Generate questions first.','error');
 try{
  readQ();
  for(let i=0;i<qs.length;i++){let q=qs[i];if(!Number.isInteger(q.max_marks)||q.max_marks<1||q.max_marks>1000)return msg('Question '+(i+1)+': maximum marks must be 1–1000.','error');if(q.awarded_marks!==null&&(!Number.isInteger(q.awarded_marks)||q.awarded_marks<0||q.awarded_marks>q.max_marks))return msg('Question '+(i+1)+': awarded marks exceed the allowed range.','error');if($('confirm').value==='true'&&q.awarded_marks===null)return msg('Enter marks for every question before confirming.','error')}
  const meta={date:$('date').value,exam_type:type(),confirmed:$('confirm').value==='true',questions:qs};
  if(type()!=='monthly')Object.assign(meta,selectedRange());
  let r=await api('/students/'+sid()+'/exam/sessions/'+$('date').value,{method:'PUT',body:JSON.stringify(meta)});
  qs=r.questions||[];renderQ();msg(r.confirmed?'Exam confirmed. Total marks: '+r.total_marks:'Draft exam saved.','success');await historyLoad();
 }catch(e){msg(e.message||'Save failed','error')}
}
async function historyLoad(){
 if(!sid())return msg('Select a student first.','error');
 try{
  hist=await api('/students/'+sid()+'/exam/sessions');
  $('history').innerHTML=hist.length?'<table><thead><tr><th>Type</th><th>Date</th><th>Range</th><th>Questions</th><th>Total</th><th>Status</th><th></th></tr></thead><tbody>'+hist.map((h,i)=>'<tr><td>'+esc(({monthly:'Monthly',juz:'Juz Completion',semester:'Semester'}[h.exam_type]||'Monthly'))+'</td><td>'+esc(h.date)+'</td><td>'+(h.start_juz?'Juz '+h.start_juz+'–'+h.end_juz:'—')+'</td><td>'+h.questions.length+'</td><td>'+h.total_marks+'</td><td>'+(h.confirmed?'Confirmed':'Draft')+'</td><td><button class="mini-btn" data-load="'+i+'">Load</button></td></tr>').join('')+'</tbody></table>':'No exams saved yet.';
 }catch(e){msg(e.message||'History failed','error')}
}
$('history').addEventListener('click',e=>{
 let b=e.target.closest('[data-load]');if(!b)return;let h=hist[Number(b.dataset.load)];
 $('date').value=h.date;$('confirm').value=String(h.confirmed);$('examType').value=h.exam_type||'monthly';setupType();
 if(h.start_juz){if(type()==='juz')$('singleJuz').value=String(h.start_juz);else{$('startJuz').value=String(h.start_juz);$('endJuz').value=String(h.end_juz)}}
 if(type()==='monthly')$('month').value=h.date.slice(0,7);
 qs=h.questions.map(q=>({...q}));renderQ();msg(h.confirmed?'Confirmed exam loaded for review; server will prevent edits.':'Draft loaded.','success');
});
$('questions').addEventListener('input',e=>{if(e.target.matches('[data-max]')){let i=e.target.dataset.max,a=$('[data-award="'+i+'"]');a.max=e.target.value;if(a.value!==''&&Number(a.value)>Number(e.target.value))a.value=e.target.value}});
$('student').addEventListener('change',()=>{qs=[];ranges=[];$('questions').innerHTML='';$('ranges').innerHTML='';$('history').innerHTML='Select View Exam History.'});
$('examType').addEventListener('change',()=>{setupType();qs=[];$('questions').innerHTML='';$('ranges').innerHTML=''});
$('rangesBtn').onclick=loadRanges;$('historyBtn').onclick=historyLoad;$('generate').onclick=generate;$('save').onclick=save;
$('date').value=today();$('month').value=today().slice(0,7);initJuz();setupType();
$('month').addEventListener('change',()=>{const m=$('month').value;if(m)$('date').value=m+'-01';$('ranges').innerHTML='';qs=[];$('questions').innerHTML=''});
A.requireRole(['teacher']);students();
})();