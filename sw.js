const CACHE_NAME='quran-journey-v42';
const FILES=['./','./index.html','./style.css','./app.js','./photo.js','./manifest.json','./icon.svg','./students.html','./students.js','./attendance.html','./discipline.html','./discipline.js','./attendance.js','./student.html','./student.js','./challenge.html','./challenge.js','./parent.html','./parent.js','./notifications.html','./notifications.js','./exam.html','./exam.js','./login.html','./nav.js','./theme.js','./theme.js','./config.js','./auth.js'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE_NAME).then(cache=>cache.addAll(FILES)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('quran-journey-')&&key!==CACHE_NAME).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  if(url.origin!==location.origin)return;
  const dynamic=event.request.mode==='navigate'||['script','style'].includes(event.request.destination)||/\.(html|js|css)$/.test(url.pathname);
  if(dynamic){
    event.respondWith(fetch(event.request).then(response=>{
      if(response.ok){const copy=response.clone();caches.open(CACHE_NAME).then(cache=>cache.put(event.request,copy));}
      return response;
    }).catch(()=>caches.match(event.request).then(cached=>cached||caches.match('./index.html'))));
    return;
  }
  event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request).then(response=>{
    if(response.ok){const copy=response.clone();caches.open(CACHE_NAME).then(cache=>cache.put(event.request,copy));}
    return response;
  })));
});