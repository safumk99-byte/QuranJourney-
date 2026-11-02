(()=>{'use strict';
if(window.QuranJourneyToast)return;
const style=document.createElement('style');
style.textContent=`
#qj-toast-region{position:fixed;z-index:99999;top:18px;right:18px;display:flex;flex-direction:column;gap:10px;width:min(390px,calc(100vw - 28px));pointer-events:none}
.qj-toast{display:flex;align-items:flex-start;gap:11px;padding:14px 16px;border-radius:13px;background:#fff;color:#18352c;box-shadow:0 12px 34px #102a2030;border:1px solid #dce5df;border-left:5px solid #b42318;font:500 14px/1.55 Manjari,Arial,sans-serif;pointer-events:auto;animation:qj-toast-in .22s ease-out}
.qj-toast.success{border-left-color:#16834a}.qj-toast.info{border-left-color:#2671c9}.qj-toast.warning{border-left-color:#c17b16}
.qj-toast-icon{font-size:18px;line-height:1.3}.qj-toast-text{flex:1;overflow-wrap:anywhere}.qj-toast-close{border:0;background:transparent;color:inherit;font-size:20px;line-height:1;cursor:pointer;padding:0 0 0 5px;opacity:.65}
@keyframes qj-toast-in{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
@media(max-width:600px){#qj-toast-region{top:10px;right:10px;width:calc(100vw - 20px)}.qj-toast{padding:12px 13px}}
`;
(document.head||document.documentElement).appendChild(style);
let region;
function show(message,type='error',duration=4800){
const text=String(message??'').trim();if(!text)return;
if(!region){region=document.createElement('div');region.id='qj-toast-region';region.setAttribute('aria-live','polite');region.setAttribute('aria-relevant','additions');document.body.appendChild(region)}
const item=document.createElement('div');item.className='qj-toast '+(['success','info','warning'].includes(type)?type:'error');item.setAttribute('role',type==='error'?'alert':'status');
const icon=document.createElement('span');icon.className='qj-toast-icon';icon.textContent=type==='success'?'✓':type==='warning'?'⚠':type==='info'?'ⓘ':'!';
const body=document.createElement('span');body.className='qj-toast-text';body.textContent=text;
const close=document.createElement('button');close.className='qj-toast-close';close.type='button';close.setAttribute('aria-label','Close');close.textContent='×';
const remove=()=>{if(item.isConnected)item.remove()};close.addEventListener('click',remove);item.append(icon,body,close);region.appendChild(item);if(duration>0)setTimeout(remove,duration);
}
window.QuranJourneyToast={show};
const nativeAlert=window.alert.bind(window);window.alert=(message)=>show(message,'error',5600);
})();