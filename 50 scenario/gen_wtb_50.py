# 50 WildToolBench-style MULTI-TURN tool-use scenarios over the WO table (arXiv 2604.06185).
# Each is a realistic analyst<->agent dialogue exercising the 3 WTB challenges:
#   TOPOLOGY: tool calls form S (sequential), P (parallel), or S+P (mixed) trees
#   INTENT  : implicit intent spread across turns (coreference / long-range / partial)
#   TRANSITION: user mixes task / follow-up / clarify / chat, switching policy on the fly
# Agent toolbox over work_orders.csv (text only):
#   search(filter)->wo_ids | extract(wo_ids)->{activity,object_class,fault} | count(filter)->n
#   group_count(by)->dist | rank(by,n)->top-n | get_text(wo_id)->str | compare(A,B)->diff
# turn tag legend: [task] [follow] [clarify] [chat]
S=[]
def add(sid,title,turns,topo,intent,transition,gold,trap):
    S.append(dict(id=sid,title=title,turns=turns,topo=topo,intent=intent,transition=transition,gold=gold,trap=trap))

add("WTB01","Replace vs repair, then drill in",
 [("U","[task]","How many of our jobs are replacements versus repairs?"),
  ("U","[follow]","Ok, and of the replacements, which equipment shows up most?"),
  ("U","[clarify]","Wait — does 'change out' count as a replacement here?"),
  ("U","[follow]","Right, with that in mind give me the top three.")],
 "P then S","coreference ('the replacements'), long-range to turn-1 set","clarify mid-stream then resume",
 "P: count(Replace)||count(Repair); S: filter Replace -> group_count(object_class) -> rank3","agent re-runs everything or forgets the 'change out' clarification when ranking")
add("WTB02","Leaks chat interlude",
 [("U","[task]","Pull everything about leaks for me."),
  ("U","[chat]","Cheers. Long week. Anyway —"),
  ("U","[follow]","of those, how many did we just seal versus replace?"),
  ("U","[follow]","and which one's the worst offender?")],
 "S","coreference ('those','the worst') back to leak set","casual chat between tasks",
 "S: search(leak)->set; on SET: count(seal)||count(replace); rank(object_class)","agent re-searches leaks each turn instead of reusing the set; ignores chat and loses thread")
add("WTB03","Two components in parallel",
 [("U","[task]","Compare bearings and seals for me — how often each fails and what we do."),
  ("U","[follow]","Which of the two is more of a problem?"),
  ("U","[chat]","Makes sense, those seals are rubbish."),
  ("U","[follow]","Add belts into that comparison too.")],
 "P (then expand)","long-range: extend the same comparison frame","chat acknowledgement then expand",
 "P: extract(bearing)||extract(seal); compare; later P add belt -> 3-way","agent does sequential one-by-one (suboptimal path) or drops the original two when adding belts")
add("WTB04","Vague then precise",
 [("U","[task]","What's our biggest reliability headache?"),
  ("U","[clarify]","by that I mean which component fails the most, not cost."),
  ("U","[follow]","ok now show me what we usually do about it.")],
 "S","coreference ('it'=the resolved top component)","clarify the metric mid-task",
 "S: rank(object_class by fault) -> top; then top_remedy(filter=top)","agent answers before the clarification, or 'it' rebinds to the wrong component")
add("WTB05","Inspection effectiveness, branching follow-ups",
 [("U","[task]","Of our inspections, how many actually find a fault?"),
  ("U","[follow]","Break that by equipment type."),
  ("U","[follow]","Which type is basically wasted inspection?"),
  ("U","[chat]","Thought so.")],
 "S then S","coreference chain ('that' -> the inspection set)","trailing chat, no new task",
 "search(Inspect)->set; count(fault in set); group_count(object_class); rank ascending by yield","agent recomputes inspection set; mis-defines 'wasted' (low yield) as low count")
add("WTB06","Spares list with a detour",
 [("U","[task]","Give me the ten most-replaced components — stocking list."),
  ("U","[chat]","Stores will love that."),
  ("U","[follow]","Of those ten, which ones are because something broke vs routine?"),
  ("U","[follow]","Just the broken ones then.")],
 "S+P","long-range: 'those ten' reused twice","chat then two dependent follows",
 "rank10(Replace patient); for those10 P: split failed vs routine; filter failed","agent re-ranks or applies the failed/routine split to ALL components, not the ten")
