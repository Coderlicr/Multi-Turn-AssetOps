#!/usr/bin/env python3
"""
Ground truth + scoring for the 50 WildToolBench multi-turn WO scenarios (WTB01-WTB50).
For each scenario we define gold(D) -> ordered list of TURNS. Each turn has:
  type   : task | follow | clarify | chat
  intent : the RESOLVED intent (what the vague turn actually means in context)
  reasoning_plan : conceptual computation sketch. This may contain local operations
                   that are not MCP tools. Formal OPR tool paths are attached by
                   eval/wtb_tool_policy.py and contain only real MaintIE tools.
  result : the computed gold value from the IE graph (None for chat/clarify)
  judge  : True if the turn also needs an LLM-judged narrative on top of the numbers.

Scoring (WildToolBench metrics):
  Accomplish Progress Rate (APR) = fraction of compute-turns whose result matches gold.
  Optimal Path Rate (OPR)        = fraction of turns whose tool plan matches gold
                                   (correct parallelism, correct sequence, no redundant calls,
                                    and NO tool call on chat/clarify turns).
Run: python3 wtb_ground_truth.py gold_release.json
"""
from maintie_verify_150 import *      # helpers, constants, load, ocls, fleaves, aprez, ...
import json, sys, collections
Cnt=collections.Counter
try:
    LAB=json.load(open("class_label_map.json")); H=lambda k: LAB.get(k,{}).get("label",k)
except Exception: H=lambda k:k
def proc(it): return sub(it,UNDES_PROC)
def fail(it): return suf(it,FAILED)
def remedies(it): return [l for l in ["Repair","Replace","Service","Adjust"] if act(it,l)]

# ---- reusable primitives (each ~ one tool call) ----
def cnt(D,p): return C(D,p)
def rank_replace(D,n=10):
    c=Cnt()
    for it in D:
        for h,t in patient_pairs(it):
            if h.endswith("Replace"): c[obj_class(t)]+=1
    return [(H(k),v) for k,v in c.most_common(n)]
def rank_fault(D,n=10):
    c=Cnt()
    for it in D:
        if anyfault(it):
            for oc in set(ocls(it)): c[oc]+=1
    return c.most_common(n)
def faultmodes(D,n=10):
    c=Cnt()
    for it in D:
        for f in fleaves(it): c[f]+=1
    return c.most_common(n)
def remedy_dist(D,pf):
    c=Cnt()
    for it in D:
        if pf(it):
            for r in aprez(it): c[r]+=1
    return dict(c)
def top_class(D,p):
    c=Cnt()
    for it in D:
        if p(it):
            for oc in set(ocls(it)): c[oc]+=1
    return (H(c.most_common(1)[0][0]),c.most_common(1)[0][1]) if c else (None,0)

# turn builder
def T(typ,intent,reasoning_plan,result=None,judge=False): return dict(type=typ,intent=intent,reasoning_plan=reasoning_plan,result=result,judge=judge)
G={}
def gold(sid):
    def deco(fn): G[sid]=fn; return fn
    return deco

@gold("WTB01")
def _(D):
    rep=cnt(D,lambda it:act(it,"Replace")); rpr=cnt(D,lambda it:act(it,"Repair"))
    top3=rank_replace(D,3)
    return [
     T("task","count replacements & repairs",[["count:Replace","count:Repair"]],{"replace":rep,"repair":rpr}),
     T("follow","of replacements, top object class",[["filter:Replace>group:object>rank:1"]],{"top":rank_replace(D,1)}),
     T("clarify","confirm 'change out'==Replace; no tool",[],None),
     T("follow","top 3 replaced classes (reuse grouping)",[["rank:3"]],{"top3":top3}),
    ]
@gold("WTB02")
def _(D):
    leakset=lambda it: proc(it)
    seal=cnt(D,lambda it: leakset(it) and sub(it,"SupportingActivity/Modify"))
    rep=cnt(D,lambda it: leakset(it) and act(it,"Replace"))
    worst=top_class(D,leakset)
    return [
     T("task","build leak set",[["search:process_fault"]],{"leak_WOs":cnt(D,leakset)}),
     T("chat","acknowledge; no tool",[],None),
     T("follow","on leak set: seal vs replace",[["count:Modify@set","count:Replace@set"]],{"seal":seal,"replace":rep}),
     T("follow","worst object class in leak set",[["rank:1@set"]],{"worst":worst}),
    ]
