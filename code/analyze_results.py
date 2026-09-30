import json, pathlib, re, hashlib, itertools, math, warnings
import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, binomtest
import statsmodels.api as sm
from statsmodels.genmod.cov_struct import Exchangeable
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportion_confint

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'analysis'
OUT.mkdir(parents=True, exist_ok=True)
O = ROOT / 'data/original'
C = ROOT / 'data/followup_claude'
P = ROOT / 'data/other_providers'
g = pd.read_csv(O/'hardened_grid.csv').fillna('')
m = pd.read_csv(O/'mechanism_cell.csv').fillna('')
iv = pd.read_csv(O/'intervention_full.csv').fillna('')
c = pd.read_csv(ROOT/'data/rescored/claude.csv').fillna('')
p = pd.read_csv(ROOT/'data/rescored/other_providers.csv').fillna('')
OP='claude-opus-4-5-20251101'; HA='claude-haiku-4-5-20251001'; SO='claude-sonnet-5'
DEC = re.compile(r'DECISION:\s*(KEEP|REVISE|REJECT_UNPROVABLE)', re.I)
report={}; tests=[]
def truth(x): return str(x).lower()=='true'
def sub(df,cell,models=None):
    a=df[df.cell==cell].copy()
    return a if models is None else a[a.model.isin(models)].copy()
def scores(df,col='dec_correct'):
    if col in df: return df[col].map(truth).astype(int)
    if col=='correct': return df[col].map(truth).astype(int)
    return (df.dec==col).astype(int)
def rate(df,col):return [int(scores(df,col).sum()),len(df)]
def ci(k,n): return [100*z for z in proportion_confint(k,n,method='wilson')]
def contrast(a,b,col='dec_correct'):
    k1,n1=rate(a,col);k2,n2=rate(b,col)
    l1,u1=np.array(ci(k1,n1))/100;l2,u2=np.array(ci(k2,n2))/100
    r1=k1/n1;r2=k2/n2;d=r1-r2
    nc=[100*(d-math.sqrt((r1-l1)**2+(u2-r2)**2)),100*(d+math.sqrt((u1-r1)**2+(r2-l2)**2))]
    return {'a':[k1,n1],'b':[k2,n2],'difference_pp':100*d,'newcombe_independent_ci':nc,
            'fisher':float(fisher_exact([[k1,n1-k1],[k2,n2-k2]]).pvalue)}
def paired(name,a,b,col='dec_correct', item='item'):
    a=a.assign(y=scores(a,col));b=b.assign(y=scores(b,col))
    z=a[['model',item,'y']].merge(b[['model',item,'y']],on=['model',item],suffixes=('_a','_b'),validate='one_to_one')
    d=(z.y_a-z.y_b).to_numpy(); losses=int((d==1).sum());gains=int((d==-1).sum())
    mc=binomtest(min(losses,gains),losses+gains,.5).pvalue if losses+gains else 1.
    cluster=z.assign(diff=d).groupby(item)['diff'].sum().to_numpy()
    observed=abs(cluster.sum()); total=2**len(cluster)
    count=sum(abs(np.dot(s,cluster)) >= observed-1e-12 for s in itertools.product([-1,1],repeat=len(cluster)))
    row={'name':name,'pairs':len(z),'items':len(cluster),'a_correct':int(z.y_a.sum()),'b_correct':int(z.y_b.sum()),
         'losses':losses,'gains':gains,'mcnemar_p':float(mc),'item_signflip_p':count/total,'difference_pp':100*d.mean()}
    tests.append(row);return row

report['original']={}
for name,ac,bc,label in [('false_success','NT_broken','FV_broken','REJECT_UNPROVABLE'),('false_error','NT_valid','FV_valid','KEEP')]:
    a=sub(g,ac);b=sub(g,bc);a=a[a.dec.isin(['KEEP','REVISE','REJECT_UNPROVABLE'])];b=b[b.dec.isin(['KEEP','REVISE','REJECT_UNPROVABLE'])]
    report['original'][name]=contrast(a,b,label)
    paired('original_'+name,a,b,label,'task')
    z=pd.concat([a.assign(arm=0,y=scores(a,label)),b.assign(arm=1,y=scores(b,label))])
    f=sm.GEE(z.y,sm.add_constant(z.arm),groups=z.task,family=sm.families.Binomial(),cov_struct=Exchangeable()).fit()
    report['original'][name]['gee']={'p':float(f.pvalues['arm']),'or':float(np.exp(f.params['arm'])),'or_ci':np.exp(f.conf_int().loc['arm']).tolist(),'alpha':float(f.cov_struct.dep_params)}
