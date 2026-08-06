const CACHE='escutapet-v3-6-0';
const ASSETS=['/offline','/static/css/app.css?v=3.6.0','/static/css/visual-v3.css?v=3.6.0','/static/css/conversations.css?v=3.6.0','/static/js/app.js?v=3.6.0'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))));
self.addEventListener('fetch',event=>{if(event.request.method!=='GET')return;event.respondWith(fetch(event.request).catch(()=>caches.match(event.request).then(hit=>hit||caches.match('/offline'))));});