@gold("WTB03")
def _(D):
    def fx(s): return {"fault":cnt(D,lambda it: sub(it,s) and anyfault(it)),
                       "remedy":remedy_dist(D,lambda it: sub(it,s))}
    return [
     T("task","compare bearings & seals (parallel)",[["extract:bearing","extract:seal"]],{"bearing":fx(BEARING),"seal":fx(SEAL)}),
     T("follow","which of the two worse",[["compare"]],{"worse":"seal" if fx(SEAL)["fault"]>fx(BEARING)["fault"] else "bearing"}),
     T("chat","acknowledge; no tool",[],None),
     T("follow","add belts -> 3-way",[["extract:belt"]],{"belt":fx(BELT)}),
    ]
@gold("WTB04")
def _(D):
    top=top_class(D,anyfault)
    return [
     T("task","ambiguous 'biggest headache' -> await metric or assume fault-count",[["rank:fault_class:1"]],{"top":top},judge=True),
     T("clarify","metric = most-failing component (not cost); no new tool",[],None),
     T("follow","usual remedy for that component",[["filter:top>remedy_dist>argmax"]],{"remedy":max(remedy_dist(D,lambda it: anyfault(it) and H(top[0]) in [H(o) for o in ocls(it)]).items(), key=lambda x:x[1], default=(None,0))[0]}),
    ]
@gold("WTB05")
def _(D):
    insp=lambda it: act(it,"Inspect")
    withf=cnt(D,lambda it: insp(it) and anyfault(it))
    per=collections.defaultdict(lambda:[0,0])
    for it in D:
        if insp(it):
            for oc in set(ocls(it)): per[oc][1]+=1; per[oc][0]+= (1 if anyfault(it) else 0)
    low=sorted([(H(k),round(v[0]/v[1],2)) for k,v in per.items() if v[1]>=3], key=lambda x:x[1])[:3]
    return [
     T("task","inspections that find a fault",[["search:Inspect>count:fault"]],{"inspect_with_fault":withf}),
     T("follow","break by equipment type",[["group:object@set"]],{"by_class":{H(k):v for k,v in sorted(per.items(),key=lambda x:-x[1][1])[:5]}}),
     T("follow","lowest-yield (wasted) type",[["rank_asc:yield"]],{"low_yield":low}),
     T("chat","no tool",[],None),
    ]
@gold("WTB06")
def _(D):
    top10=rank_replace(D,10); names=[k for k,_ in top10]
    brk=Cnt()
    for it in D:
        if act(it,"Replace") and fail(it):
            for oc in set(ocls(it)):
                if H(oc) in names: brk[H(oc)]+=1
    return [
     T("task","top10 most-replaced",[["rank:replace:10"]],{"top10":top10}),
     T("chat","no tool",[],None),
     T("follow","of those10: broken vs routine",[["split:failed@top10"]],{"breakdown_within_top10":dict(brk)}),
     T("follow","just the broken ones",[["filter:failed@top10"]],{"broken":dict(brk)}),
    ]
@gold("WTB07")
def _(D):
    pump=lambda it: "pump" in " ".join(tok(it)).lower()
    return [
     T("task","pump problems (vague)",[["search:pump_text"]],{"pump_text_WOs":cnt(D,pump)},judge=True),
     T("clarify","use text not asset tag; no tool",[],None),
     T("follow","faults & remedies on text-pumps",[["extract@set"]],{"remedies":remedy_dist(D,pump),"top_fault":(faultmodes_for(D,pump))}),
    ]
def faultmodes_for(D,p):
    c=Cnt()
    for it in D:
        if p(it):
            for f in fleaves(it): c[f]+=1
    return H(c.most_common(1)[0][0]) if c else None
@gold("WTB08")
def _(D):
    modes=faultmodes(D,99); tot=sum(v for _,v in modes); cum=0;k=0
    for _,v in modes:
        cum+=v;k+=1
        if cum>=0.8*tot: break
    topmode=modes[0][0]
    hit=top_class(D,lambda it: topmode in fleaves(it))
    return [
     T("task","failure-mode pareto",[["group:fault>rank"]],{"pareto":[(H(m),v) for m,v in modes[:5]]}),
     T("follow","modes for 80%",[["cumsum"]],{"modes_for_80pct":k}),
     T("follow","top mode -> which kit",[["filter:topmode>group:object>rank:1"]],{"top_mode":H(topmode),"top_kit":hit}),
    ]
@gold("WTB09")
def _(D):
    return [
     T("task","shift comparison (will fail: no shift field)",[["attempt:group:shift"]],{"shift_field":"absent"},judge=True),
     T("clarify","user drops shift; no tool",[],None),
     T("follow","pivot: failures by type",[["group:object,fault"]],{"by_class":rank_fault(D,5)}),
    ]