add("WTB07","Pump deep-dive, identity clarify",
 [("U","[task]","Tell me about our pump problems."),
  ("U","[clarify]","real pumps — go by what the job text says, not the asset tag."),
  ("U","[follow]","what fails on them and how we fix it.")],
 "S","coreference ('them'=text-identified pumps)","clarify to override the misleading asset tag",
 "search(text mentions pump) NOT tag; extract faults+remedies","agent groups by the fabricated PMP tag (wrong) instead of the text")
add("WTB08","Failure-mode pareto, then one slice",
 [("U","[task]","Rank our failure modes, most common first."),
  ("U","[follow]","How many modes make up most of it — say 80%?"),
  ("U","[follow]","Take the top mode and tell me which kit it hits.")],
 "S chain","long-range: top mode feeds the last turn","pure task chain (no chat) but deep dependency",
 "group_count(fault); cumulative-to-80; filter top -> group_count(object_class)","agent loses the 'top mode' referent or recomputes pareto each turn")
add("WTB09","Parallel two-sites mental model (trap)",
 [("U","[task]","Compare failures on the day shift versus night shift."),
  ("U","[clarify]","oh — we don't tag shift, do we? skip that."),
  ("U","[follow]","just give me overall failures by type then.")],
 "P attempted -> S","coreference ('that' dropped)","user self-corrects an impossible ask mid-stream",
 "recognise no shift field -> abstain on shift; pivot to group_count(object_class, fault)","agent fabricates a shift split, or gets stuck instead of pivoting")
add("WTB10","Bearings then 'the same for'",
 [("U","[task]","How many bearing jobs were replacements?"),
  ("U","[follow]","Same for seals."),
  ("U","[follow]","And same for belts. Put all three side by side.")],
 "P (parallel-isable)","partial intent: 'same for X' inherits the metric","terse elliptical follow-ups",
 "P: count(Replace&bearing)||count(Replace&seal)||count(Replace&belt) -> table","agent fails to infer the elided metric, or serialises avoidably (poor Optimal Path)")
add("WTB11","Chat-heavy, buried task",
 [("U","[chat]","Morning! Coffee machine's broken again, ironic for a maintenance team."),
  ("U","[chat]","Anyway."),
  ("U","[task]","Can you find me the most common thing we do to valves?"),
  ("U","[follow]","and is that different from what we do to sensors?")],
 "S then P","coreference ('that'=valve action)","heavy chat preamble then task + compare",
 "top action on ControllingObject; then compare to top action on SensingObject","agent reacts to the coffee-machine chat as a task, or misses the real task")
add("WTB12","Worst offender, evidence, fix",
 [("U","[task]","Who's our worst repeat offender, component-wise?"),
  ("U","[follow]","Show me the evidence — counts and its main failure."),
  ("U","[follow]","Draft what we should change.")],
 "S chain","coreference ('its','that') across 3 turns","task -> evidence -> recommendation",
 "rank(object_class by fault)->top; counts+top fault; recommend","agent's recommendation references a different component than the one ranked")
add("WTB13","Two questions in one breath",
 [("U","[task]","How many leaks do we get, and separately how many cracks — and which is worse?"),
  ("U","[follow]","For the worse one, what's the usual remedy?")],
 "P then S","coreference ('the worse one')","compound single-turn (two asks + a compare)",
 "P: count(leak)||count(crack); pick max; top_remedy(filter=that fault)","agent answers one of the two, or mis-binds 'the worse one'")
add("WTB14","Long-range callback",
 [("U","[task]","Pull the most-replaced component."),
  ("U","[chat]","ok good."),
  ("U","[task]","Now, unrelated — how many inspections did we do total?"),
  ("U","[follow]","Right, and that component from before — do we ever inspect it?")],
 "S, S, S","long-range: 'that component from before' spans 3 turns + a distractor task","topic switch then callback",
 "remember turn-1 component; count(Inspect & that component)","agent forgets the early referent after the unrelated task in between")
add("WTB15","Filter then re-filter",
 [("U","[task]","Show failures on lines and drives — belts, chains, hoses, cables."),
  ("U","[follow]","Narrow to just the ones we replaced."),
  ("U","[follow]","Now just hoses out of those.")],
 "S progressive","coreference: progressive narrowing of one set","successive refinement",
 "search(GuidingObject&fault); filter Replace; filter hose subtype","agent restarts the filter from scratch each time instead of narrowing")
