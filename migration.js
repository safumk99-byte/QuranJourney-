(()=>{'use strict';
const auth=window.QuranJourneyAuth;
if(!auth||!auth.requireRole(['teacher']))return;
const $=id=>document.getElementById(id);
let normalized=null;
function count(x){return Array.isArray(x)?x.length:x&&typeof x==='object'?Object.keys(x).length:0}
function validate(raw){
 if(!raw||typeof raw!=='object'||raw.format!=='quran-journey-local-backup'||raw.version!==1||!raw.records||typeof raw.records!=='object')throw new Error('This is not a supported Quran Journey backup (expected format version 1).');
 const r=raw.records;
 const data={
  students:r['quranJourney.students.v1']||[],
  photos:r['quranJourney.photos.v1']||{},
  daily_marks:r['quranJourney.dailyMarks.v1']||[],
  reading_entries:r['quranJourney.readingEntries.v1']||[],
  reading_base_pages:r['quranJourney.readingBasePages.v1']||{}
 };
 if(!Array.isArray(data.students)||!Array.isArray(data.daily_marks)||!Array.isArray(data.reading_entries)||!data.photos||typeof data.photos!=='object'||Array.isArray(data.photos)||!data.reading_base_pages||typeof data.reading_base_pages!=='object'||Array.isArray(data.reading_base_pages))throw new Error('Backup record structure is invalid. No data was imported.');
 if(data.students.length>5000||data.daily_marks.length>20000||data.reading_entries.length>50000)throw new Error('Backup exceeds the per-request limit. No data was imported.');
 if(data.students.some(s=>!s||typeof s.id!=='string'&&typeof s.id!=='number'||!String(s.name||'').trim()))throw new Error('A student record is missing an ID or name. No data was imported.');
 return data;
}
$('previewBtn').addEventListener('click',async()=>{
 normalized=null;$('importBtn').disabled=true;$('result').textContent='';
 const f=$('backupFile').files[0];if(!f){$('preview').textContent='Please choose a JSON backup file.';return}
 if(f.size>15*1024*1024){$('preview').textContent='The selected file is larger than 15 MB. No data was imported.';return}
 try{const raw=JSON.parse(await f.text());normalized=validate(raw);$('preview').textContent='Backup validated. Students: '+count(normalized.students)+' · Photos: '+count(normalized.photos)+' · Reading entries: '+count(normalized.reading_entries)+' · Daily marks: '+count(normalized.daily_marks)+'. Please confirm before import.';$('importBtn').disabled=false}
 catch(e){$('preview').textContent='Validation failed: '+e.message}
});
$('importBtn').addEventListener('click',async()=>{
 if(!normalized)return;
 if(!confirm('Import this backup to the database now? Existing browser data will not be deleted.'))return;
 $('importBtn').disabled=true;$('preview').textContent='Import in progress…';$('result').textContent='';
 try{const result=await auth.api('/migration/localstorage',{method:'POST',body:JSON.stringify(normalized)});$('preview').textContent='Import completed. Review the counts below before proceeding.';$('result').textContent=JSON.stringify(result,null,2)}
 catch(e){$('preview').textContent='Import failed: '+e.message+' You can safely retry after checking the error.';$('importBtn').disabled=false}
});
})();