@gold("WTB10")
def _(D):
    b=cnt(D,lambda it:act(it,"Replace") and sub(it,BEARING))
    s=cnt(D,lambda it:act(it,"Replace") and sub(it,SEAL))
    be=cnt(D,lambda it:act(it,"Replace") and sub(it,BELT))
    return [
     T("task","bearing replacements",[["count:Replace&bearing"]],{"bearing":b}),
     T("follow","same for seals (elliptical)",[["count:Replace&seal"]],{"seal":s}),
     T("follow","same for belts; table all 3 (parallelisable)",[["count:Replace&belt"]],{"belt":be,"table":{"bearing":b,"seal":s,"belt":be}}),
    ]
@gold("WTB11")
def _(D):
    va=remedy_dist(D,lambda it: sub(it,"ControllingObject"))
    se=remedy_dist(D,lambda it: sub(it,SENSOR))
    return [
     T("chat","coffee-machine banter; no tool",[],None),
     T("chat","'anyway'; no tool",[],None),
     T("task","most common action on valves",[["filter:ControllingObject>remedy>argmax"]],{"valve_top":max(va.items(),key=lambda x:x[1],default=(None,0))[0]}),
     T("follow","different from sensors?",[["filter:Sensor>remedy>argmax"]],{"sensor_top":max(se.items(),key=lambda x:x[1],default=(None,0))[0]}),
    ]
@gold("WTB12")
def _(D):
    top=top_class(D,anyfault); fm=faultmodes_for(D,lambda it: anyfault(it) and H(top[0]) in [H(o) for o in ocls(it)])
    return [
     T("task","worst repeat offender",[["rank:fault_class:1"]],{"worst":top}),
     T("follow","evidence: counts+main fault",[["filter:top>count","filter:top>group:fault>rank:1"]],{"count":top[1],"main_fault":fm}),
     T("follow","draft change (narrative)",[["compose"]],{"target":top[0],"basis":fm},judge=True),
    ]
@gold("WTB13")
def _(D):
    leak=cnt(D,proc); crack=cnt(D,lambda it: sub(it,UNDES_PROP))
    worse="leak" if leak>=crack else "crack"
    pf = proc if worse=="leak" else (lambda it: sub(it,UNDES_PROP))
    return [
     T("task","count leaks & cracks; which worse",[["count:leak","count:crack"]],{"leak":leak,"crack":crack,"worse":worse}),
     T("follow","usual remedy for the worse one",[["filter:worse>remedy>argmax"]],{"remedy":max(remedy_dist(D,pf).items(),key=lambda x:x[1],default=(None,0))[0]}),
    ]
@gold("WTB14")
def _(D):
    toprep=rank_replace(D,1)[0][0]
    insp=cnt(D,lambda it: act(it,"Inspect") and H_in(toprep,it))
    return [
     T("task","most-replaced component",[["rank:replace:1"]],{"top":toprep}),
     T("chat","no tool",[],None),
     T("task","total inspections (distractor)",[["count:Inspect"]],{"inspections":cnt(D,lambda it:act(it,"Inspect"))}),
     T("follow","callback: do we inspect THAT component?",[["count:Inspect&topcomp"]],{"inspect_top_component":insp}),
    ]
def H_in(label,it): return label in [H(o) for o in ocls(it)]
@gold("WTB15")
def _(D):
    base=lambda it: sub(it,"GuidingObject") and anyfault(it)
    rep=lambda it: base(it) and act(it,"Replace")
    hose=lambda it: rep(it) and sub(it,HOSE)
    return [
     T("task","failures on lines & drives",[["search:GuidingObject&fault"]],{"n":cnt(D,base)}),
     T("follow","narrow to replaced",[["filter:Replace@set"]],{"n":cnt(D,rep)}),
     T("follow","narrow to hoses",[["filter:hose@set"]],{"n":cnt(D,hose)}),
    ]
@gold("WTB16")
def _(D):
    distinct=len({obj_class(t) for it in D for h,t in patient_pairs(it) if h.endswith("Replace")})
    wear={"JointingObject","InfillingObject","MechanicalEnergyGuidingObject","MechanicalSeparatingObject"}
    wparts=len({obj_class(t) for it in D for h,t in patient_pairs(it) if h.endswith("Replace") and obj_class(t) in wear})
    return [
     T("task","how many replacements",[["count:Replace"]],{"replace_jobs":cnt(D,lambda it:act(it,"Replace"))}),
     T("clarify","unit = distinct parts; recompute",[["distinct:object@Replace"]],{"distinct_parts":distinct}),
     T("follow","of those, wear items",[["intersect:wear"]],{"wear_parts":wparts}),
    ]
