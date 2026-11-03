(()=>{'use strict';
const CONFIG=window.QURAN_JOURNEY_CONFIG||{};
const API=(CONFIG.API_BASE_URL||'').replace(/\/$/,'');
const WIDTH=window.innerWidth<=560?480:800;
const IMAGE_VERSION=8;
const CACHE='quran-journey-mushaf-madani1405-v'+IMAGE_VERSION+'-'+WIDTH;
const NS='http://www.w3.org/2000/svg';
let zoom=1,activeSvg=null,activeObjectUrl=null,selected=null,renderToken=0;
function resourceUrl(page,coordinates){if(!API)throw new Error('Quran Journey API URL is not configured.');return API+'/quran/mushaf/page/'+page+(coordinates?'/coordinates':'')+'?width='+WIDTH+'&v='+IMAGE_VERSION}
async function resource(url){
 const request=new Request(url,{mode:'cors'});
 if('caches'in window){try{const cache=await caches.open(CACHE),cached=await cache.match(request);if(cached)return cached}catch(_){}}
 const response=await fetch(request);
 if(!response.ok)throw new Error('Madinah Mushaf asset unavailable (HTTP '+response.status+').');
 if('caches'in window){try{const cache=await caches.open(CACHE);await cache.put(request,response.clone())}catch(_){}}
 return response;
}
function applyZoom(){const wrap=$('mushafArtWrap');if(wrap)wrap.style.width=(zoom*100)+'%'}
function highlight(surah,ayah){
 selected={surah:Number(surah),ayah:Number(ayah)};
 if(!activeSvg)return;
 activeSvg.querySelectorAll('[data-surah][data-ayah]').forEach(rect=>{
  const active=Number(rect.getAttribute('data-surah'))===selected.surah&&Number(rect.getAttribute('data-ayah'))===selected.ayah;
  rect.setAttribute('fill',active?'#d2a95e':'transparent');
  rect.setAttribute('fill-opacity',active?'.28':'0');
  rect.setAttribute('aria-pressed',active?'true':'false');
 });
}
function addRect(svg,rect,surah,ayah){
 const node=document.createElementNS(NS,'rect');
 node.setAttribute('x',rect[0]);node.setAttribute('y',rect[1]);
 node.setAttribute('width',Math.max(1,rect[2]-rect[0]));node.setAttribute('height',Math.max(1,rect[3]-rect[1]));
 node.setAttribute('fill','transparent');node.setAttribute('fill-opacity','0');
 node.setAttribute('data-surah',surah);node.setAttribute('data-ayah',ayah);
 node.setAttribute('role','button');node.setAttribute('tabindex','0');
 node.setAttribute('aria-label','Surah '+surah+', Ayah '+ayah);
 return node;
}
async function render(page,surah,ayah,onAyah){
 const host=$('text');if(!host)throw new Error('Mushaf display container is missing.');
 const token=++renderToken;host.setAttribute('aria-busy','true');
 try{
  const [imageResponse,coordinateResponse]=await Promise.all([
   resource(resourceUrl(page,false)),resource(resourceUrl(page,true))
  ]);
  const [blob,coordinates]=await Promise.all([imageResponse.blob(),coordinateResponse.json()]);
  if(token!==renderToken)return false;
  if(coordinates.edition!=='MADANI_1405'||Number(coordinates.page)!==Number(page)||Number(coordinates.width)!==WIDTH||!Array.isArray(coordinates.ayahs))throw new Error('Madani 1405 ayah coordinates failed validation.');
  const objectUrl=URL.createObjectURL(blob),img=document.createElement('img');
  img.className='mushaf-page-image';img.alt='Quran for Android Madani Mushaf page '+page;
  img.decoding='async';img.draggable=false;img.src=objectUrl;
  await img.decode();
  if(token!==renderToken){URL.revokeObjectURL(objectUrl);return false}
  const width=img.naturalWidth,height=img.naturalHeight;
  if(width!==WIDTH||!height)throw new Error('Mushaf page image dimensions do not match the coordinate edition.');
  const wrapper=document.createElement('div');wrapper.id='mushafArtWrap';wrapper.className='mushaf-art-wrap';wrapper.style.width=(zoom*100)+'%';
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 '+width+' '+height);
  svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('class','mushaf-ayah-hit-layer');
  svg.setAttribute('role','group');svg.setAttribute('aria-label','Selectable ayahs on page '+page);
  coordinates.ayahs.forEach(item=>item.rects.forEach(rect=>svg.appendChild(addRect(svg,rect,item.surah,item.ayah))));
  svg.addEventListener('click',event=>{const node=event.target.closest&&event.target.closest('[data-surah][data-ayah]');if(!node)return;const s=Number(node.getAttribute('data-surah')),a=Number(node.getAttribute('data-ayah'));highlight(s,a);if(onAyah)onAyah(s,a)});
  svg.addEventListener('keydown',event=>{const node=event.target.closest&&event.target.closest('[data-surah][data-ayah]');if(node&&(event.key==='Enter'||event.key===' ')){event.preventDefault();const s=Number(node.getAttribute('data-surah')),a=Number(node.getAttribute('data-ayah'));highlight(s,a);if(onAyah)onAyah(s,a)}});
  wrapper.append(img,svg);host.replaceChildren(wrapper);activeSvg=svg;
  if(activeObjectUrl)URL.revokeObjectURL(activeObjectUrl);activeObjectUrl=objectUrl;
  highlight(surah,ayah);applyZoom();return true;
 }finally{if(token===renderToken)host.setAttribute('aria-busy','false')}
}
function changeZoom(delta){zoom=Math.max(.75,Math.min(1.65,zoom+delta));applyZoom();return zoom}
async function cachePage(page){await Promise.all([resource(resourceUrl(page,false)),resource(resourceUrl(page,true))])}
async function cacheAll(onProgress){for(let page=1;page<=604;page++){await cachePage(page);if(onProgress)onProgress(page,604)}return true}
window.QuranMushaf={render,changeZoom,cacheAll,cachePage,version:'MADANI_1405',width:WIDTH};
})();