add("WTB16","Clarify the unit of count",
 [("U","[task]","How many replacements did we do?"),
  ("U","[clarify]","do you mean jobs or actual parts? I want distinct parts."),
  ("U","[follow]","ok and how many of those parts are wear items?")],
 "S","coreference ('those parts')","clarify the counting unit",
 "count distinct object_class replaced; then intersect with wear-item set","agent reports WO count not distinct parts; or 'those' rebinds to jobs")
add("WTB17","Parallel compare + casual + extend",
 [("U","[task]","Replace vs repair — which do we lean on for engines?"),
  ("U","[chat]","engines are always drama."),
  ("U","[follow]","what about motors, same question?"),
  ("U","[follow]","combine engines and motors and tell me the overall lean.")],
 "P, P, then aggregate","partial ('same question'), long-range (combine)","chat then parallel extend then merge",
 "P engines:Replace||Repair; P motors; then merge counts","agent treats motors fresh and can't merge with engines for the overall")
add("WTB18","Implicit object",
 [("U","[task]","We change a lot of oil — what's it usually on?"),
  ("U","[follow]","and is that a service or a replacement in our coding?")],
 "S","coreference ('it','that')","short, implicit-object task",
 "find oil-change WOs; infer object; classify activity (Service)","agent treats 'change oil' as Replace, or can't ground 'it'")
add("WTB19","Three-way then pick",
 [("U","[task]","Of failures, how do we respond — replace, repair, or service? give the split."),
  ("U","[follow]","which response dominates?"),
  ("U","[clarify]","and to be clear, only count jobs where something actually failed.")],
 "P then S","coreference ('which dominates')","clarification arrives AFTER the compute (must redo)",
 "P split among FailedState WOs; argmax; re-scope to failed-only if not already","agent computed over all jobs; the late clarify forces a re-scope it skips")
add("WTB20","Casual misdirection",
 [("U","[chat]","Did you catch the game last night?"),
  ("U","[task]","Anyway — most common fault across the whole lot?"),
  ("U","[follow]","and the second most common?"),
  ("U","[chat]","nice, ta.")],
 "S","coreference ('the second')","chat bookends",
 "group_count(fault); take rank1 then rank2","agent engages the game chat as if a task, or recomputes for rank2")
# --- 20 more, denser ---
add("WTB21","Bad actor -> RCA -> abstain boundary",
 [("U","[task]","Find the component we run to failure the most."),
  ("U","[follow]","Why does it keep failing?"),
  ("U","[clarify]","I know root cause isn't in the text — just infer the likely mode.")],
 "S","coreference ('it')","clarify lowers the bar from cause to mode",
 "rank run-to-failure class; report dominant mode (not fabricated cause)","agent invents a root cause instead of the inferable mode")
add("WTB22","Parallel KPIs for a dashboard",
 [("U","[task]","Give me four numbers for a board slide: total jobs, % replacements, % with a fault, top failing component."),
  ("U","[follow]","tighten the last one to a plain-English label.")],
 "P (4-way)","partial: 'the last one'","single compound dashboard ask",
 "P: count||share||share||rank; humanize the component label","agent serialises the 4 (poor path) or mislabels with ontology jargon")
add("WTB23","Refer by position",
 [("U","[task]","Top 5 most-replaced components."),
  ("U","[follow]","what's the third one used for / what is it?"),
  ("U","[follow]","and how often is the fifth a breakdown?")],
 "S, S","coreference by ORDINAL ('third','fifth')","positional reference into a prior list",
 "rank5; index 3 -> describe; index 5 -> failed-share","agent miscounts ordinals or re-ranks, shifting positions")
add("WTB24","Self-correcting user",
 [("U","[task]","How many pump replacements?"),
  ("U","[follow]","actually I meant pump SEAL replacements, not whole pumps."),
  ("U","[follow]","and whole pumps separately for contrast.")],
 "S then P","coreference correction (part vs whole)","user revises intent",
 "count(Replace & InfillingObject on pump) vs count(Replace & pump whole)","agent keeps the whole-pump count after the correction")
add("WTB25","Chat that contains a constraint",
 [("U","[chat]","FYI we don't care about routine servicing, only actual faults."),
  ("U","[task]","With that, what's our most common job?"),
  ("U","[follow]","by equipment type now.")],
 "S","long-range: the 'only faults' constraint set in a chat turn","constraint hidden in casual aside",
 "apply fault-only filter from the chat turn; top (activity,object); then group","agent ignores the chat-stated constraint and counts routine work")