@gold("WTB17")
def _(D):
    eR=cnt(D,lambda it: is_engine(it) and act(it,"Replace")); eP=cnt(D,lambda it: is_engine(it) and act(it,"Repair"))
    mR=cnt(D,lambda it: is_motor(it) and act(it,"Replace")); mP=cnt(D,lambda it: is_motor(it) and act(it,"Repair"))
    return [
     T("task","engines: replace vs repair",[["count:eR","count:eP"]],{"engine":{"replace":eR,"repair":eP}}),
     T("chat","no tool",[],None),
     T("follow","motors: same",[["count:mR","count:mP"]],{"motor":{"replace":mR,"repair":mP}}),
     T("follow","combine -> overall lean",[["merge"]],{"overall":{"replace":eR+mR,"repair":eP+mP,"lean":"replace" if eR+mR>=eP+mP else "repair"}}),
    ]
@gold("WTB18")
def _(D):
    oil=lambda it: "oil" in " ".join(tok(it)).lower()
    return [
     T("task","oil changes - what's it on",[["search:oil>infer_object"]],{"oil_WOs":cnt(D,oil)},judge=True),
     T("follow","service or replacement in our coding",[["classify_activity@set"]],{"service":cnt(D,lambda it: oil(it) and act(it,"Service")),"replace":cnt(D,lambda it: oil(it) and act(it,"Replace"))}),
    ]
@gold("WTB19")
def _(D):
    pf=fail
    d=remedy_dist(D,pf)
    return [
     T("task","of failures: replace/repair/service split",[["filter:failed>split3"]],{"split":{k:d.get(k,0) for k in ["Replace","Repair","Service"]}}),
     T("follow","which dominates",[["argmax"]],{"dominant":max(["Replace","Repair","Service"],key=lambda k:d.get(k,0))}),
     T("clarify","ensure failed-only scope (re-scope if needed); no NEW tool if already scoped",[],None),
    ]
@gold("WTB20")
def _(D):
    fm=faultmodes(D,3)
    return [
     T("chat","game banter; no tool",[],None),
     T("task","most common fault overall",[["group:fault>rank:1"]],{"top1":(H(fm[0][0]),fm[0][1])}),
     T("follow","second most common",[["index:2"]],{"top2":(H(fm[1][0]),fm[1][1])}),
     T("chat","no tool",[],None),
    ]
# ---- WTB21-50 (compact) ----
def _rtf(D):
    c=Cnt()
    for it in D:
        if fail(it) and (act(it,"Replace") or act(it,"Repair")) and not act(it,"Inspect"):
            for oc in set(ocls(it)): c[oc]+=1
    return (H(c.most_common(1)[0][0]),c.most_common(1)[0][1]) if c else (None,0)
@gold("WTB21")
def _(D):
    top=_rtf(D); fm=faultmodes_for(D,lambda it: H_in(top[0],it) and anyfault(it))
    return [T("task","run-to-failure component",[["rank:rtf:1"]],{"top":top}),
            T("follow","why it fails (infer mode, not cause)",[["filter:top>group:fault>rank:1"]],{"likely_mode":fm}),
            T("clarify","mode not cause; no tool",[],None)]
@gold("WTB22")
def _(D):
    n=len(D); rep=cnt(D,lambda it:act(it,"Replace")); flt=cnt(D,anyfault); top=top_class(D,anyfault)
    return [T("task","4 dashboard numbers (parallel)",[["count:all","share:replace","share:fault","rank:fault:1"]],
              {"total":n,"replace_pct":round(100*rep/n,1),"fault_pct":round(100*flt/n,1),"top_component":top[0]}),
            T("follow","plain label for last one",[["humanize"]],{"top_component_label":top[0]})]
@gold("WTB23")
def _(D):
    t5=rank_replace(D,5)
    fifth_fail=0
    if len(t5)>=5:
        name=t5[4][0]
        fifth_fail=cnt(D,lambda it: act(it,"Replace") and fail(it) and H_in(name,it))
    return [T("task","top5 most-replaced",[["rank:replace:5"]],{"top5":t5}),
            T("follow","what's the 3rd",[["index:3"]],{"third":t5[2][0] if len(t5)>=3 else None}),
            T("follow","how often is the 5th a breakdown",[["filter:5th&failed>count"]],{"fifth":t5[4][0] if len(t5)>=5 else None,"breakdown":fifth_fail})]
