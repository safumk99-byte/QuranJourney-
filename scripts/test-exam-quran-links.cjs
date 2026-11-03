'use strict';
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('exam.js','utf8');
const start=source.indexOf('function quranAyahRef(expected){');
const end=source.indexOf('\nfunction renderQ()',start);
if(start<0||end<0)throw new Error('quranAyahRef function boundaries not found');
const sandbox={};
vm.runInNewContext(source.slice(start,end)+'\nglobalThis.quranAyahRef=quranAyahRef;',sandbox);
const parse=sandbox.quranAyahRef;
const cases=[
 ['Surah 1: Al-Fatihah 7',{surah:1,ayah:7}],
 ['Surah 2: Al-Baqarah 286',{surah:2,ayah:286}],
 ['Surah 114: An-Nas 6',{surah:114,ayah:6}],
 ['Surah 2: Ayah 255',{surah:2,ayah:255}],
 ['Surah 2: 255 · reference',{surah:2,ayah:255}],
 ['Surah 1: Al-Fatihah 8',null],
 ['Surah 2: Al-Baqarah 287',null],
 ['Surah 114: An-Nas 7',null],
 ['Surah 0: invalid 1',null],
 ['Surah 115: invalid 1',null],
 ['invalid reference',null]
];
for(const [input,expected] of cases){
 const actual=parse(input);
 if(JSON.stringify(actual)!==JSON.stringify(expected))throw new Error('Failed: '+input+'; expected '+JSON.stringify(expected)+' got '+JSON.stringify(actual));
}
console.log('PASS: '+cases.length+' Quran ayah link parser cases');