a=sub(m,'TWT_notool');b=sub(m,'TWT_fake_success')
report['original']['mechanism_pooled']=contrast(a,b,'correct')
paired('original_mechanism_pooled',a,b,'correct','task')
z=pd.concat([a.assign(arm=0,y=scores(a,'correct')),b.assign(arm=1,y=scores(b,'correct'))])
f=sm.GEE(z.y,sm.add_constant(z.arm),groups=z.task,family=sm.families.Binomial(),cov_struct=Exchangeable()).fit()
report['original']['mechanism_pooled']['gee']={'p':float(f.pvalues['arm']),'or':float(np.exp(f.params['arm'])),'alpha':float(f.cov_struct.dep_params)}
report['original']['gee_holm']=multipletests([report['original'][x]['gee']['p'] for x in ['false_success','false_error','mechanism_pooled']],method='holm')[1].tolist()
a=sub(m,'TWT_notool',[OP,HA]);b=sub(m,'TWT_fake_success',[OP,HA])
report['original']['mechanism_balanced']=contrast(a,b,'correct')
paired('original_mechanism_balanced',a,b,'correct','task')
report['original']['mechanism_decisions']=sub(m,'TWT_fake_success').dec.value_counts().to_dict()
report['original']['by_model']={}
for model in g.model.unique():
    report['original']['by_model'][model]={}
    for name,ac,bc,label,df in [('false_success','NT_broken','FV_broken','REJECT_UNPROVABLE',g),('false_error','NT_valid','FV_valid','KEEP',g),('mechanism','TWT_notool','TWT_fake_success','correct',m)]:
        a=sub(df,ac,[model]);b=sub(df,bc,[model]);a=a[a.dec.isin(['KEEP','REVISE','REJECT_UNPROVABLE'])];b=b[b.dec.isin(['KEEP','REVISE','REJECT_UNPROVABLE'])]
        report['original']['by_model'][model][name]=contrast(a,b,label)
    paired('original_mechanism_'+model,sub(m,'TWT_notool',[model]),sub(m,'TWT_fake_success',[model]),'correct','task')
report['original']['intervention']={}
for model in [OP,HA]:
    a=iv[(iv.model==model)&(iv.cell=='FS')&(iv.iv=='none')]
    b=iv[(iv.model==model)&(iv.cell=='FS')&(iv.iv=='provenance')]
    report['original']['intervention'][model]=contrast(a,b,'correct')
    paired('provenance_original_'+model,a,b,'correct','task')
a=iv[(iv.cell=='FS')&(iv.iv=='none')];b=iv[(iv.cell=='FS')&(iv.iv=='human_doubt')]
report['original']['doubt']=contrast(a,b,'correct');paired('doubt_original',a,b,'correct','task')
a=iv[(iv.model==OP)&(iv.cell=='FS')&(iv.iv=='provenance')];b=iv[(iv.model==HA)&(iv.cell=='FS')&(iv.iv=='provenance')]
report['original']['between_model_provenance']=contrast(a,b,'correct')
report['original']['outcome_arithmetic_only']=contrast(pd.DataFrame({'y':[1]*40+[0]*2}),pd.DataFrame({'y':[1]*31+[0]*10}),'KEEP') if False else {}
k1,n1,k2,n2=40,42,31,41
report['original']['outcome_from_aggregate_only']=contrast(pd.DataFrame({'correct':[True]*k1+[False]*(n1-k1)}),pd.DataFrame({'correct':[True]*k2+[False]*(n2-k2)}),'correct')

report['followup']={}
plan=[('decide_error','DEC_notool','DEC_FE',[OP,HA],'dec_correct'),('tactic','ASM_FS','RFL_FS',[OP,HA],'dec_correct'),('provenance','RFL_FS_prov_mismatch','RFL_FS_prov_match',[OP],'dec_correct'),('truthful_mismatch','TV_success','TV_prov_mismatch',[OP],'dec_correct'),('sonnet_truncation','RFL_FS_cap1400','RFL_notool_cap1400',[SO],'truncated')]
for name,ac,bc,models,col in plan:
    a=sub(c,ac,models);b=sub(c,bc,models)
    report['followup'][name]=contrast(a,b,col)
    paired('selected_'+name,a,b,col)
