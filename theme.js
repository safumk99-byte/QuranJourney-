(()=>{'use strict';
const KEY='qj-theme',root=document.documentElement;
function saved(){try{return localStorage.getItem(KEY)}catch(_){return null}}
function initial(){const v=saved();if(v==='dark'||v==='light')return v;return matchMedia?.('(prefers-color-scheme: dark)').matches?'dark':'light'}
function apply(mode){const dark=mode==='dark';root.dataset.theme=dark?'dark':'light';root.style.colorScheme=dark?'dark':'light';document.querySelectorAll('meta[name="theme-color"]').forEach(m=>m.content=dark?'#101c19':'#0b5b46');const b=document.getElementById('qjThemeToggle');if(b){b.setAttribute('aria-pressed',String(dark));b.setAttribute('aria-label',dark?'Switch to light mode':'Switch to dark mode');b.title=dark?'Switch to light mode':'Switch to dark mode';b.innerHTML=dark?'<span aria-hidden="true">☀</span><span class="qj-theme-label">Light</span>':'<span aria-hidden="true">☾</span><span class="qj-theme-label">Dark</span>'}}
apply(initial());
function init(){if(!document.getElementById('qjThemeToggle')){const b=document.createElement('button');b.type='button';b.id='qjThemeToggle';b.className='qj-theme-toggle';b.addEventListener('click',()=>{const n=root.dataset.theme==='dark'?'light':'dark';try{localStorage.setItem(KEY,n)}catch(_){}apply(n)});const header=document.querySelector('.topbar');if(header){const nav=header.querySelector('.qj-nav');if(nav){const logout=nav.querySelector('#qjLogout');nav.insertBefore(b,logout||null)}else header.appendChild(b)}else{b.classList.add('qj-theme-floating');document.body.appendChild(b)}apply(root.dataset.theme||initial())}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
window.addEventListener('storage',e=>{if(e.key===KEY)apply(e.newValue==='dark'?'dark':'light')});
if(window.matchMedia){const mq=matchMedia('(prefers-color-scheme: dark)');mq.addEventListener?.('change',e=>{if(!saved())apply(e.matches?'dark':'light')})}
window.QuranJourneyTheme={set:m=>{const n=m==='dark'?'dark':'light';try{localStorage.setItem(KEY,n)}catch(_){}apply(n)},get:()=>root.dataset.theme||'light'};
})();