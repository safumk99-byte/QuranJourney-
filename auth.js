(()=>{'use strict';
const TOKEN_KEY='quranJourney.auth.token',USER_KEY='quranJourney.auth.user';
const config=window.QURAN_JOURNEY_CONFIG||{};
const apiBase=String(config.API_BASE_URL||'').trim().replace(/\/$/,'');
const getUser=()=>{try{return JSON.parse(sessionStorage.getItem(USER_KEY)||'null')}catch{return null}};
const getToken=()=>sessionStorage.getItem(TOKEN_KEY)||'';
const clear=()=>{sessionStorage.removeItem(TOKEN_KEY);sessionStorage.removeItem(USER_KEY)};
const api=async(path,options={})=>{
 if(!apiBase)throw new Error('API URL is not configured. Set API_BASE_URL in config.js to the Render service URL.');
 const headers={'Content-Type':'application/json',...(options.headers||{})};
 if(options.auth!==false&&getToken())headers.Authorization='Bearer '+getToken();
 const response=await fetch(apiBase+path,{...options,headers});
 const data=await response.json().catch(()=>({detail:'Server returned a non-JSON response'}));
 if(!response.ok)throw new Error(data.detail||('Request failed ('+response.status+')'));
 return data;
};
window.QuranJourneyAuth={api,apiBase,getUser,getToken,clear,login:async(login_id,password)=>{
 const data=await api('/auth/login',{method:'POST',auth:false,body:JSON.stringify({login_id,password})});
 sessionStorage.setItem(TOKEN_KEY,data.access_token);sessionStorage.setItem(USER_KEY,JSON.stringify(data.user));return data.user;
},logout:()=>{clear();location.replace('./login.html')},requireRole:(roles)=>{
 const user=getUser();
 if(!getToken()||!user){location.replace('./login.html');return false}
 if(!roles.includes(user.role)){location.replace(user.role==='parent'?'./parent.html':'./index.html');return false}
 return true;
}};
})();