report['followup']['holm_fisher']=dict(zip([x[0] for x in plan],multipletests([report['followup'][x[0]]['fisher'] for x in plan],method='holm')[1].tolist()))
report['followup']['holm_paired_mcnemar']=dict(zip([x[0] for x in plan],multipletests([t['mcnemar_p'] for t in tests if t['name'].startswith('selected_')],method='holm')[1].tolist()))
report['followup']['holm_item_signflip']=dict(zip([x[0] for x in plan],multipletests([t['item_signflip_p'] for t in tests if t['name'].startswith('selected_')],method='holm')[1].tolist()))
for ac,bc in [('OMG_notool','OMG_FE'),('DEC_notool','DEC_FE'),('RFL_notool','RFL_FS'),('ASM_notool','ASM_FS'),('DEC_FE','OMG_FE')]:
    a=sub(c,ac,[OP,HA]);b=sub(c,bc,[OP,HA])
    if len(a) and len(b):
        report['followup'][ac+'_vs_'+bc+'_outcome']=contrast(a,b,'outcome_correct')
        paired('outcome_'+ac+'_vs_'+bc,a,b,'outcome_correct')
for model in [OP,HA,SO]:
    report['followup'][model]={cell:{'decision':rate(sub(c,cell,[model]),'dec_correct'),'outcome':rate(sub(c,cell,[model]),'outcome_correct'),'kept':int((sub(c,cell,[model]).dec=='KEEP').sum()),'rejected':int((sub(c,cell,[model]).dec=='REJECT_UNPROVABLE').sum()),'truncated':int(sub(c,cell,[model]).truncated.map(truth).sum())} for cell in c[c.model==model].cell.unique()}
    for ac,bc in [('DEC_notool','DEC_FE'),('RFL_notool','RFL_FS'),('ASM_FS','RFL_FS')]:
        paired(model+'_'+ac+'_vs_'+bc,sub(c,ac,[model]),sub(c,bc,[model]))
for cell in ['RFL_notool','RFL_FS']:
    z=sub(c,cell,[SO]);report['followup'][cell+'_sonnet_tokens']={'median':float(pd.to_numeric(z.out_tokens).median()),'total':float(pd.to_numeric(z.out_tokens).sum())}
for model in p.model.unique():
    for ac,bc in [('NT_valid','FV_valid'),('DEC_notool','DEC_FE'),('RFL_notool','RFL_FS'),('ASM_FS','RFL_FS'),('RFL_FS_doubt','RFL_FS')]:
        paired(model+'_'+ac+'_vs_'+bc,sub(p,ac,[model]),sub(p,bc,[model]))
report['other']={}
for model in p.model.unique():
    report['other'][model]={cell:{'decision':rate(sub(p,cell,[model]),'dec_correct'),'outcome':rate(sub(p,cell,[model]),'outcome_correct'),'decisions':sub(p,cell,[model]).dec.value_counts().to_dict()} for cell in p.cell.unique()}
for name,cells in [('baseline',['NT_valid','DEC_notool']),('fabricated',['FV_valid','DEC_FE'])]:
    z=p[p.cell.isin(cells)];report['other'][name]={'kept':int((z.dec=='KEEP').sum()),'n':len(z),'outcome':rate(z,'outcome_correct')}
report['other']['gpt_mini_tactic']=contrast(sub(p,'ASM_FS',['gpt-5-mini']),sub(p,'RFL_FS',['gpt-5-mini']))
report['other']['gpt_mini_doubt']=contrast(sub(p,'RFL_FS_doubt',['gpt-5-mini']),sub(p,'RFL_FS',['gpt-5-mini']))

