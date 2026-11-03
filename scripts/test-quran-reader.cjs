'use strict';
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('quran.js','utf8');
const start=source.indexOf('function check(v){');
const end=source.indexOf('\nasync function load()',start);
if(start<0||end<0)throw new Error('Reader check() boundaries not found');
const sandbox={TOTAL:6236};
vm.runInNewContext(source.slice(start,end)+'\nglobalThis.readerCheck=check;',sandbox);
const check=sandbox.readerCheck;
const counts=[7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,110,98,135,112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,182,88,75,85,54,53,89,59,37,35,38,29,18,45,60,49,62,55,78,96,29,22,24,13,14,11,11,18,12,12,30,52,52,44,28,28,20,56,40,31,50,40,46,42,29,19,36,25,22,17,19,26,30,20,15,21,11,8,8,19,5,8,8,11,11,8,3,9,5,4,7,3,6,3,5,4,5,6];
if(counts.length!==114||counts.reduce((a,b)=>a+b,0)!==6236)throw new Error('Test fixture ayah counts invalid');
const fixture=()=>({surahs:counts.map((count,i)=>({number:i+1,numberOfAyahs:count,name:'سورة',englishName:'Surah '+(i+1),englishNameTranslation:'Chapter',revelationType:'Meccan',basmalah:null,ayahs:Array.from({length:count},(_,j)=>({number:j+1,numberInSurah:j+1,text:'آية '+(j+1),page:Math.min(604,Math.floor((i*count+j)*604/6236)+1),juz:Math.min(30,Math.floor((i*count+j)*30/6236)+1)}))}))});
const cases=[
 ['valid complete corpus',v=>check(v)],
 ['reject missing surah',v=>{v.surahs.pop();check(v)}],
 ['reject ayah count mismatch',v=>{v.surahs[1].ayahs.pop();check(v)}],
 ['reject wrong surah sequence',v=>{v.surahs[4].number=3;check(v)}],
 ['reject wrong ayah sequence',v=>{v.surahs[0].ayahs[0].number=2;check(v)}],
 ['reject empty Arabic text',v=>{v.surahs[0].ayahs[0].text=' ';check(v)}],
 ['reject page outside Mushaf',v=>{v.surahs[0].ayahs[0].page=605;check(v)}],
 ['reject juz outside range',v=>{v.surahs[0].ayahs[0].juz=31;check(v)}],
 ['reject separate basmalah in Al-Fatihah',v=>{v.surahs[0].basmalah='بسم الله';check(v)}],
 ['reject separate basmalah in At-Tawbah',v=>{v.surahs[8].basmalah='بسم الله';check(v)}],
 ['reject blank surah name',v=>{v.surahs[1].englishName='';check(v)}]
];
let passed=0;
for(const [name,mutate] of cases){
 const v=fixture();
 try{mutate(v);if(name!=='valid complete corpus')throw new Error('Expected rejection but validation passed')}
 catch(e){if(name==='valid complete corpus')throw e;if(!/സൂറത്ത്|ആയത്ത്|ഖുർആൻ|ആകെ|ഡാറ്റ/.test(e.message))throw new Error(name+': unexpected error '+e.message)}
 passed++;
}
const actual=JSON.parse(fs.readFileSync('data/quran-uthmani.json','utf8'));
check(actual);
console.log('PASS: '+passed+' synthetic validation cases + actual bundled Quran corpus');
