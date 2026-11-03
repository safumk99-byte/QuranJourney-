(()=>{'use strict';
const VERSION='v1.1.1';
const BASE='https://cdn.quran.ws/svg/pages/'+VERSION+'/hafs-kfqc/';
const CACHE='quran-journey-mushaf-'+VERSION;
const $=id=>document.getElementById(id);
let zoom=1,selected=null,activeSvg=null;
function pageUrl(page){return BASE+String(page).padStart(3,'0')+'.svg'}
async function pageText(page){
 const url=pageUrl(page),request=new Request(url,{mode:'cors'});
 if('caches'in window){try{const cache=await caches.open(CACHE),saved=await cache.match(request);if(saved)return await saved.text()}catch(_){}}
 const response=await fetch(request,{mode:'cors'});
 if(!response.ok)throw new Error('Mushaf page '+page+' could not be loaded (HTTP '+response.status+').');
 const text=await response.text();
 if(!text.includes('<svg')||!text.includes('ayahPolygon'))throw new Error('Mushaf page '+page+' has invalid artwork data.');
 if('caches'in window){try{const cache=await caches.open(CACHE);await cache.put(request,response.clone())}catch(_){}}
 return text;
}
function markSelection(svg,surah,ayah){
 selected={surah:Number(surah),ayah:Number(ayah)};
 svg.querySelectorAll('.ayahPolygon').forEach(path=>{
  const match=Number(path.getAttribute('surah'))===selected.surah&&Number(path.getAttribute('ayah'))===selected.ayah;
  path.style.fill=match?'#c49a50':'transparent';
  path.style.fillOpacity=match?'.22':'0';
  path.setAttribute('aria-pressed',match?'true':'false');
 });
}
async function render(page,surah,ayah,onAyah){
 const host=$('text');if(!host)throw new Error('Mushaf display container is missing.');
 host.setAttribute('aria-busy','true');
 try{
  const source=await pageText(page),doc=new DOMParser().parseFromString(source,'image/svg+xml');
  if(doc.querySelector('parsererror'))throw new Error('Mushaf SVG parsing failed.');
  const svg=document.importNode(doc.documentElement,true);
  svg.classList.add('mushaf-artwork');svg.setAttribute('role','group');svg.setAttribute('aria-label','Madinah Mushaf page '+page);
  svg.querySelectorAll('path.ayahPolygon').forEach(path=>{
   const s=Number(path.getAttribute('surah')),a=Number(path.getAttribute('ayah'));
   path.style.cursor='pointer';path.style.pointerEvents='all';path.setAttribute('tabindex','0');
   path.setAttribute('role','button');path.setAttribute('aria-label','Surah '+s+', Ayah '+a);
  });
  svg.addEventListener('click',event=>{const path=event.target.closest&&event.target.closest('path.ayahPolygon');if(!path)return;const s=Number(path.getAttribute('surah')),a=Number(path.getAttribute('ayah'));markSelection(svg,s,a);if(onAyah)onAyah(s,a)});
  svg.addEventListener('keydown',event=>{const path=event.target.closest&&event.target.closest('path.ayahPolygon');if(path&&(event.key==='Enter'||event.key===' ')){event.preventDefault();const s=Number(path.getAttribute('surah')),a=Number(path.getAttribute('ayah'));markSelection(svg,s,a);if(onAyah)onAyah(s,a)}});
  markSelection(svg,surah,ayah);
  host.replaceChildren(svg);activeSvg=svg;applyZoom();return true;
 }finally{host.setAttribute('aria-busy','false')}
}
function applyZoom(){if(activeSvg)activeSvg.style.width=(zoom*100)+'%'}
function changeZoom(delta){zoom=Math.max(.75,Math.min(1.65,zoom+delta));applyZoom();return zoom}
async function cachePage(page){await pageText(page)}
async function cacheAll(onProgress){
 for(let page=1;page<=604;page++){await cachePage(page);if(onProgress)onProgress(page,604)}
 return true;
}
window.QuranMushaf={render,changeZoom,cacheAll,cachePage,pageUrl,version:VERSION};
})();