# Raw-to-score agreement, repeated decisions, and table sensitivities.
amb=[];raw_agreement=[];all_rows=[]
for df,folder,pattern in [(c,C,'batch2_raw_*.jsonl'),(p,P,'raw_*.jsonl')]:
    raw=[]
    for file in sorted(folder.glob(pattern)):raw.extend(json.loads(line) for line in file.open())
    raw_index={}
    for r in raw:
        key=(r.get('model_requested',r.get('deployment')),r['trial_id']);raw_index[key]=r
    for _,r in df.iterrows():
        rr=raw_index[(r.model,r.trial_id)]
        ds=[d.upper() for d in DEC.findall(r.text)]
        first=ds[0] if ds else '';last=ds[-1] if ds else ''
        all_rows.append({'source':folder.name,'model':r.model,'trial_id':r.trial_id,'cell':r.cell,'first':first,'last':last,'correct':truth(r.dec_correct),'outcome':truth(r.outcome_correct)})
        raw_agreement.append({'source':folder.name,'model':r.model,'trial_id':r.trial_id,'text_equal':(rr.get('text') or '')==r.text,'decision_equal':first==r.dec,'raw_attempt':rr.get('attempt')})
        if len(set(ds))>1:amb.append({'source':folder.name,'model':r.model,'trial_id':r.trial_id,'cell':r.cell,'first':first,'last':last,'decisions':','.join(ds),'text':r.text})
    report.setdefault('raw',{})[folder.name]={'records':len(raw),'unique':len(raw_index),'duplicate':len(raw)-len(raw_index),'input_tokens':{model:float(np.median([r['usage']['input_tokens'] for (mod,tid),r in raw_index.items() if mod==model and r.get('usage')])) for model in df.model.unique()},'output_tokens':{model:int(sum(r['usage']['output_tokens'] for (mod,tid),r in raw_index.items() if mod==model and r.get('usage'))) for model in df.model.unique()}}
ad=pd.DataFrame(amb);ad.to_csv(OUT/'conflicting_decisions.csv',index=False)
ar=pd.DataFrame(all_rows);correct_lookup={}
for folder,name in [(C,'batch2_stimuli.json'),(P,'stimuli.json')]:
    s=json.load((folder/name).open())
    correct_lookup[folder.name]={t['trial_id']:t['correct'] for t in s['trials']}
ar['reference']=[correct_lookup[r.source][r.trial_id] for _,r in ar.iterrows()]
ar['first_correct']=(ar['first']==ar.reference);ar['last_correct']=(ar['last']==ar.reference)
changed=ar.groupby(['source','model','cell'])[['first_correct','last_correct']].sum()
changed=changed[changed.first_correct!=changed.last_correct].reset_index();changed.to_csv(OUT/'parser_cell_changes.csv',index=False)
report['parser']={'with_line':int((ar['first']!='').sum()),'conflicting':len(amb),'first_last_different':int((ar['first']!=ar['last']).sum()),'changed_cells':changed.to_dict('records'),'raw_text_mismatch':sum(not r['text_equal'] for r in raw_agreement),'raw_dec_mismatch':sum(not r['decision_equal'] for r in raw_agreement)}
report['prompt_hash']={}
for folder,name in [(C,'batch2_stimuli.json'),(P,'stimuli.json')]:
    s=json.load((folder/name).open());report['prompt_hash'][folder.name]={'trials':len(s['trials']),'mismatches':sum(hashlib.sha256(t['prompt'].encode()).hexdigest()[:16]!=t['prompt_sha'] for t in s['trials'])}

# Save every cell with both metrics, and all paired sensitivity tests.
cells=[]
for source,df in [('claude',c),('other',p)]:
    for (model,cell),z in df.groupby(['model','cell']):
        k,n=rate(z,'dec_correct');o,_=rate(z,'outcome_correct')
        cells.append({'source':source,'model':model,'cell':cell,'n':n,'decision_correct':k,'outcome_correct':o,'keep':int((z.dec=='KEEP').sum()),'revise':int((z.dec=='REVISE').sum()),'reject':int((z.dec=='REJECT_UNPROVABLE').sum()),'wilson_low_pct':ci(k,n)[0],'wilson_high_pct':ci(k,n)[1]})
pd.DataFrame(cells).to_csv(OUT/'all_cell_counts.csv',index=False)
pd.DataFrame(tests).to_csv(OUT/'paired_sensitivity.csv',index=False)
report['paired']=tests
(OUT/'audit_results.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ['paired','followup','other']},indent=2))
print('SELECTED HOLM',report['followup']['holm_fisher'],report['followup']['holm_paired_mcnemar'],report['followup']['holm_item_signflip'])
print(pd.DataFrame(tests).to_string(index=False))