@gold("WTB24")
def _(D):
    seal=cnt(D,lambda it: act(it,"Replace") and sub(it,SEAL))
    whole=cnt(D,lambda it: act(it,"Replace") and sub(it,PUMP))
    return [T("task","pump replacements",[["count:Replace&pump"]],{"whole_pump":whole}),
            T("follow","correction: pump SEAL replacements",[["count:Replace&seal"]],{"pump_seal":seal}),
            T("follow","whole pumps separately",[["count:Replace&pump"]],{"whole_pump":whole})]
@gold("WTB25")
def _(D):
    pf=anyfault
    c=Cnt()
    for it in D:
        if pf(it):
            for a in aprez(it):
                for oc in set(ocls(it)): c[(a,H(oc))]+=1
    top=c.most_common(1)[0] if c else None
    return [T("chat","constraint set: faults only; no tool",[],None),
            T("task","most common job (faults only)",[["filter:fault>top(activity,object)"]],{"top_job":top}),
            T("follow","by equipment type",[["group:object@fault"]],{"by_class":rank_fault(D,5)})]
@gold("WTB26")
def _(D):
    A=cnt(D,fail); B=cnt(D,lambda it:act(it,"Replace")); both=cnt(D,lambda it: fail(it) and act(it,"Replace"))
    return [T("task","set A: failed",[["search:failed"]],{"A":A}),
            T("task","set B: replace",[["search:replace"]],{"B":B}),
            T("follow","intersection (reactive replacements)",[["intersect:A,B"]],{"both":both})]
@gold("WTB27")
def _(D):
    cool=lambda it: "cooling" in " ".join(tok(it)).lower()
    return [T("task","anything on cooling",[["search:cooling"]],{"n":cnt(D,cool)}),
            T("chat","no tool",[],None),
            T("follow","of those, failed",[["filter:failed@set"]],{"failed":cnt(D,lambda it: cool(it) and fail(it))}),
            T("follow","remedies for those",[["remedy_dist@set"]],{"remedies":remedy_dist(D,lambda it: cool(it) and fail(it))})]
@gold("WTB28")
def _(D):
    lk=remedy_dist(D,proc); ck=remedy_dist(D,lambda it: sub(it,UNDES_PROP))
    diff={k:lk.get(k,0)-ck.get(k,0) for k in set(lk)|set(ck)}
    return [T("task","leak remedies & crack remedies (parallel)",[["remedy:leak","remedy:crack"]],{"leak":lk,"crack":ck}),
            T("follow","where differ most",[["compare"]],{"max_diff_action":max(diff,key=lambda k:abs(diff[k])) if diff else None})]
@gold("WTB29")
def _(D):
    sig=Cnt()
    for it in D:
        for oc in set(ocls(it)):
            for f in (fleaves(it) or ["(none)"]):
                for a in (aprez(it) or ["(none)"]): sig[(H(oc),H(f),a)]+=1
    top3=sig.most_common(3)
    return [T("task","top3 job signatures",[["scan>group:(obj,fault,act)>rank:3"]],{"top3":top3}),
            T("chat","no tool",[],None),
            T("follow","#1 variant count",[["count_variants:#1"]],{"sig1":top3[0][0] if top3 else None},judge=True)]
@gold("WTB30")
def _(D):
    bR=cnt(D,lambda it: sub(it,BEARING) and act(it,"Replace")); bP=cnt(D,lambda it: sub(it,BEARING) and act(it,"Repair"))
    hR=cnt(D,lambda it: sub(it,"EnclosingObject") and act(it,"Replace")); hP=cnt(D,lambda it: sub(it,"EnclosingObject") and act(it,"Repair"))
    return [T("task","bearings replace vs repair",[["count:bR","count:bP"]],{"bearing":{"replace":bR,"repair":bP}}),
            T("follow","same for housings",[["count:hR","count:hP"]],{"housing":{"replace":hR,"repair":hP}})]
@gold("WTB31")
def _(D):
    a=cnt(D,anyfault); b=cnt(D,lambda it: anyfault(it) and sub(it,"ProtectingObject"))
    c=cnt(D,lambda it: anyfault(it) and sub(it,"ProtectingObject") and act(it,"Replace"))
    return [T("task","total faults",[["count:fault"]],{"n":a}),
            T("follow","+protective gear",[["filter:ProtectingObject@set"]],{"n":b}),
            T("follow","+replaced",[["filter:Replace@set"]],{"n":c})]
