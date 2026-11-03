#!/usr/bin/env node
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const SOURCE='https://raw.githubusercontent.com/dotquran/corpus/main/processed/uthmani/quran-uthmani.json';
const META='https://api.alquran.cloud/v1/quran/quran-uthmani';
const EXPECTED=[7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,110,98,135,112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,182,88,75,85,54,53,89,59,37,35,38,29,18,45,60,49,62,55,78,96,29,22,24,13,14,11,11,18,12,12,30,52,52,44,28,28,20,56,40,31,50,40,46,42,29,19,36,25,22,17,19,26,30,20,15,21,11,8,8,19,5,8,8,11,11,8,3,9,5,4,7,3,6,3,5,4,5,6];
async function json(url){const r=await fetch(url,{headers:{'accept':'application/json'}});if(!r.ok)throw Error(url+' returned HTTP '+r.status);return r.json()}
function fail(m){throw Error('Quran data build failed: '+m)}
(async()=>{
 const [source,metaResponse]=await Promise.all([json(SOURCE),json(META)]);
 if(!source||!Array.isArray(source.surahs)||source.surahs.length!==114)fail('Tanzil source does not contain exactly 114 surahs');
 const meta=metaResponse.data;
 if(!meta||!Array.isArray(meta.surahs)||meta.surahs.length!==114)fail('AlQuran Cloud metadata is incomplete');
 const out={metadata:{source:'Tanzil Project Uthmani v1.1',sourceRepository:'dotquran/corpus',sourceUrl:'https://tanzil.net',license:'Creative Commons Attribution 3.0',terms:'Quran text is reproduced verbatim. Do not alter the text. Credit Tanzil Project and link to https://tanzil.net.',metadataProvider:'AlQuran Cloud (surah names, revelation type, juz and Madinah Mushaf page positions)',generatedAt:new Date().toISOString(),ayahCount:6236,surahCount:114},surahs:[]};
 let total=0;
 for(let i=0;i<114;i++){
  const s=source.surahs[i],m=meta.surahs[i],n=i+1;
  if(Number(s.number)!==n||Number(m.number)!==n)fail('Surah sequence mismatch at '+n);
  const verses=(s.ayahs||[]).filter(a=>Number(a.number)>0);
  if(verses.length!==EXPECTED[i])fail('Ayah count mismatch in surah '+n+': '+verses.length);
  const apiAyahs=m.ayahs||[];
  if(apiAyahs.length!==verses.length)fail('Metadata ayah count mismatch in surah '+n);
  const ayahs=verses.map((a,j)=>{
   const b=apiAyahs[j];
   if(Number(a.number)!==j+1||Number(b.numberInSurah)!==j+1||!a.text||!Number(b.page)||!Number(b.juz))fail('Ayah metadata mismatch at '+n+':'+(j+1));
   return {number:j+1,numberInSurah:j+1,text:a.text,page:Number(b.page),juz:Number(b.juz)};
  });
  total+=ayahs.length;
  out.surahs.push({number:n,name:s.name,englishName:m.englishName,englishNameTranslation:m.englishNameTranslation,numberOfAyahs:ayahs.length,revelationType:m.revelationType,ayahs});
 }
 if(total!==6236)fail('Expected 6236 ayahs; got '+total);
 const pages=new Set(out.surahs.flatMap(s=>s.ayahs.map(a=>a.page)));
 if(pages.size!==604||Math.min(...pages)!==1||Math.max(...pages)!==604)fail('Mushaf page coverage must be exactly 1–604');
 const juzs=new Set(out.surahs.flatMap(s=>s.ayahs.map(a=>a.juz)));
 if(juzs.size!==30||Math.min(...juzs)!==1||Math.max(...juzs)!==30)fail('Juz coverage must be exactly 1–30');
 const target=path.join(process.cwd(),'data','quran-uthmani.json');
 fs.mkdirSync(path.dirname(target),{recursive:true});
 fs.writeFileSync(target,JSON.stringify(out));
 console.log('Verified '+out.surahs.length+' surahs, '+total+' ayahs, 604 pages and 30 juz.');
 console.log('Text source: Tanzil Project Uthmani v1.1 (CC BY 3.0), unchanged.');
})().catch(e=>{console.error(e);process.exit(1)});
