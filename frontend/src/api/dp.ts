import {request,post} from './client';import type {DpBudget,DpRelease} from '../types/domain';
export const budgets=()=>request<DpBudget[]>('/dp/budgets');
export const setBudget=(data:unknown)=>post<DpBudget>('/dp/budgets',data);
export const releases=(study_id?:number)=>request<DpRelease[]>('/dp/releases'+(study_id?`?study_id=${study_id}`:''));
export const create=(data:unknown)=>post<DpRelease>('/dp/releases',data);
export const retry=(id:number)=>post<DpRelease>('/dp/releases/'+id+'/retry',{});
export async function download(id:number){const r=await fetch('/api/dp/releases/'+id+'/export',{headers:{Authorization:'Bearer '+localStorage.getItem('ordinal-token')}});if(!r.ok){const d=await r.json().catch(()=>({detail:'分发失败'}));throw new Error(d.detail)}const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download='青蘖差分发布_'+id+'.csv';a.click();URL.revokeObjectURL(u);}