add("WTB26","Two sets, then their overlap",
 [("U","[task]","Find jobs that mention a failed state."),
  ("U","[task]","Separately, find jobs that mention a replacement."),
  ("U","[follow]","how many are in both — reactive replacements?")],
 "P then S","coreference ('both')","two parallel tasks then an intersection",
 "P: setA=failed; setB=replace; |A∩B|","agent recomputes or counts union/either instead of intersection")
add("WTB27","Escalating specificity with chat",
 [("U","[task]","Anything on cooling systems?"),
  ("U","[chat]","summer's coming, want to get ahead of it."),
  ("U","[follow]","of those, which had an actual failure?"),
  ("U","[follow]","and what did we do for those?")],
 "S chain","coreference ('those' twice, narrowing)","motivational chat mid-thread",
 "search(cooling); filter failed; extract remedies","agent loses the cooling scope after the chat turn")
add("WTB28","Compare remedies across two faults",
 [("U","[task]","For leaks, what do we do? For cracks, what do we do?"),
  ("U","[follow]","where do they differ most?")],
 "P then compare","coreference ('they')","two parallel asks then a diff",
 "P: remedy_dist(leak)||remedy_dist(crack); compare()","agent reports both but never computes the difference asked")
add("WTB29","Long horizon with a casual derail",
 [("U","[task]","Walk the whole set and give me the top 3 job signatures (object+fault+fix)."),
  ("U","[chat]","this is gold for standard work."),
  ("U","[follow]","take #1 and tell me how many variants it's written as.")],
 "S (heavy) then S","coreference ('#1')","derail then drill into result 1",
 "rank3 signatures; for #1 count surface variants","agent re-derives signatures or picks a different one to drill")
add("WTB30","Ambiguous 'it' resolved by context",
 [("U","[task]","Bearings — replace or repair, mostly?"),
  ("U","[follow]","and is it the same story for the housings they sit in?")],
 "S then P","coreference ('it'=the replace/repair pattern; 'they'=bearings)","analogical follow-up",
 "bearing replace vs repair; then same metric on enclosing/housing class","agent mis-resolves 'they/it' or changes the metric")
add("WTB31","Counting with a moving filter",
 [("U","[task]","How many faults total?"),
  ("U","[follow]","now only the ones on protective gear."),
  ("U","[follow]","now only those we replaced.")],
 "S progressive","coreference (progressive AND filters)","stacking filters across turns",
 "count(fault); +ProtectingObject; +Replace","agent treats each turn as independent (loses the stack)")
add("WTB32","Parallel then conditional branch",
 [("U","[task]","What share of replacements are breakdown-driven?"),
  ("U","[follow]","if it's over a third, show me the worst component; if not, just say it's fine.")],
 "S then Selection","coreference ('it'=the share)","embedded conditional in a follow-up",
 "compute share; branch: if>33% rank worst else 'fine'","agent always shows the component (ignores the condition) or mis-evaluates it")
add("WTB33","Re-scope after a wrong assumption",
 [("U","[task]","Which asset fails most?"),
  ("U","[clarify]","oh the tags are junk — do it by equipment type from the text instead."),
  ("U","[follow]","good, now its top failure mode.")],
 "S","coreference ('its')","clarify forces a representation change (asset->class)",
 "pivot from tag to text-derived object_class; rank; top mode","agent persists with the misleading asset tag")
add("WTB34","Terse expert",
 [("U","[task]","replace counts by class, desc."),
  ("U","[follow]","top3 only."),
  ("U","[follow]","#2's fault mix.")],
 "S","coreference (ordinal '#2')","extremely terse, elliptical",
 "rank replace by class; top3; for #2 group_count(fault)","agent misreads terse commands or wrong ordinal")
add("WTB35","Two metrics, pick by user value",
 [("U","[task]","Most-failing component — give me both raw count and failure variety."),
  ("U","[clarify]","I care more about variety, that's the messy one."),
  ("U","[follow]","so which is it, and what are its modes?")],
 "P then S","coreference ('the messy one','its')","user re-weights the metric",
 "P: rank by count || rank by distinct-modes; pick variety winner; list modes","agent answers by count (the obvious) not the variety metric the user chose")
add("WTB36","Inspection -> fix chain, with aside",
 [("U","[task]","How often do we inspect then fix in the same job?"),
  ("U","[chat]","that's the good kind of job."),
  ("U","[follow]","on what equipment does that happen most?")],
 "S then S","coreference ('that')","approving aside",
 "count(Inspect & remedy same WO); group_count(object_class) on that set","agent counts inspect-only or any-remedy, not the conjunction")
