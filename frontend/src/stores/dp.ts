import {defineStore} from 'pinia';import {ref,computed} from 'vue';import * as dpApi from '../api/dp';import type {DpBudget,DpRelease} from '../types/domain';
export const useDp=defineStore('dp',()=>{const budgets=ref<DpBudget[]>([]),releases=ref<DpRelease[]>([]),selected=ref(0);
const current=computed(()=>releases.value.find(r=>r.id===selected.value));
const budgetFor=(studyId:number)=>budgets.value.find(b=>b.study_id===studyId);
async function loadBudgets(){budgets.value=await dpApi.budgets();}
async function loadReleases(studyId?:number){releases.value=await dpApi.releases(studyId);if(!releases.value.some(r=>r.id===selected.value))selected.value=releases.value[0]?.id||0;}
async function load(studyId?:number){await Promise.all([loadBudgets(),loadReleases(studyId)]);}
function select(id:number){selected.value=id;}
async function preset(data:unknown){const b=await dpApi.setBudget(data);await loadBudgets();return b;}
async function publish(data:unknown){const r=await dpApi.create(data);await Promise.all([loadBudgets(),loadReleases(Number((data as {study_id:number}).study_id))]);select(r.id);return r;}
async function resume(id:number){const r=await dpApi.retry(id);await Promise.all([loadBudgets(),loadReleases()]);select(r.id);return r;}
async function distribute(id:number){await dpApi.download(id);}
return {budgets,releases,selected,current,budgetFor,loadBudgets,loadReleases,load,select,preset,publish,resume,distribute};});
