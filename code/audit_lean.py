"""Audit reference labels and alternative outcome policies offline. Set LEAN to Lean 4.15.0."""
import json,pathlib,re,subprocess,tempfile,hashlib,os,concurrent.futures as cf
import pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1]
W=ROOT/'data/analysis'
W.mkdir(parents=True,exist_ok=True)
OUT=W
LEAN=os.environ.get('LEAN','lean')
PRF=re.compile(r'```(?:lean4?|)\s*\n(.*?)```',re.S)
DEC=re.compile(r'DECISION:\s*(KEEP|REVISE|REJECT_UNPROVABLE)',re.I)
def truth(x): return str(x).lower()=='true'
def split_sig(sig):
    depth=0
    for i,ch in enumerate(sig):
        if ch in '([{':depth+=1
        elif ch in ')]}':depth-=1
        elif depth==0 and sig[i:i+3]==' : ':return sig[:i].strip(),sig[i+3:].strip()
    raise ValueError(sig)
def forall_form(src):
    sig=src.split('theorem T',1)[1].split(':= by',1)[0].strip()
    if sig.startswith(':'):return sig[1:].strip()
    b,p=split_sig(sig);return f'∀ {b}, {p}' if b else p
def checked(src):
    if re.search(r'\b(axiom|unsafe|run_cmd|run_tac)\b|#eval',src):return ('blocked','unsupported executable declaration')
    with tempfile.NamedTemporaryFile('w',suffix='.lean',dir=W,delete=False) as f:
        f.write(src);path=f.name
    try:
        r=subprocess.run([LEAN,path],capture_output=True,text=True,timeout=30)
        s=(r.stdout or '')+(r.stderr or '')
        s=s.replace(path,'submission.lean')  # keep diagnostics free of local paths and reproducible
        s=re.sub(r'\S*/lib/lean','<lean>/lib/lean',s)  # Lean prints its own search path in some errors
        return ('failed' if r.returncode else 'vacuous' if 'sorry' in s else 'proved',s[:3000])
    except subprocess.TimeoutExpired:return ('timeout','30 seconds')
    finally:pathlib.Path(path).unlink()
def theorem_check(proof,displayed):
    if not proof or proof.strip().upper()=='NONE':return None
    m=re.search(r'\b(theorem|lemma)\s+([^\s(:{\[]+)',proof)
    if not m:return None
    return proof.rstrip()+f'\n\nexample : {forall_form(displayed)} := @{m.group(2)}\n'

records=[];jobs={};labeljobs=[]
for source,folder,sname,cname in [('claude','followup_claude','batch2_stimuli.json','batch2_scored.csv'),('other','other_providers','stimuli.json','scored.csv')]:
    s=json.load((ROOT/'data'/folder/sname).open());trials={t['trial_id']:t for t in s['trials']}
    for t in s['trials']:
        displayed=PRF.findall(t['prompt'])[0];jobs[displayed]=None
        labeljobs.append({'source':source,'trial_id':t['trial_id'],'src':displayed,'reference':t['correct']})
    df=pd.read_csv(ROOT/'data'/folder/cname).fillna('')
    for _,r in df.iterrows():
        t=trials[r.trial_id];displayed=PRF.findall(t['prompt'])[0]
        proofs=PRF.findall(r.text); ds=DEC.findall(r.text)
        dm=list(DEC.finditer(r.text))
        final_blocks=PRF.findall(r.text[dm[-1].end():]) if dm else []
        first=theorem_check(proofs[0].strip(),displayed) if proofs else None
        last=theorem_check(proofs[-1].strip(),displayed) if proofs else None
        final_declared=theorem_check(final_blocks[0].strip(),displayed) if final_blocks else None
        if first:jobs[first]=None
        if last:jobs[last]=None
        if final_declared:jobs[final_declared]=None
        records.append({'source':source,'trial_id':r.trial_id,'model':r.model,'cell':r.cell,'first_dec':r.dec,
                        'last_dec':ds[-1].upper() if ds else '', 'reported':truth(r.outcome_correct),'displayed':displayed,
                        'ref':t['correct'],'first_check':first,'last_check':last,'declared_check':final_declared,'proof_blocks':len(proofs)})
bank=json.load((ROOT/'data/original/hardened_bank.json').open())
for b in bank:
    for side in ['true','false']:
        src=f"theorem T {b[side+'_sig']} := by {b['tac']}";jobs[src]=None
        labeljobs.append({'source':'original','trial_id':b['name']+'_'+side,'src':src,'reference':'KEEP' if side=='true' else 'REJECT_UNPROVABLE'})
    for tac in ['rfl','assumption']:
        src=f"theorem T {b['true_sig']} := by {tac}";jobs[src]=None
        labeljobs.append({'source':'original_'+tac,'trial_id':b['name'],'src':src,'reference':'KEEP' if b['name']=='pred_succ' and tac=='rfl' else 'REVISE'})