add("WTB37","Compare and then combine differently",
 [("U","[task]","Reactive vs proactive split overall."),
  ("U","[follow]","now per equipment type."),
  ("U","[follow]","which type is most reactive?")],
 "S then S","coreference (the per-type table feeds 'which')","progressive granularity",
 "overall split; group by class; argmax reactive share","agent recomputes or ranks by raw reactive count not share")
add("WTB38","Distractor numbers",
 [("U","[task]","How many jobs mention a number like a quantity?"),
  ("U","[clarify]","I mean the masked <num> placeholders, those carry no info."),
  ("U","[follow]","what fraction of all jobs is that?")],
 "S","coreference ('that')","clarify what 'number' means (data-quality angle)",
 "count(<num> token); /total","agent counts digits in text or miscounts the placeholder")
add("WTB39","Multi-component stocking plan",
 [("U","[task]","Top wear items by replacement: bearings, seals, belts, filters — counts."),
  ("U","[follow]","which are unplanned (failure) demand vs plannable?"),
  ("U","[follow]","just the unplanned ones, ranked.")],
 "P then S","coreference ('the unplanned ones')","parallel then split then filter",
 "P counts 4 items; split failed vs routine; filter+rank failed","agent loses the 4-item scope or mixes planned into the final rank")
add("WTB40","User changes the question after seeing data",
 [("U","[task]","Show the failure-mode pareto."),
  ("U","[follow]","hmm, actually forget modes — redo it for components."),
  ("U","[follow]","top one, and is it mostly outright failure?")],
 "S","coreference ('it'); intent pivot mode->component","user pivots dimension after seeing results",
 "rank components by fault; top; failed-share","agent stays on modes or carries stale numbers")
add("WTB41","Parallel sanity check",
 [("U","[task]","Give me replacements by class, and also class totals by activity."),
  ("U","[follow]","do the replacement totals reconcile across the two?")],
 "P then verify","coreference ('the two')","compute-two-then-cross-check",
 "P: by-object replace || by-activity; assert totals equal","agent doesn't actually cross-check, just restates both")
add("WTB42","Chat reveals scope",
 [("U","[chat]","We're only responsible for the mobile fleet, not fixed plant."),
  ("U","[task]","With that, what's our most-replaced component?"),
  ("U","[clarify]","though honestly we can't split mobile vs fixed from this data, can we?")],
 "S","long-range scope in chat; then user flags it's unsplittable","constraint then self-doubt",
 "acknowledge no mobile/fixed field; answer overall + caveat","agent fabricates a mobile-only subset")
add("WTB43","Stacked superlatives",
 [("U","[task]","Worst component."),
  ("U","[follow]","its worst fault."),
  ("U","[follow]","the worst (most-skewed) fix for that fault.")],
 "S chain","coreference chain ('its','that') 3 deep","nested superlatives",
 "rank component; its top fault; most-skewed remedy for that fault","agent's chain drifts — final fix not tied to the resolved component/fault")
add("WTB44","Two unrelated tasks then a join",
 [("U","[task]","Count diagnose-only jobs."),
  ("U","[task]","Count replace jobs with no diagnosis."),
  ("U","[follow]","what does the gap between those say about our RCA habit?")],
 "P then synthesise","coreference ('those','the gap')","two tasks then an interpretive follow",
 "P: count(Diagnose-only)||count(Replace&!Diagnose); interpret","agent gives raw numbers, never interprets the requested gap")
add("WTB45","Resolve 'the usual' from data",
 [("U","[task]","What's the usual fix when a sensor plays up?"),
  ("U","[follow]","and when it's fully failed, does that change?")],
 "S then S","coreference ('that change'=the remedy)","'usual' = modal remedy",
 "modal remedy on SensingObject faults; then condition on FailedState","agent reports a non-modal fix, or ignores the failed-state condition")
add("WTB46","Parallel across three faults + pick",
 [("U","[task]","For seized, leaking, and cracked — what's the dominant remedy each?"),
  ("U","[follow]","which fault is the most 'just replace it' one?")],
 "P then argmax","coreference ('which fault')","3 parallel then a selection by replace-share",
 "P: remedy_dist for 3 faults; argmax replace-share","agent picks by raw replace count not share, or drops one fault")
