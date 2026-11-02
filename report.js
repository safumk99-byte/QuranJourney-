(()=>{'use strict';
const A=window.QuranJourneyAuth;if(!A||!A.requireRole(['teacher']))return;
const $=id=>document.getElementById(id);
const monthNow=()=>{const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const validMonth=/^\\d{4}-(0[1-9]|1[0-2])$/;
function openSource(path,params,hash){const q=new URLSearchParams(params);const url='./'+path+'?'+q.toString()+(hash?'#'+hash:'');const tab=window.open(url,'_blank');if(!tab)window.location.href=url}
function getMonth(id,label){const v=$(id).value;if(!validMonth.test(v)){window.QuranJourneyToast?.show('Select a valid '+label+'.','error');$(id).focus();return null}return v}
async function loadLists(){const status=$('reportStatus');try{const rows=await A.api('/students');const students=Array.isArray(rows)?rows:[];const classes=[...new Set(students.map(s=>s.class_name||'Unassigned class'))].sort((a,b)=>a.localeCompare(b));$('reportStudent').innerHTML='<option value="">Select Student</option>'+students.slice().sort((a,b)=>String(a.name||'').localeCompare(String(b.name||''))).map(s=>'<option value="'+encodeURIComponent(s.id)+'">'+esc(s.name)+' · '+esc(s.class_name||'Unassigned class')+'</option>').join('');$('attendanceClass').innerHTML='<option value="">All Classes</option>'+classes.map(c=>'<option value="'+encodeURIComponent(c)+'">'+esc(c)+'</option>').join('');status.textContent='Ready · '+students.length+' students · '+classes.length+' classes. Choose a report to continue.'}catch(err){status.textContent='Could not load student and class lists: '+err.message;window.QuranJourneyToast?.show(err.message,'error')}}
const m=monthNow();['progressMonth','rankingMonth','attendanceMonth'].forEach(id=>$(id).value=m);
$('openProgress').addEventListener('click',()=>{const v=getMonth('progressMonth','report month');if(v)openSource('students.html',{report:'monthly-progress',month:v},'monthly-progress-report')});
$('openRanking').addEventListener('click',()=>{const v=getMonth('rankingMonth','ranking month');if(v)openSource('students.html',{report:'monthly-ranking',month:v},'monthly-ranking-report')});
$('openAttendance').addEventListener('click',()=>{const v=getMonth('attendanceMonth','report month');if(!v)return;const cls=$('attendanceClass').value;openSource('attendance.html',{report:'monthly-attendance',month:v,...(cls?{class:decodeURIComponent(cls)}:{})},'attendancePdfBtn')});
$('openStudent').addEventListener('click',()=>{const id=$('reportStudent').value;if(!id){window.QuranJourneyToast?.show('Select a student first.','error');$('reportStudent').focus();return}openSource('student.html',{id:decodeURIComponent(id)},'progressPdfBtn')});
loadLists();
})();