(()=>{'use strict';
const TOKEN_KEY='quranJourney.auth.token',USER_KEY='quranJourney.auth.user',REFRESH_KEY='quranJourney.auth.refresh';
const toastScript=document.createElement('script');toastScript.src='./toast.js?v=global-popup-20261102';toastScript.defer=true;document.head.appendChild(toastScript);
const config=window.QURAN_JOURNEY_CONFIG||{};
const apiBase=String(config.API_BASE_URL||'').trim().replace(/\/$/,'');
const getUser=()=>{try{return JSON.parse(localStorage.getItem(USER_KEY)||'null')}catch{return null}};
const getToken=()=>localStorage.getItem(TOKEN_KEY)||'';
const getRefreshToken=()=>localStorage.getItem(REFRESH_KEY)||'';
const clear=()=>{localStorage.removeItem(TOKEN_KEY);localStorage.removeItem(USER_KEY);localStorage.removeItem(REFRESH_KEY)};
let refreshPromise=null;
const rawRequest=async(path,options={},tokenOverride)=>{
 const headers={'Content-Type':'application/json',...(options.headers||{})};
 const token=tokenOverride===undefined?getToken():tokenOverride;
 if(options.auth!==false&&token)headers.Authorization='Bearer '+token;
 const response=await fetch(apiBase+path,{...options,headers});
 const data=await response.json().catch(()=>({detail:'Server returned a non-JSON response'}));
 return {response,data};
};
const refresh=async()=>{
 if(refreshPromise)return refreshPromise;
 refreshPromise=(async()=>{
  const refreshToken=getRefreshToken();
  if(!refreshToken)throw new Error('Session expired. Please sign in again.');
  const {response,data}=await rawRequest('/auth/refresh',{method:'POST',auth:false,body:JSON.stringify({refresh_token:refreshToken})},'');
  if(!response.ok||!data.access_token||!data.refresh_token)throw new Error(data.detail||'Session expired. Please sign in again.');
  localStorage.setItem(TOKEN_KEY,data.access_token);
  localStorage.setItem(REFRESH_KEY,data.refresh_token);
  return data.access_token;
 })();
 try{return await refreshPromise}finally{refreshPromise=null}
};
const api=async(path,options={})=>{
 try{
  if(!apiBase)throw new Error('API URL is not configured. Set API_BASE_URL in config.js to the Render service URL.');
  let {response,data}=await rawRequest(path,options);
  if(response.status===401&&options.auth!==false){
   if(getRefreshToken()){
    try{const fresh=await refresh();({response,data}=await rawRequest(path,options,fresh))}
    catch(refreshError){clear();location.replace('./login.html');throw refreshError}
   }else{clear();location.replace('./login.html')}
   if(response.status===401){clear();location.replace('./login.html')}
  }
  if(!response.ok){
   const detail=data?.detail??data?.message;
   let message='';
   if(Array.isArray(detail)){
    message=detail.map(item=>{
     if(typeof item==='string')return item;
     const where=Array.isArray(item?.loc)?item.loc.filter(x=>x!=='body').join(' → '):'';
     const why=item?.msg||item?.message||JSON.stringify(item);
     return (where?where+': ':'')+why;
    }).join(' | ');
   }else if(typeof detail==='string')message=detail;
   else if(detail&&typeof detail==='object')message=detail.message||detail.msg||JSON.stringify(detail);
   throw new Error(message||('Request failed ('+response.status+')'));
  }
  return data;
 }catch(error){
  window.QuranJourneyToast?.show(error?.message||'Something went wrong. Please try again.','error');
  throw error;
 }
};
window.QuranJourneyAuth={api,apiBase,getUser,getToken,clear,login:async(login_id,password)=>{
 const data=await api('/auth/login',{method:'POST',auth:false,body:JSON.stringify({login_id,password})});
 localStorage.setItem(TOKEN_KEY,data.access_token);if(data.refresh_token)localStorage.setItem(REFRESH_KEY,data.refresh_token);localStorage.setItem(USER_KEY,JSON.stringify(data.user));return data.user;
},changePassword:async(current_password,new_password)=>api('/auth/change-password',{method:'POST',body:JSON.stringify({current_password,new_password})}),changeTeacherCredentials:async(current_password,new_login_id,new_password)=>api('/auth/change-teacher-credentials',{method:'POST',body:JSON.stringify({current_password,new_login_id,new_password})}),logout:async()=>{const refreshToken=getRefreshToken();if(refreshToken){try{await rawRequest('/auth/logout',{method:'POST',auth:false,body:JSON.stringify({refresh_token:refreshToken})},'')}catch{}}clear();location.replace('./login.html')},requireRole:(roles)=>{
 const user=getUser();
 if(!getToken()||!user){location.replace('./login.html');return false}
 if(!roles.includes(user.role)){location.replace(user.role==='parent'?'./parent.html':'./index.html');return false}
 return true;
}};
})();