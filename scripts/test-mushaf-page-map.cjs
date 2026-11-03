'use strict';
const fs=require('node:fs');
const map=JSON.parse(fs.readFileSync('data/mushaf-madani-1405-page-map.json','utf8'));
const corpus=JSON.parse(fs.readFileSync('data/quran-uthmani.json','utf8'));
const backend=JSON.parse(fs.readFileSync('backend/quran_page_map.json','utf8'));
const reader=fs.readFileSync('quran.js','utf8');
const renderer=fs.readFileSync('mushaf-renderer.js','utf8');
const html=fs.readFileSync('quran.html','utf8');
const sw=fs.readFileSync('sw.js','utf8');
const api=fs.readFileSync('backend/main.py','utf8');
function assert(ok,message){if(!ok)throw new Error(message)}
assert(map.edition==='MADANI_1405','Reader must use Quran for Android MADANI_1405 edition');
assert(map.pageCount===604&&map.ayahCount===6236,'Mushaf totals must be 604 pages and 6,236 ayahs');
assert(map.pageStarts.length===604,'Exactly 604 page starts are required');
assert(map.surahAyahCounts.length===114,'Exactly 114 surah counts are required');
const counts=corpus.surahs.map(s=>s.ayahs.length);
assert(JSON.stringify(counts)===JSON.stringify(map.surahAyahCounts),'Page map surah counts must match unchanged Quran corpus');
assert(counts.reduce((a,b)=>a+b,0)===6236,'Corpus must contain exactly 6,236 ayahs');
assert(map.pageStarts[0]===1,'Page 1 must start at global ayah 1');
for(let i=0;i<map.pageStarts.length;i++){
 const value=map.pageStarts[i];
 assert(Number.isInteger(value)&&value>=1&&value<=6236,'Invalid global ayah at page '+(i+1));
 if(i)assert(value>map.pageStarts[i-1],'Page starts must be strictly increasing at page '+(i+1));
}
const offsets=[];let total=0;
for(const count of counts){offsets.push(total);total+=count}
function toRef(global){
 let lo=0,hi=offsets.length-1;
 while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(offsets[mid]<global)lo=mid;else hi=mid-1}
 return [lo+1,global-offsets[lo]];
}
assert(backend.pages.length===604,'Backend must expose 604 page starts');
for(let i=0;i<604;i++){
 const [surah,ayah]=toRef(map.pageStarts[i]);
 const row=backend.pages[i];
 assert(row[0]===i+1&&row[1]===surah&&row[2]===ayah,'Backend page map mismatch at page '+(i+1));
}
for(let i=0;i<604;i++){
 const start=map.pageStarts[i],end=i<603?map.pageStarts[i+1]-1:6236;
 assert(end>=start,'Empty page interval at page '+(i+1));
}
assert(reader.includes('mushaf-madani-1405-page-map.json'),'Reader must load the verified Madani 1405 map');
assert(reader.includes('pageForOrdinal')&&reader.includes('refForOrdinal'),'Reader must use exact ordinal-based page navigation');
assert(renderer.includes('quran/mushaf/page/')&&renderer.includes('/coordinates'),'Renderer must use official page images and ayah hit coordinates');
assert(renderer.includes("coordinates.edition!=='MADANI_1405'"),'Renderer must reject a different Mushaf edition');
assert(html.includes('./mushaf-renderer.js'),'Reader page must load the Mushaf renderer');
assert(sw.includes('./mushaf-renderer.js')&&sw.includes('./data/mushaf-madani-1405-page-map.json'),'Offline shell must cache renderer and page map');
assert(api.includes('https://android.quran.com/data/width_')&&api.includes('ayahinfo_{width}.zip'),'Backend must proxy official Quran for Android page and position assets');
console.log('PASS: MADANI_1405 edition, 604 pages, 6,236 ayahs, 114 surahs, backend page boundaries, reader navigation, SVG hit-layer integration, and offline shell references.');
