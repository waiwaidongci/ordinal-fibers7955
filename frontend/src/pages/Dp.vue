<script setup lang="ts">import {onMounted,watch,ref,computed} from 'vue';import {useDp} from '../stores/dp';import {useStudies} from '../stores/studies';import {useAuth} from '../stores/auth';import {useTask} from '../hooks/useTask';import {num,date} from '../utils/format';import PageHeading from '../components/common/PageHeading.vue';import ErrorNotice from '../components/common/ErrorNotice.vue';import StatusBadge from '../components/common/StatusBadge.vue';import StudySelect from '../components/StudySelect.vue';const dp=useDp(),study=useStudies(),auth=useAuth(),{error,busy,perform}=useTask(),total=ref(1),epsilon=ref(.1),name=ref('对外合作 · 等级分布'),message=ref('');
const budget=computed(()=>dp.budgetFor(study.selected)),release=computed(()=>dp.current),requested=computed(()=>epsilon.value>0?Math.round(epsilon.value*1e6)/1e6:0),overspend=computed(()=>!!budget.value&&requested.value>budget.value.remaining_epsilon+1e-12);
onMounted(()=>perform(async()=>{await study.load();await dp.load(study.selected);}));
async function saveBudget(){await dp.preset({study_id:study.selected,total_epsilon:total.value});message.value='研究总ε已登记；已花费额度不会因重新登记而回退。'}
async function submit(){const r=await dp.publish({study_id:study.selected,name:name.value,epsilon:epsilon.value});message.value=r.reused?'相同冻结输入与ε已复用同一发布，未再次扣费。':'新发布已扣费并落盘。'}
async function resume(id:number){await dp.resume(id);message.value='已按原噪声种子恢复发布，未重新抽噪、未退费。'}
async function distribute(id:number){await dp.distribute(id);message.value='分发文件只含已扣费加噪表，不含原始频数或逐份等级。'}
watch(()=>study.selected,id=>{message.value='';if(id)perform(()=>dp.load(id))});</script>
<template><PageHeading no="07" title="差分发布" sub="对外只取同一份已扣费加噪频数；相同冻结输入与ε跨名称复用，更正等级或新增版本不重置预算。"/><StudySelect/><ErrorNotice :error="error"/><p v-if="message" role="status" class="success">{{message}}</p>
<div class="dp-spread">
<section>
<h2 class="ruled-title">研究预设总ε <small>{{budget?`已花 ${num(budget.spent_epsilon,6)} / ${num(budget.total_epsilon,6)}`:'尚未登记'}}</small></h2>
<div v-if="budget" class="result-metrics"><div><small>总ε</small><strong>{{num(budget.total_epsilon,4)}}</strong><span>研究级预设</span></div><div><small>已花费ε</small><strong>{{num(budget.spent_epsilon,4)}}</strong><span>累计，不重置</span></div><div><small>剩余ε</small><strong>{{num(budget.remaining_epsilon,4)}}</strong><span>低于请求即拒绝</span></div><div><small>预设人</small><strong class="small-metric">{{budget.preset_by||'—'}}</strong><span>复检负责人</span></div></div>
<form v-if="auth.user?.role==='admin'" class="form-grid" @submit.prevent="perform(saveBudget)"><label>研究总ε<input v-model.number="total" aria-label="研究总ε" name="total_epsilon" type="number" min="0.000001" max="1000" step="any" required/></label><div class="button-row"><button class="primary" :disabled="busy">登记 / 调整总ε</button></div></form>
<p v-else class="muted">总ε由复检负责人预设；观察员与分析员只读已扣费发布。</p>
<div class="method-note"><b>邻接关系与敏感度</b><p>邻接＝在同一研究内替换一份独立试样记录（形成等级和/或所属工艺），试样总数不变。</p><p>一次替换最多改变两个等级格各1，故整表L1敏感度=2；每格独立加Laplace(0, 2/ε)。</p><p>总ε按研究累计，只减不增的回退被拒绝；同一冻结输入与同一ε只扣一次。</p></div>
<h2 class="ruled-title">按预设ε发布</h2>
<form v-if="auth.canEdit" @submit.prevent="perform(submit)"><label>发布名称<input v-model="name" aria-label="发布名称" name="release_name" required minLength="2" maxLength="140"/></label><label>本次ε<input v-model.number="epsilon" aria-label="本次ε" name="release_epsilon" type="number" min="0.000001" max="1000" step="any" required/></label><p class="muted">噪声尺度 = 2/ε = {{requested>0?num(2/requested,4):'—'}}；加噪频数可为负、非整数。</p><p v-if="overspend" class="error-text">剩余ε {{num(budget?.remaining_epsilon)}} 不足以支付本次 {{num(requested,6)}}；请求会被拒绝且不产生发布。</p><button class="primary" :disabled="busy||!auth.canEdit||!budget||overspend">{{busy?'提交中…':'生成加噪发布 →'}}</button></form><p v-else class="muted">观察员只读：可阅读与下载已扣费发布，提交由分析员完成。</p>
<aside class="margin-note">换名重试同一发布不会重新扣费或重新抽噪。若在落盘后中断，恢复时沿用已保存的噪声种子；失败不退费。发布身份按加噪结果计算，冻结输入摘要只在服务端去重，不对外提供。</aside>
</section>
<section>
<h2 class="ruled-title">本研究的发布 <small>{{dp.releases.length}}份</small></h2>
<div v-if="!dp.releases.length" class="empty">尚无差分发布。先登记总ε，再按研究预设的ε生成。</div>
<article v-for="r in dp.releases" :key="r.id" class="run-entry dp-entry">
<div class="entry-line"><small>DP {{r.id}}</small><StatusBadge :status="r.status"/></div>
<h3>{{r.names.join(' / ')}}</h3><p>ε {{num(r.epsilon,4)}} / {{r.result?.treatments.length||"—"}}工艺 × 9等级</p><small>{{date(r.created_at)}}</small>
<p v-if="r.error" class="error-text">{{r.error}}</p>
<button v-if="r.status==='released'" class="text-link" @click="dp.select(r.id)">阅读已扣费加噪频数 →</button>
<button v-if="r.status==='failed'" class="text-link" @click="perform(()=>resume(r.id))">按原种子恢复（不退费、不重抽）↻</button>
<button v-if="r.status==='released'" class="text-link" @click="perform(()=>distribute(r.id))">下载分发 CSV（仅加噪表）↙</button>
</article>
<template v-if="release?.status==='released'&&release.result">
<h2 class="ruled-title archive-title">已扣费发布 #{{release.id}}</h2>
<p class="muted">名称：{{release.names.join(' / ')}}；ε={{num(release.epsilon,4)}}；噪声尺度 {{num(release.result.noise_scale,4)}}；敏感度 {{release.result.sensitivity_l1}}。</p>
<div class="table-scroll"><table><thead><tr><th>工艺</th><th v-for="g in release.result.grade_domain" :key="g">等级 {{g}}</th></tr></thead><tbody><tr v-for="t in release.result.treatments" :key="t.code"><td><b>{{t.code}} {{t.name}}</b></td><td v-for="c in t.noisy_counts" :key="c.grade" :class="{negative:c.noisy_count<0}">{{num(c.noisy_count,3)}}</td></tr></tbody></table></div>
<div class="method-note"><b>边界</b><p>{{release.result.adjacency_explanation}}</p><p>{{release.result.disclosure}}</p></div>
<div class="fingerprint">发布摘要 <code>{{release.release_digest}}</code></div>
</template>
</section>
</div></template>
