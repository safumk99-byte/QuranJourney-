(()=>{'use strict';
const $=id=>document.getElementById(id),A=window.QuranJourneyAuth;
const today=()=>{let d=new Date();return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,10)};
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let qs=[],ranges=[],hist=[],editingExamId=null;
const type=()=> $('examType').value;
function msg(t,k=''){ $('message').innerHTML=t?'<div class="message '+k+'">'+esc(t)+'</div>':''}
const sid=()=> $('student').value;
async function api(p,o={}){return A.api(p,o)}
function setupType(){
 const t=type(),monthly=t==='monthly',single=t==='juz',semester=t==='semester';
 const setVisible=(id,visible)=>{const el=$(id);el.hidden=!visible;el.style.setProperty('display',visible?(id==='semesterRangeField'?'contents':'block'):'none','important')};
 setVisible('monthField',monthly);
 setVisible('singleJuzField',single);
 setVisible('semesterRangeField',semester);
 $('rangesBtn').textContent=monthly?'Load Monthly New Lessons':single?'Check Selected Juz':'Check Semester Juz Range';
 $('month').required=monthly;
 $('monthlySourceField').hidden=!monthly;$('monthlySourceField').style.display=monthly?'block':'none';updateMonthlySource();
}
function updateMonthlySource(){const show=type()==='monthly'&&['page_range','both'].includes($('monthlySource').value);$('pageRangeFields').hidden=!show;$('pageRangeFields').style.display=show?'grid':'none';$('startPage').required=show;$('endPage').required=show;}
function monthlyPageRange(){const start=Number($('startPage').value),end=Number($('endPage').value);if(!Number.isInteger(start)||!Number.isInteger(end)||start<1||end>604||end<start)throw new Error('Enter a valid Quran page range from 1 to 604.');return {start_page:start,end_page:end};}
function initJuz(){
 for(const id of ['singleJuz','startJuz','endJuz'])$(id).innerHTML=Array.from({length:30},(_,i)=>'<option value="'+(i+1)+'">Juz '+(i+1)+'</option>').join('');
 $('singleJuz').value='1';$('startJuz').value='1';$('endJuz').value='5';
}
async function students(){try{let a=await api('/students');$('student').innerHTML='<option value="">Select student</option>'+a.map(s=>'<option value="'+s.id+'">'+esc(s.name)+' · '+esc(s.class_name||'No class')+'</option>').join('')}catch(e){msg(e.message||'Cannot load students','error')}}
function quranAyahRef(expected){
 const match=String(expected||'').trim().match(/^Surah\\s+(\\d+)\\s*:\\s*.*?\\s+(\\d+)\\s*(?:[·(]|$)/i);
 if(!match)return null;
 const counts=[7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,110,98,135,112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,182,88,75,85,54,53,89,59,37,35,38,29,18,45,60,49,62,55,78,96,29,22,24,13,14,11,11,18,12,12,30,52,52,44,28,28,20,56,40,31,50,40,46,42,29,19,36,25,22,17,19,26,30,20,15,21,11,8,8,19,5,8,8,11,11,8,3,9,5,4,7,3,6,3,5,4,5,6];
 const surah=Number(match[1]),ayah=Number(match[2]);
 if(!Number.isInteger(surah)||surah<1||surah>114||!Number.isInteger(ayah)||ayah<1||ayah>counts[surah-1])return null;
 return {surah,ayah};
}
function renderQ(){
 $('questions').innerHTML=qs.map((q,i)=>{
  const ref=quranAyahRef(q.expected);
  const ayahLink=ref?'<a class="quran-ayah-open" href="./quran.html?surah='+ref.surah+'&ayah='+ref.ayah+'" aria-label="Surah '+ref.surah+', Ayah '+ref.ayah+' Quran Journey-യിൽ തുറക്കുക"><div class="ayah" dir="rtl" lang="ar">'+esc(q.text)+'</div><span class="quran-ayah-hint">📖 ഈ ആയത്ത് Quran Journey-യിൽ തുറക്കുക · '+ref.surah+':'+ref.ayah+'</span></a>':'<div class="ayah" dir="rtl" lang="ar">'+esc(q.text)+'</div>';
  return '<article class="q"><b>Question '+(i+1)+'</b>'+ayahLink+'<p class="muted">'+esc(q.expected||'')+'</p><div class="grid"><label>Maximum marks<input type="number" min="1" max="1000" data-max="'+i+'" value="'+(q.max_marks||5)+'"></label><label>Marks awarded<input type="number" min="0" max="'+(q.max_marks||5)+'" data-award="'+i+'" value="'+(q.awarded_marks??'')+'" placeholder="Teacher marks"></label></div><label>Teacher note<textarea data-note="'+i+'" rows="2">'+esc(q.note||'')+'</textarea></label></article>';
 }).join('');
}
function readQ(){qs=qs.map((q,i)=>{const max=document.querySelector('[data-max="'+i+'"]'),award=document.querySelector('[data-award="'+i+'"]'),note=document.querySelector('[data-note="'+i+'"]');if(!max||!award||!note)throw new Error('Question '+(i+1)+' fields are missing. Regenerate the questions and try again.');return {...q,max_marks:Number(max.value),awarded_marks:award.value===''?null:Number(award.value),note:note.value.trim()}})}
function selectedRange(){return type()==='juz'?{juz_no:Number($('singleJuz').value)}:{start_juz:Number($('startJuz').value),end_juz:Number($('endJuz').value)}}
async function loadRanges(){
 if(!sid())return msg('Select a student first.','error');
 if(type()==='monthly'){
  const v=$('month').value;if(!v)return msg('Select exam month first.','error');
  const source=$('monthlySource').value;
  if(source==='page_range'||source==='both'){try{const p=monthlyPageRange();const preview=await api('/students/'+sid()+'/exam/monthly-pages?start_page='+p.start_page+'&end_page='+p.end_page);$('ranges').innerHTML='<div class="range"><b>Quran Page Range:</b> Pages '+p.start_page+'–'+p.end_page+' · '+preview.ayah_count+' ayahs'+(source==='both'?' + New Lesson Progress':'')+'</div>';}catch(e){msg(e.message||'Invalid page range','error');return}if(source==='page_range')return;}
  const [year,month]=v.split('-').map(Number);
  try{ranges=await api('/students/'+sid()+'/exam/monthly-learning?year='+year+'&month='+month);
   const lessonHtml=ranges.length?ranges.map(r=>'<div class="range"><b>'+esc(r.date)+'</b> · Surah '+r.start_surah+':'+r.start_ayah+' – '+r.end_surah+':'+r.end_ayah+' · '+esc(r.pages)+' pages</div>').join(''):'<div class="range">ഈ മാസത്തിൽ New Lesson രേഖകളൊന്നും കണ്ടെത്തിയില്ല.</div>';
   const pageHtml=(source==='both')?$('ranges').innerHTML:'';
   $('ranges').innerHTML=pageHtml+lessonHtml;
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
   payload.year=year;payload.month=month;payload.monthly_source=$('monthlySource').value;
   if(payload.monthly_source==='page_range'||payload.monthly_source==='both')Object.assign(payload,monthlyPageRange());
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
  const meta={date:$('date').value,exam_type:type(),confirmed:$('confirm').value==='true',allow_confirmed_edit:editingExamId!==null,session_id:editingExamId,questions:qs};
  if(type()==='monthly'){meta.monthly_source=$('monthlySource').value;if(meta.monthly_source==='page_range'||meta.monthly_source==='both')Object.assign(meta,monthlyPageRange());}else Object.assign(meta,selectedRange());
  let r=await api('/students/'+sid()+'/exam/sessions/'+$('date').value,{method:'PUT',body:JSON.stringify(meta)});
  qs=r.questions||[];renderQ();editingExamId=null;$('date').disabled=false;$('examType').disabled=false;msg(r.confirmed?'Exam confirmed. Total marks: '+r.total_marks:'Draft exam saved.','success');await historyLoad();
 }catch(e){msg(e.message||'Save failed','error')}
}
async function historyLoad(){
 if(!sid())return msg('Select a student first.','error');
 try{
  hist=await api('/students/'+sid()+'/exam/sessions');
  $('history').innerHTML=hist.length?'<table><thead><tr><th>Type</th><th>Date</th><th>Range</th><th>Questions</th><th>Total</th><th>Status</th><th></th></tr></thead><tbody>'+hist.map((h,i)=>'<tr><td>'+esc(({monthly:'Monthly',juz:'Juz Completion',semester:'Semester'}[h.exam_type]||'Monthly'))+'</td><td>'+esc(h.date)+'</td><td>'+(h.start_juz?'Juz '+h.start_juz+'–'+h.end_juz:(h.exam_type==='monthly'?(h.monthly_source==='page_range'?'Pages '+h.start_page+'–'+h.end_page:(h.monthly_source==='both'?'New Lesson + Pages '+h.start_page+'–'+h.end_page:'New Lesson')):'—'))+'</td><td>'+h.questions.length+'</td><td>'+h.total_marks+'</td><td>'+(h.confirmed?'Confirmed':'Draft')+'</td><td><button class="mini-btn" data-edit="'+i+'">Edit</button> <button class="mini-btn" data-load="'+i+'">Load</button> <button class="mini-btn" data-delete="'+i+'">Delete</button></td></tr>').join('')+'</tbody></table>':'No exams saved yet.';
 }catch(e){msg(e.message||'History failed','error')}
}
$('history').addEventListener('click',async e=>{
 let del=e.target.closest('[data-delete]');
 if(del){const h=hist[Number(del.dataset.delete)];if(!h||!confirm('Delete this exam history record and all its questions? This cannot be undone.'))return;del.disabled=true;try{await api('/students/'+sid()+'/exam/sessions/'+h.id,{method:'DELETE'});msg('Exam history deleted.','success');await historyLoad()}catch(err){msg(err.message||'Delete failed','error');del.disabled=false}return;}
 let edit=e.target.closest('[data-edit]');let load=e.target.closest('[data-load]');if(!edit&&!load)return;
 let h=hist[Number((edit||load).dataset[edit?'edit':'load'])];
 if(edit){editingExamId=h.id;$('date').disabled=true;$('examType').disabled=true;}else{editingExamId=null;$('date').disabled=false;$('examType').disabled=false;}
 $('date').value=h.date;$('confirm').value=String(h.confirmed);$('examType').value=h.exam_type||'monthly';setupType();
 if(h.start_juz){if(type()==='juz')$('singleJuz').value=String(h.start_juz);else{$('startJuz').value=String(h.start_juz);$('endJuz').value=String(h.end_juz)}}
 if(type()==='monthly'){$('month').value=h.date.slice(0,7);$('monthlySource').value=h.monthly_source||'new_lesson';$('startPage').value=h.start_page||'';$('endPage').value=h.end_page||'';updateMonthlySource();}
 qs=h.questions.map(q=>({...q}));renderQ();msg(edit?'Exam loaded for editing. Save Exam & Marks to update this history record.':(h.confirmed?'Confirmed exam loaded for review.':'Draft loaded.'),'success');
});
$('questions').addEventListener('input',e=>{if(e.target.matches('[data-max]')){let i=e.target.dataset.max,a=document.querySelector('[data-award="'+i+'"]');if(!a)return;a.max=e.target.value;if(a.value!==''&&Number(a.value)>Number(e.target.value))a.value=e.target.value}});
$('student').addEventListener('change',()=>{editingExamId=null;$('date').disabled=false;$('examType').disabled=false;qs=[];ranges=[];$('questions').innerHTML='';$('ranges').innerHTML='';hist=[];$('history').innerHTML=sid()?'Loading exam history…':'Select a student to view exam history.';if(sid())historyLoad();});
$('examType').addEventListener('change',()=>{setupType();qs=[];$('questions').innerHTML='';$('ranges').innerHTML=''});
$('monthlySource').addEventListener('change',()=>{updateMonthlySource();$('ranges').innerHTML='';qs=[];$('questions').innerHTML=''});
$('rangesBtn').onclick=loadRanges;$('historyBtn').onclick=historyLoad;$('generate').onclick=generate;$('save').onclick=save;
$('date').value=today();$('month').value=today().slice(0,7);initJuz();setupType();
$('month').addEventListener('change',()=>{const m=$('month').value;if(m)$('date').value=m+'-01';$('ranges').innerHTML='';qs=[];$('questions').innerHTML=''});
A.requireRole(['teacher']);students();
})();