add("WTB47","Long callback after detour",
 [("U","[task]","Most common job on valves?"),
  ("U","[chat]","valves everywhere in this plant."),
  ("U","[task]","Different thing: how many jobs have no object recorded?"),
  ("U","[follow]","and back to valves — what's the second most common job there?")],
 "S, S, S","long-range callback to valves across a detour task","topic switch and return",
 "valve top job (remember); DQ count; valve 2nd job","agent loses valve context or recomputes valve set after detour")
add("WTB48","Conditional on data availability",
 [("U","[task]","Trend our failures over time."),
  ("U","[clarify]","if there's no date field, just give me the static failure-mode breakdown instead."),
  ("U","[follow]","and flag the top mode.")],
 "Selection then S","coreference ('the top mode')","user pre-authorises a fallback branch",
 "detect no dates -> fallback: group_count(fault); flag rank1","agent stalls on the impossible trend instead of taking the offered fallback")
add("WTB49","Build then critique own answer",
 [("U","[task]","Give me a one-line reliability headline from the data."),
  ("U","[follow]","now poke holes in it — what's the weakest assumption?"),
  ("U","[chat]","fair.")],
 "S then reflect","coreference ('it'=the headline)","self-critique follow-up",
 "compose headline (top class+mode+reactive%); state its caveat (no time/cost/asset)","agent gives a second headline instead of critiquing the first")
add("WTB50","Everything, prioritised, your call",
 [("U","[task]","Scan the lot. Tell me the single most important reliability action."),
  ("U","[clarify]","'important' = biggest failure burden, since we've no cost data."),
  ("U","[follow]","name the component, the evidence, and the one task you'd add.")],
 "S (long-horizon)","coreference ('it'); clarify defines the metric","open mandate then metric clarify then structured output",
 "rank by fault*failed-share; pick; counts as evidence; recommend one task","agent gives a vague theme, or recommends for a component other than the ranked one")

import csv
with open("MaintIE_50_WildToolBench_Scenarios.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["id","title","num_turns","topology","intent_mechanism","instruction_transition","gold_orchestration","weak_agent_trap"])
    for s in S:
        w.writerow([s["id"],s["title"],len(s["turns"]),s["topo"],s["intent"],s["transition"],s["gold"],s["trap"]])
with open("MaintIE_50_WildToolBench_Scenarios.md","w") as f:
    f.write("# 50 WildToolBench-style Multi-Turn Tool-Use Scenarios (WTB01-WTB50)\n\n")
    f.write("**Source.** WildToolBench (ICLR 2026, arXiv 2604.06185): the real challenge isn't artificial complexity "
            "but *simple, realistic user behaviour* — compositionality, vagueness, variability. No model scored >15%. "
            "Three challenges exercised here: **(1) tool-call topology** (S sequential / P parallel / S+P mixed) — "
            "scored by Optimal Path Rate; **(2) implicit intent spread across turns** (coreference / long-range / "
            "elliptical 'same for X'); **(3) instruction transition** — user mixes task / follow-up / clarify / chat.\n\n")
    f.write("**Agent toolbox over `work_orders.csv` (text only):** `search(filter)`, `extract(wo_ids)`, `count(filter)`, "
            "`group_count(by)`, `rank(by,n)`, `get_text(wo_id)`, `compare(A,B)`. The underlying analytics are all "
            "answerable from the IE graph (verifiable like the prior sets); the difficulty is *orchestration + "
            "intent-tracking + policy-switching*, not the final number.\n\n")
    f.write("Turn tags: `[task]` `[follow]` `[clarify]` `[chat]`.\n\n---\n\n")
    for s in S:
        f.write(f"## {s['id']} — {s['title']}\n")
        f.write(f"*Topology:* {s['topo']}  ·  *Intent:* {s['intent']}  ·  *Transition:* {s['transition']}\n\n")
        for who,tag,txt in s["turns"]:
            f.write(f"- **{tag}** {txt}\n")
        f.write(f"\n*Gold orchestration:* {s['gold']}\n\n")
        f.write(f"*Weak-agent trap:* {s['trap']}\n\n---\n\n")
    f.write("## Sources\n- WildToolBench, ICLR 2026: https://arxiv.org/abs/2604.06185 · https://github.com/yupeijei1997/WildToolBench\n")
from collections import Counter
print("wrote",len(S),"scenarios")
print("topology mix:",dict(Counter(s["topo"] for s in S)))
print("avg turns:",round(sum(len(s['turns']) for s in S)/len(S),1))