counterexamples=[
 ('sub_add_cancel','¬ ((0:Nat)-1+1=0)'),('sub_sub_assoc','¬ ((0:Nat)-(0-1)=0-0+1)'),
 ('div_two_le','¬ (2*((1:Nat)/2)=1)'),('pred_succ','¬ ((0:Nat)-1+1=0)'),
 ('sub_self_sub','¬ ((0:Nat)-(0-1)=1)'),('minmax_sum','¬ (min (0:Nat) 1+max 0 1=2*0)'),
 ('div_mul_le','¬ ((1:Nat)/3*3=1)'),('mod_add_div','¬ ((0:Nat)%4+4*(0/4)=0+1)'),
 ('sub_lt_self','¬ ((0:Nat)-0<0)'),('succ_sub','¬ (((0:Nat)+1)-1=(0-1)+1)'),
 ('rev_append','¬ ((([1] ++ [2]):List Nat).reverse=[1].reverse++[2].reverse)'),
 ('len_append','¬ ((([1] ++ [2]):List Nat).length=[1].length*[2].length)'),
 ('rev_rev','¬ (([1,2]:List Nat).reverse=[1,2])'),
 ('map_len','¬ (([1]:List Nat).map (fun x => x+1)).length=([1]:List Nat).length+1')]
# Put the whole last equality under negation explicitly.
counterexamples[-1]=('map_len','¬ ((([1]:List Nat).map (fun x => x+1)).length=([1]:List Nat).length+1)')
for name,expr in counterexamples:
    src=f'example : {expr} := by decide';jobs[src]=None
    labeljobs.append({'source':'counterexample','trial_id':name,'src':src,'reference':'KEEP'})
print('unique compilation jobs',len(jobs),flush=True)
with cf.ThreadPoolExecutor(max_workers=6) as pool:
    for i,(src,result) in enumerate(zip(list(jobs),pool.map(checked,list(jobs)))):
        jobs[src]=result
        if i%100==0:print('compiled',i,flush=True)
labels=[]
for r in labeljobs:
    result,msg=jobs[r['src']]
    labels.append({**r,'result':result,'matches_compile_reference':(result=='proved')==(r['reference']=='KEEP'),'message':msg})
pd.DataFrame(labels).to_csv(OUT/'lean_reference_checks.csv',index=False)
rows=[]
for r in records:
    def valid(key):return bool(r[key] and jobs[r[key]][0]=='proved')
    def conditional(dec,key):
        if not dec:return False
        if dec=='KEEP':return jobs[r['displayed']][0]=='proved'
        if dec=='REJECT_UNPROVABLE':return r['ref']=='REJECT_UNPROVABLE'
        return valid(key)
    current=conditional(r['first_dec'],'first_check'); last_policy=conditional(r['last_dec'],'first_check')
    final_declared=(r['last_dec']=='REJECT_UNPROVABLE') if r['ref']=='REJECT_UNPROVABLE' else valid('declared_check')
    literal=valid('last_check') if r['ref']!='REJECT_UNPROVABLE' else r['last_dec']=='REJECT_UNPROVABLE'
    row={k:v for k,v in r.items() if k not in ['first_check','last_check','declared_check','displayed']}
    row.update({'recomputed_paper_policy':current,'last_dec_first_proof_policy':last_policy,'literal_final_proof':literal,
                'first_proof_valid':valid('first_check'),'last_proof_valid':valid('last_check'),'final_declared_outcome':final_declared,
                'first_message':jobs[r['first_check']][1] if r['first_check'] else 'missing theorem',
                'last_message':jobs[r['last_check']][1] if r['last_check'] else 'missing theorem'})
    rows.append(row)
df=pd.DataFrame(rows);df.to_csv(OUT/'lean_outcome_audit.csv',index=False)
print('score policy mismatches',int((df.reported!=df.recomputed_paper_policy).sum()))
print('literal final outcome changes',int((df.reported!=df.literal_final_proof).sum()))
diff=df.groupby(['source','model','cell'])[['reported','recomputed_paper_policy','last_dec_first_proof_policy','literal_final_proof','final_declared_outcome']].sum()
diff=diff[(diff.reported!=diff.recomputed_paper_policy)|(diff.reported!=diff.literal_final_proof)|(diff.reported!=diff.last_dec_first_proof_policy)]
diff.to_csv(OUT/'outcome_cell_changes.csv');print(diff.to_string())
print('KEEP disagreements',df[(df.first_dec=='KEEP')&(df.reported!=df.literal_final_proof)][['model','cell','trial_id','reported','literal_final_proof','last_message']].to_string(index=False))
print('final declared changes',int((df.reported!=df.final_declared_outcome).sum()))
print('reference mismatches',pd.DataFrame(labels)[lambda x:~x.matches_compile_reference][['source','trial_id','result','reference','message']].to_string(index=False))
(W/'compile_cache.json').write_text(json.dumps(jobs,indent=2))