@gold("WTB32")
def _(D):
    rep=cnt(D,lambda it:act(it,"Replace")); brk=cnt(D,lambda it:act(it,"Replace") and anyfault(it))
    share=round(brk/rep,2) if rep else 0
    worst=top_class(D,lambda it: act(it,"Replace") and anyfault(it))
    return [T("task","breakdown share of replacements",[["count:replace","count:replace&fault>ratio"]],{"share":share}),
            T("follow","branch: if>1/3 worst else 'fine'",[["select"]],{"branch":"worst" if share>1/3 else "fine","worst":worst if share>1/3 else None})]
@gold("WTB33")
def _(D):
    top=top_class(D,anyfault); fm=faultmodes_for(D,lambda it: anyfault(it) and H_in(top[0],it))
    return [T("task","which asset fails most (tags junk)",[["attempt:group:tag"]],{"note":"tags unreliable"},judge=True),
            T("clarify","pivot to text-class",[["group:object_class"]],{"top":top}),
            T("follow","its top mode",[["filter:top>group:fault>rank:1"]],{"top_mode":fm})]
@gold("WTB34")
def _(D):
    r=rank_replace(D,3)
    second=r[1][0] if len(r)>=2 else None
    fm=Cnt()
    for it in D:
        if act(it,"Replace") and H_in(second,it):
            for f in fleaves(it): fm[H(f)]+=1
    return [T("task","replace counts by class desc",[["group:object>rank"]],{"ranked":rank_replace(D,10)}),
            T("follow","top3",[["index:1..3"]],{"top3":r}),
            T("follow","#2 fault mix",[["filter:#2>group:fault"]],{"second":second,"fault_mix":dict(fm)})]
@gold("WTB35")
def _(D):
    byc=rank_fault(D,1);
    var=collections.defaultdict(set)
    for it in D:
        for oc in set(ocls(it)):
            for f in fleaves(it): var[oc].add(f)
    byv=max(var,key=lambda k:len(var[k])) if var else None
    return [T("task","most-failing: count & variety (parallel)",[["rank:count:1","rank:variety:1"]],{"by_count":(H(byc[0][0]),byc[0][1]),"by_variety":(H(byv),len(var[byv]))}),
            T("clarify","choose variety; no tool",[],None),
            T("follow","its modes",[["filter:variety_winner>list:fault"]],{"modes":[H(x) for x in var[byv]]})]
@gold("WTB36")
def _(D):
    p=lambda it: act(it,"Inspect") and (act(it,"Repair") or act(it,"Replace") or act(it,"Adjust"))
    return [T("task","inspect-then-fix same job",[["count:inspect&remedy"]],{"n":cnt(D,p)}),
            T("chat","no tool",[],None),
            T("follow","on what equipment most",[["group:object@set>rank:1"]],{"top":top_class(D,p)})]
@gold("WTB37")
def _(D):
    reac=Cnt(); pro=Cnt()
    for it in D:
        r=fail(it) and (act(it,"Repair") or act(it,"Replace"))
        pp=(act(it,"Inspect") or act(it,"Service") or act(it,"Adjust")) and not anyfault(it)
        for oc in set(ocls(it)):
            if r: reac[oc]+=1
            if pp: pro[oc]+=1
    rows=[(H(oc),round(reac[oc]/(reac[oc]+pro[oc]),2)) for oc in set(list(reac)+list(pro)) if reac[oc]+pro[oc]>=3]
    worst=max(rows,key=lambda x:x[1]) if rows else None
    return [T("task","overall reactive vs proactive",[["count:reactive","count:proactive"]],{"reactive":sum(reac.values()),"proactive":sum(pro.values())}),
            T("follow","per equipment type",[["group:object"]],{"per_class":sorted(rows,key=lambda x:-x[1])[:5]}),
            T("follow","most reactive type",[["argmax:share"]],{"most_reactive":worst})]
@gold("WTB38")
def _(D):
    nph=cnt(D,lambda it: any(p in " ".join(tok(it)) for p in ["<num>","<date>"]))
    return [T("task","jobs mentioning a number",[["search:number"]],{"raw":"ambiguous"},judge=True),
            T("clarify","mean <num> placeholders; no tool",[],None),
            T("follow","fraction of all",[["count:placeholder>ratio"]],{"placeholder_WOs":nph,"pct":round(100*nph/len(D),1)})]
@gold("WTB39")
def _(D):
    items={"bearing":BEARING,"seal":SEAL,"belt":BELT,"filter":FILTER}
    counts={n:cnt(D,lambda it,s=s: act(it,"Replace") and sub(it,s)) for n,s in items.items()}
    unp={n:cnt(D,lambda it,s=s: act(it,"Replace") and sub(it,s) and anyfault(it)) for n,s in items.items()}
    return [T("task","top wear items by replacement (parallel)",[["count:bearing","count:seal","count:belt","count:filter"]],{"counts":counts}),
            T("follow","unplanned vs plannable",[["split:failed@4"]],{"unplanned":unp}),
            T("follow","unplanned only, ranked",[["rank:unplanned"]],{"ranked":sorted(unp.items(),key=lambda x:-x[1])})]
