(()=>{'use strict';
const $=id=>document.getElementById(id),A=window.QuranJourneyAuth;
if(!A||!A.requireRole(['teacher','parent']))return;
const API='https://api.alquran.cloud/v1/quran/quran-uthmani',DB='quran-journey-reader',STORE='data',TOTAL=6236;
let data=null,surahNo=1,ayahNo=1,size=29,timer=null;
const params=new URLSearchParams(location.search),startSurah=Number(params.get('surah'))||1,startAyah=Number(params.get('ayah'))||1;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function say(s){$('status').textContent=s}
function db(){return new Promise((ok,no)=>{const r=indexedDB.open(DB,1);r.onupgradeneeded=()=>r.result.createObjectStore(STORE);r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)})}
async function readCache(){try{const d=await db();return await new Promise((ok,no)=>{const r=d.transaction(STORE).objectStore(STORE).get('uthmani');r.onsuccess=()=>ok(r.result||null);r.onerror=()=>no(r.error)})}catch(_){return null}}
async function writeCache(v){const d=await db();return new Promise((ok,no)=>{const t=d.transaction(STORE,'readwrite');t.objectStore(STORE).put(v,'uthmani');t.oncomplete=ok;t.onerror=()=>no(t.error)})}
function check(v){if(!v||!Array.isArray(v.surahs)||v.surahs.length!==114)throw Error('114 സൂറത്തുകളുള്ള ഡാറ്റ ലഭിച്ചില്ല.');let n=0;v.surahs.forEach((s,i)=>{if(Number(s.number)!==i+1||!Array.isArray(s.ayahs)||s.ayahs.length!==Number(s.numberOfAyahs))throw Error('സൂറത്ത് '+(i+1)+'-ന്റെ എണ്ണം പൊരുത്തപ്പെടുന്നില്ല.');s.ayahs.forEach((a,j)=>{if(Number(a.numberInSurah)!==j+1||!a.text||!Number(a.page)||!Number(a.juz))throw Error('ആയത്ത് ഡാറ്റ പരിശോധിക്കൽ പരാജയപ്പെട്ടു: '+(i+1)+':'+(j+1));n++})});if(n!==TOTAL)throw Error('ആകെ ആയത്തുകൾ 6,236 അല്ല; ലഭിച്ചത് '+n);return v}
async function load(){let v=await readCache();if(v){try{check(v);say('പരിശോധിച്ച ഖുർആൻ ഡാറ്റ ഈ ഉപകരണത്തിൽ ലഭ്യമാണ്.');return v}catch(_){v=null}}
say('പൂർണ്ണ ഖുർആൻ ടെക്സ്റ്റ് ഡൗൺലോഡ് ചെയ്യുന്നു…');const c=new AbortController(),t=setTimeout(()=>c.abort(),45000);try{const r=await fetch(API,{signal:c.signal,cache:'no-store'});if(!r.ok)throw Error('ഖുർആൻ ഡാറ്റ ഉറവിടം HTTP '+r.status);const j=await r.json();if(j.code!==200)throw Error('ഖുർആൻ ഡാറ്റ ലഭ്യമല്ല.');v=check(j.data);try{await writeCache(v);say('114 സൂറത്തുകൾ · 6,236 ആയത്തുകൾ പരിശോധിച്ചു; ഈ ഉപകരണത്തിൽ ഓഫ്‌ലൈനായി സൂക്ഷിച്ചു.')}catch(cacheError){say('ഖുർആൻ ഡാറ്റ പരിശോധിച്ചു; ഇപ്പോൾ വായിക്കാം. ഉപകരണത്തിൽ ഓഫ്‌ലൈനായി സൂക്ഷിക്കാൻ കഴിഞ്ഞില്ല: '+(cacheError.message||'Storage unavailable'))}return v}catch(e){v=await readCache();if(v){check(v);say('ഇന്റർനെറ്റ് ലഭ്യമല്ല; ഉപകരണത്തിൽ സൂക്ഷിച്ച ഡാറ്റ ഉപയോഗിക്കുന്നു.');return v}throw Error(e.name==='AbortError'?'ഡൗൺലോഡ് സമയപരിധി കഴിഞ്ഞു. വീണ്ടും ശ്രമിക്കുക.':e.message)}finally{clearTimeout(t)}}
const surah=n=>data.surahs.find(s=>Number(s.number)===Number(n));
const flat=()=>data.surahs.flatMap(s=>s.ayahs.map(a=>({...a,surah:s})));
function populate(){$('surah').innerHTML=data.surahs.map(s=>'<option value="'+s.number+'">'+s.number+'. '+esc(s.englishName)+' · '+esc(s.name)+'</option>').join('');$('juz').innerHTML='<option value="">ജുസ് തിരഞ്ഞെടുക്കുക</option>'+Array.from({length:30},(_,i)=>'<option value="'+(i+1)+'">ജുസ് '+(i+1)+'</option>').join('')}
function render(scroll=true){const s=surah(surahNo),current=s.ayahs[ayahNo-1];$('surah').value=surahNo;$('ayah').value=ayahNo;$('juz').value=String(current.juz);$('page').value=String(current.page);$('surahName').textContent=s.name;$('surahInfo').textContent=s.englishName+' · '+s.englishNameTranslation+' · '+s.numberOfAyahs+' ആയത്തുകൾ · '+s.revelationType;
const b=surahNo!==1&&surahNo!==9?'<div class="qr-bism" lang="ar">بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ</div>':''; $('text').innerHTML=b+s.ayahs.map(a=>'<span class="qr-ayah '+(a.numberInSurah===ayahNo?'active':'')+'" data-ayah="'+a.numberInSurah+'" id="a'+a.numberInSurah+'" tabindex="0" role="button">'+esc(a.text)+' <span class="qr-mark">۞'+a.numberInSurah+'۞</span></span> ').join('');
$('prevSurah').disabled=surahNo===1;$('nextSurah').disabled=surahNo===114;$('prevPage').disabled=!pageTarget(-1);$('nextPage').disabled=!pageTarget(1);
if(scroll)requestAnimationFrame(()=> $('a'+ayahNo)?.scrollIntoView({behavior:'smooth',block:'center'}))}
function go(s,a){const x=surah(s);if(!x)return;surahNo=Number(s);ayahNo=Math.max(1,Math.min(Number(a)||1,x.numberOfAyahs));render()}
function pageTarget(d){const cur=flat().find(a=>a.surah.number===surahNo&&a.numberInSurah===ayahNo);if(!cur)return null;const p=cur.page+d;if(p<1||p>604)return null;return flat().find(a=>a.page===p)||null}
function page(d){const x=pageTarget(d);if(x)go(x.surah.number,x.numberInSurah)}
function bookmarks(){try{return JSON.parse(localStorage.getItem('qj-quran-bookmarks')||'[]')}catch(_){return []}}
function bookmark(){const ref=surahNo+':'+ayahNo,list=bookmarks(),has=list.some(x=>x.ref===ref),next=has?list.filter(x=>x.ref!==ref):[{ref,surah:surahNo,ayah:ayahNo,name:surah(surahNo).englishName},...list];localStorage.setItem('qj-quran-bookmarks',JSON.stringify(next));say(has?'ബുക്ക്മാർക്ക് നീക്കം ചെയ്തു.':'ആയത്ത് ബുക്ക്മാർക്ക് ചെയ്തു.');$('bookmark').textContent=has?'☆ ബുക്ക്മാർക്ക്':'★ സംരക്ഷിച്ചു'}
function showBookmarks(){const list=bookmarks();$('results').innerHTML=list.length?list.map(x=>'<button data-ref="'+x.ref+'"><strong>'+esc(x.name)+' · '+x.ref+'</strong><span>'+esc(surah(x.surah).ayahs[x.ayah-1].text)+'</span></button>').join(''):'ബുക്ക്മാർക്കുകൾ ഒന്നുമില്ല.'}
function search(q){q=q.trim();if(q.length<2){$('results').innerHTML='';return}const found=[];for(const s of data.surahs){for(const a of s.ayahs)if(a.text.includes(q)){found.push({s,a});if(found.length===50)break}if(found.length===50)break}$('results').innerHTML=found.length?found.map(x=>'<button data-ref="'+x.s.number+':'+x.a.numberInSurah+'"><strong>'+esc(x.s.englishName)+' · '+x.s.number+':'+x.a.numberInSurah+'</strong><span>'+esc(x.a.text)+'</span></button>').join(''):'പദം കണ്ടെത്തിയില്ല.'}
$('go').onclick=()=>{const n=Number($('ayah').value);if(!Number.isInteger(n)||n<1||n>surah(surahNo).numberOfAyahs){say('ഈ സൂറത്തിലെ സാധുവായ ആയത്ത് നമ്പർ നൽകുക.');return}go(surahNo,n)};
$('surah').onchange=()=>go(Number($('surah').value),1);
$('juz').onchange=()=>{const x=flat().find(a=>a.juz===Number($('juz').value));if(x)go(x.surah.number,x.numberInSurah)};
$('page').onchange=()=>{const n=Number($('page').value),x=flat().find(a=>a.page===n);if(!Number.isInteger(n)||n<1||n>604||!x){say('പേജ് നമ്പർ 1–604 ആയിരിക്കണം.');return}go(x.surah.number,x.numberInSurah)};
$('prevSurah').onclick=()=>go(surahNo-1,1);$('nextSurah').onclick=()=>go(surahNo+1,1);$('prevPage').onclick=()=>page(-1);$('nextPage').onclick=()=>page(1);
$('bookmark').onclick=bookmark;$('bookmarks').onclick=showBookmarks;
$('search').oninput=e=>{clearTimeout(timer);timer=setTimeout(()=>search(e.target.value),180)};
$('results').onclick=e=>{const b=e.target.closest('[data-ref]');if(!b)return;const [s,a]=b.dataset.ref.split(':').map(Number);$('results').innerHTML='';$('search').value='';go(s,a)};
$('text').onclick=e=>{const el=e.target.closest('[data-ayah]');if(el){ayahNo=Number(el.dataset.ayah);render(false)}};
$('text').onkeydown=e=>{const el=e.target.closest('[data-ayah]');if(el&&(e.key==='Enter'||e.key===' ')){e.preventDefault();ayahNo=Number(el.dataset.ayah);render(false)}};
$('smaller').onclick=()=>{size=Math.max(21,size-2);document.querySelectorAll('.qr-ayah').forEach(x=>x.style.fontSize=size+'px')};$('larger').onclick=()=>{size=Math.min(43,size+2);document.querySelectorAll('.qr-ayah').forEach(x=>x.style.fontSize=size+'px')};
$('offline').onclick=async()=>{const b=$('offline');b.disabled=true;try{await writeCache(data);say('പൂർണ്ണ ഖുർആൻ ഈ ഉപകരണത്തിൽ ഓഫ്‌ലൈനായി സൂക്ഷിച്ചു.')}catch(e){say('ഓഫ്‌ലൈൻ സ്റ്റോറേജ് ലഭ്യമല്ല: '+(e.message||'Storage unavailable'))}finally{b.disabled=false}};
(async()=>{try{data=await load();populate();go(startSurah,startAyah)}catch(e){say(e.message);$('text').textContent='ഖുർആൻ ഡാറ്റ ലോഡ് ചെയ്യാനായില്ല. ഇന്റർനെറ്റ് പരിശോധിച്ച് വീണ്ടും ശ്രമിക്കുക.'}})();
})();