@gold("WTB40")
def _(D):
    comp=rank_fault(D,1); top=comp[0]
    fs=cnt(D,lambda it: anyfault(it) and H_in(H(top[0]),it) and fail(it))
    return [T("task","failure-mode pareto",[["group:fault>rank"]],{"pareto":[(H(m),v) for m,v in faultmodes(D,5)]}),
            T("follow","pivot: redo for components",[["group:object>rank"]],{"top_component":(H(top[0]),top[1])}),
            T("follow","top one mostly outright failure?",[["filter:top>failed_share"]],{"failed_share":round(fs/top[1],2) if top[1] else 0})]
@gold("WTB41")
def _(D):
    byobj=Cnt(); byact=Cnt()
    for it in D:
        for h,t in patient_pairs(it):
            if h.endswith("Replace"): byobj[obj_class(t)]+=1
            if MAINT in h: byact[h.split("/")[-1]]+=1
    return [T("task","replace by class & class by activity (parallel)",[["group:object","group:activity"]],{"replace_total":sum(byobj.values()),"activity_replace":byact.get("Replace",0)}),
            T("follow","reconcile",[["assert_equal"]],{"reconciles":sum(byobj.values())==byact.get("Replace",0)})]
@gold("WTB42")
def _(D):
    return [T("chat","scope: mobile fleet only; no tool",[],None),
            T("task","most-replaced component (overall; no mobile/fixed field)",[["rank:replace:1"]],{"top":rank_replace(D,1)},judge=True),
            T("clarify","confirm cannot split mobile/fixed; no tool",[],None)]
@gold("WTB43")
def _(D):
    top=top_class(D,anyfault)
    fm=Cnt()
    for it in D:
        if anyfault(it) and H_in(top[0],it):
            for f in fleaves(it): fm[f]+=1
    tf=fm.most_common(1)[0][0] if fm else None
    rem=Cnt()
    for it in D:
        if tf in fleaves(it):
            for r in remedies(it): rem[r]+=1
    skew=max(rem.values())/sum(rem.values()) if rem else 0
    return [T("task","worst component",[["rank:fault_class:1"]],{"worst":top}),
            T("follow","its worst fault",[["filter:top>group:fault>rank:1"]],{"worst_fault":H(tf)}),
            T("follow","most-skewed fix for that fault",[["filter:fault>remedy>argmax_share"]],{"fix":rem.most_common(1)[0][0] if rem else None,"share":round(skew,2)})]
@gold("WTB44")
def _(D):
    a=cnt(D,lambda it: act(it,"Diagnose") and not (act(it,"Replace") or act(it,"Repair")))
    b=cnt(D,lambda it: act(it,"Replace") and not act(it,"Diagnose") and fail(it))
    return [T("task","diagnose-only count",[["count:diagnose_only"]],{"diagnose_only":a}),
            T("task","replace-without-diagnosis count",[["count:replace_no_diag"]],{"replace_no_diag":b}),
            T("follow","interpret the gap (RCA habit)",[["synthesise"]],{"gap":b-a},judge=True)]
@gold("WTB45")
def _(D):
    r1=remedy_dist(D,lambda it: sub(it,SENSOR) and anyfault(it))
    r2=remedy_dist(D,lambda it: sub(it,SENSOR) and fail(it))
    return [T("task","usual fix when a sensor plays up",[["filter:sensor_fault>remedy>argmax"]],{"usual":max(r1.items(),key=lambda x:x[1],default=(None,0))[0]}),
            T("follow","when fully failed, does it change",[["filter:sensor_failed>remedy>argmax"]],{"when_failed":max(r2.items(),key=lambda x:x[1],default=(None,0))[0]})]
@gold("WTB46")
def _(D):
    faults={"seized":lambda it: fail(it),"leaking":proc,"cracked":lambda it: sub(it,UNDES_PROP)}
    dom={k:max(remedy_dist(D,p).items(),key=lambda x:x[1],default=(None,0))[0] for k,p in faults.items()}
    share={k:( (remedy_dist(D,p).get("Replace",0))/ (sum(remedy_dist(D,p).values()) or 1)) for k,p in faults.items()}
    mostrep=max(share,key=share.get)
    return [T("task","dominant remedy for seized/leaking/cracked (parallel)",[["remedy:seized","remedy:leaking","remedy:cracked"]],{"dominant":dom}),
            T("follow","most 'just replace it' fault",[["argmax:replace_share"]],{"most_replace":mostrep,"share":round(share[mostrep],2)})]
@gold("WTB47")
def _(D):
    va=Cnt()
    for it in D:
        if sub(it,"ControllingObject"):
            for a in aprez(it): va[a]+=1
    top2=va.most_common(2)
    noobj=cnt(D,lambda it: not any(t.startswith("PhysicalObject") for t in tps(it)))
    return [T("task","most common job on valves",[["filter:valve>activity>rank:1"]],{"valve_top":top2[0][0] if top2 else None}),
            T("chat","no tool",[],None),
            T("task","jobs with no object (distractor)",[["count:no_object"]],{"no_object":noobj}),
            T("follow","back to valves: 2nd most common",[["index:2@valve"]],{"valve_second":top2[1][0] if len(top2)>=2 else None})]
@gold("WTB48")
def _(D):
    fm=faultmodes(D,5)
    return [T("task","trend over time (no date field)",[["attempt:trend"]],{"date_field":"absent"},judge=True),
            T("clarify","fallback authorised: static breakdown; no tool",[],None),
            T("follow","static failure-mode breakdown + flag top",[["group:fault>rank>flag:1"]],{"breakdown":[(H(m),v) for m,v in fm],"top":H(fm[0][0])})]
@gold("WTB49")
def _(D):
    top=top_class(D,anyfault); mode=faultmodes(D,1)[0]
    rep=cnt(D,lambda it: fail(it) and (act(it,"Repair") or act(it,"Replace")))
    pro=cnt(D,lambda it: (act(it,"Inspect") or act(it,"Service") or act(it,"Adjust")) and not anyfault(it))
    return [T("task","one-line reliability headline",[["compose:top_class+mode+reactive%"]],
              {"top":top[0],"mode":H(mode[0]),"reactive_pct":round(100*rep/(rep+pro),1) if rep+pro else None},judge=True),
            T("follow","critique its weakest assumption",[["reflect"]],{"caveat":"no time/cost/asset identity in data"},judge=True),
            T("chat","no tool",[],None)]
@gold("WTB50")
def _(D):
    f=Cnt(); fl=Cnt()
    for it in D:
        if anyfault(it):
            for oc in set(ocls(it)):
                f[oc]+=1
                if fail(it): fl[oc]+=1
    best=max(f,key=lambda oc: f[oc]*(fl[oc]/f[oc] if f[oc] else 0))
    return [T("task","single most important action (open)",[["scan"]],{"await_metric":True},judge=True),
            T("clarify","metric=failure burden; no tool",[],None),
            T("follow","component+evidence+one task",[["rank:burden:1>compose"]],{"target":H(best),"fault_WOs":f[best],"failed_share":round(fl[best]/f[best],2)},judge=True)]

if __name__=="__main__":
    path=sys.argv[1] if len(sys.argv)>1 else "/sessions/gifted-awesome-ramanujan/mnt/uploads/gold_release.json"
    D=load(path)
    GT={}
    for sid in sorted(G):
        try: GT[sid]=G[sid](D)
        except Exception as e: GT[sid]=[{"ERROR":str(e)}]
    json.dump(GT, open("wtb_ground_truth.json","w"), indent=2, default=str)
    ok=sum(1 for sid in GT if "ERROR" not in GT[sid][0])
    print(f"computed ground truth for {ok}/{len(G)} scenarios -> wtb_ground_truth.json")
    # Demo formal scoring on WTB01 using only real MaintIE tool paths.
    from pathlib import Path
    repo_root=Path(__file__).resolve().parent.parent
    sys.path.insert(0,str(repo_root))
    from eval.wtb_score import score_dialog
    from eval.wtb_tool_policy import apply_real_tool_policy
    formal_gt=apply_real_tool_policy(GT)
    g=formal_gt["WTB01"]
    perfect=[{"tools":t["tools"],"result":t["result"]} for t in g]
    flawed=[{"tools":[["count"]],"result":g[0]["result"]},   # missing the second parallel count
            {"tools":g[1]["tools"],"result":{"top":[("WRONG",1)]}},   # wrong result
            {"tools":[["count"]],"result":None},                       # called a tool on a clarify turn
            {"tools":g[3]["tools"],"result":g[3]["result"]}]
    print("WTB01 perfect trace ->", score_dialog(perfect,g))
    print("WTB01 flawed  trace ->", score_dialog(flawed,g))
