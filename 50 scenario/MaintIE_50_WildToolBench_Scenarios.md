# 50 WildToolBench-style Multi-Turn Tool-Use Scenarios (WTB01-WTB50)

**Source.** WildToolBench (ICLR 2026, arXiv 2604.06185): the real challenge isn't artificial complexity but *simple, realistic user behaviour* — compositionality, vagueness, variability. No model scored >15%. Three challenges exercised here: **(1) tool-call topology** (S sequential / P parallel / S+P mixed) — scored by Optimal Path Rate; **(2) implicit intent spread across turns** (coreference / long-range / elliptical 'same for X'); **(3) instruction transition** — user mixes task / follow-up / clarify / chat.

**Agent toolbox over `work_orders.csv` (text only):** `search(filter)`, `extract(wo_ids)`, `count(filter)`, `group_count(by)`, `rank(by,n)`, `get_text(wo_id)`, `compare(A,B)`. The underlying analytics are all answerable from the IE graph (verifiable like the prior sets); the difficulty is *orchestration + intent-tracking + policy-switching*, not the final number.

Turn tags: `[task]` `[follow]` `[clarify]` `[chat]`.

---

## WTB01 — Replace vs repair, then drill in
*Topology:* P then S  ·  *Intent:* coreference ('the replacements'), long-range to turn-1 set  ·  *Transition:* clarify mid-stream then resume

- **[task]** How many of our jobs are replacements versus repairs?
- **[follow]** Ok, and of the replacements, which equipment shows up most?
- **[clarify]** Wait — does 'change out' count as a replacement here?
- **[follow]** Right, with that in mind give me the top three.

*Gold orchestration:* P: count(Replace)||count(Repair); S: filter Replace -> group_count(object_class) -> rank3

*Weak-agent trap:* agent re-runs everything or forgets the 'change out' clarification when ranking

---

## WTB02 — Leaks chat interlude
*Topology:* S  ·  *Intent:* coreference ('those','the worst') back to leak set  ·  *Transition:* casual chat between tasks

- **[task]** Pull everything about leaks for me.
- **[chat]** Cheers. Long week. Anyway —
- **[follow]** of those, how many did we just seal versus replace?
- **[follow]** and which one's the worst offender?

*Gold orchestration:* S: search(leak)->set; on SET: count(seal)||count(replace); rank(object_class)

*Weak-agent trap:* agent re-searches leaks each turn instead of reusing the set; ignores chat and loses thread

---

## WTB03 — Two components in parallel
*Topology:* P (then expand)  ·  *Intent:* long-range: extend the same comparison frame  ·  *Transition:* chat acknowledgement then expand

- **[task]** Compare bearings and seals for me — how often each fails and what we do.
- **[follow]** Which of the two is more of a problem?
- **[chat]** Makes sense, those seals are rubbish.
- **[follow]** Add belts into that comparison too.

*Gold orchestration:* P: extract(bearing)||extract(seal); compare; later P add belt -> 3-way

*Weak-agent trap:* agent does sequential one-by-one (suboptimal path) or drops the original two when adding belts

---

## WTB04 — Vague then precise
*Topology:* S  ·  *Intent:* coreference ('it'=the resolved top component)  ·  *Transition:* clarify the metric mid-task

- **[task]** What's our biggest reliability headache?
- **[clarify]** by that I mean which component fails the most, not cost.
- **[follow]** ok now show me what we usually do about it.

*Gold orchestration:* S: rank(object_class by fault) -> top; then top_remedy(filter=top)

*Weak-agent trap:* agent answers before the clarification, or 'it' rebinds to the wrong component

---

## WTB05 — Inspection effectiveness, branching follow-ups
*Topology:* S then S  ·  *Intent:* coreference chain ('that' -> the inspection set)  ·  *Transition:* trailing chat, no new task

- **[task]** Of our inspections, how many actually find a fault?
- **[follow]** Break that by equipment type.
- **[follow]** Which type is basically wasted inspection?
- **[chat]** Thought so.

*Gold orchestration:* search(Inspect)->set; count(fault in set); group_count(object_class); rank ascending by yield

*Weak-agent trap:* agent recomputes inspection set; mis-defines 'wasted' (low yield) as low count

---

## WTB06 — Spares list with a detour
*Topology:* S+P  ·  *Intent:* long-range: 'those ten' reused twice  ·  *Transition:* chat then two dependent follows

- **[task]** Give me the ten most-replaced components — stocking list.
- **[chat]** Stores will love that.
- **[follow]** Of those ten, which ones are because something broke vs routine?
- **[follow]** Just the broken ones then.

*Gold orchestration:* rank10(Replace patient); for those10 P: split failed vs routine; filter failed

*Weak-agent trap:* agent re-ranks or applies the failed/routine split to ALL components, not the ten

---

## WTB07 — Pump deep-dive, identity clarify
*Topology:* S  ·  *Intent:* coreference ('them'=text-identified pumps)  ·  *Transition:* clarify to override the misleading asset tag

- **[task]** Tell me about our pump problems.
- **[clarify]** real pumps — go by what the job text says, not the asset tag.
- **[follow]** what fails on them and how we fix it.

*Gold orchestration:* search(text mentions pump) NOT tag; extract faults+remedies

*Weak-agent trap:* agent groups by the fabricated PMP tag (wrong) instead of the text

---

## WTB08 — Failure-mode pareto, then one slice
*Topology:* S chain  ·  *Intent:* long-range: top mode feeds the last turn  ·  *Transition:* pure task chain (no chat) but deep dependency

- **[task]** Rank our failure modes, most common first.
- **[follow]** How many modes make up most of it — say 80%?
- **[follow]** Take the top mode and tell me which kit it hits.

*Gold orchestration:* group_count(fault); cumulative-to-80; filter top -> group_count(object_class)

*Weak-agent trap:* agent loses the 'top mode' referent or recomputes pareto each turn

---

## WTB09 — Parallel two-sites mental model (trap)
*Topology:* P attempted -> S  ·  *Intent:* coreference ('that' dropped)  ·  *Transition:* user self-corrects an impossible ask mid-stream

- **[task]** Compare failures on the day shift versus night shift.
- **[clarify]** oh — we don't tag shift, do we? skip that.
- **[follow]** just give me overall failures by type then.

*Gold orchestration:* recognise no shift field -> abstain on shift; pivot to group_count(object_class, fault)

*Weak-agent trap:* agent fabricates a shift split, or gets stuck instead of pivoting

---

## WTB10 — Bearings then 'the same for'
*Topology:* P (parallel-isable)  ·  *Intent:* partial intent: 'same for X' inherits the metric  ·  *Transition:* terse elliptical follow-ups

- **[task]** How many bearing jobs were replacements?
- **[follow]** Same for seals.
- **[follow]** And same for belts. Put all three side by side.

*Gold orchestration:* P: count(Replace&bearing)||count(Replace&seal)||count(Replace&belt) -> table

*Weak-agent trap:* agent fails to infer the elided metric, or serialises avoidably (poor Optimal Path)

---

## WTB11 — Chat-heavy, buried task
*Topology:* S then P  ·  *Intent:* coreference ('that'=valve action)  ·  *Transition:* heavy chat preamble then task + compare

- **[chat]** Morning! Coffee machine's broken again, ironic for a maintenance team.
- **[chat]** Anyway.
- **[task]** Can you find me the most common thing we do to valves?
- **[follow]** and is that different from what we do to sensors?

*Gold orchestration:* top action on ControllingObject; then compare to top action on SensingObject

*Weak-agent trap:* agent reacts to the coffee-machine chat as a task, or misses the real task

---

## WTB12 — Worst offender, evidence, fix
*Topology:* S chain  ·  *Intent:* coreference ('its','that') across 3 turns  ·  *Transition:* task -> evidence -> recommendation

- **[task]** Who's our worst repeat offender, component-wise?
- **[follow]** Show me the evidence — counts and its main failure.
- **[follow]** Draft what we should change.

*Gold orchestration:* rank(object_class by fault)->top; counts+top fault; recommend

*Weak-agent trap:* agent's recommendation references a different component than the one ranked

---

## WTB13 — Two questions in one breath
*Topology:* P then S  ·  *Intent:* coreference ('the worse one')  ·  *Transition:* compound single-turn (two asks + a compare)

- **[task]** How many leaks do we get, and separately how many cracks — and which is worse?
- **[follow]** For the worse one, what's the usual remedy?

*Gold orchestration:* P: count(leak)||count(crack); pick max; top_remedy(filter=that fault)

*Weak-agent trap:* agent answers one of the two, or mis-binds 'the worse one'

---

## WTB14 — Long-range callback
*Topology:* S, S, S  ·  *Intent:* long-range: 'that component from before' spans 3 turns + a distractor task  ·  *Transition:* topic switch then callback

- **[task]** Pull the most-replaced component.
- **[chat]** ok good.
- **[task]** Now, unrelated — how many inspections did we do total?
- **[follow]** Right, and that component from before — do we ever inspect it?

*Gold orchestration:* remember turn-1 component; count(Inspect & that component)

*Weak-agent trap:* agent forgets the early referent after the unrelated task in between

---

## WTB15 — Filter then re-filter
*Topology:* S progressive  ·  *Intent:* coreference: progressive narrowing of one set  ·  *Transition:* successive refinement

- **[task]** Show failures on lines and drives — belts, chains, hoses, cables.
- **[follow]** Narrow to just the ones we replaced.
- **[follow]** Now just hoses out of those.

*Gold orchestration:* search(GuidingObject&fault); filter Replace; filter hose subtype

*Weak-agent trap:* agent restarts the filter from scratch each time instead of narrowing

---

## WTB16 — Clarify the unit of count
*Topology:* S  ·  *Intent:* coreference ('those parts')  ·  *Transition:* clarify the counting unit

- **[task]** How many replacements did we do?
- **[clarify]** do you mean jobs or actual parts? I want distinct parts.
- **[follow]** ok and how many of those parts are wear items?

*Gold orchestration:* count distinct object_class replaced; then intersect with wear-item set

*Weak-agent trap:* agent reports WO count not distinct parts; or 'those' rebinds to jobs

---

## WTB17 — Parallel compare + casual + extend
*Topology:* P, P, then aggregate  ·  *Intent:* partial ('same question'), long-range (combine)  ·  *Transition:* chat then parallel extend then merge

- **[task]** Replace vs repair — which do we lean on for engines?
- **[chat]** engines are always drama.
- **[follow]** what about motors, same question?
- **[follow]** combine engines and motors and tell me the overall lean.

*Gold orchestration:* P engines:Replace||Repair; P motors; then merge counts

*Weak-agent trap:* agent treats motors fresh and can't merge with engines for the overall

---

## WTB18 — Implicit object
*Topology:* S  ·  *Intent:* coreference ('it','that')  ·  *Transition:* short, implicit-object task

- **[task]** We change a lot of oil — what's it usually on?
- **[follow]** and is that a service or a replacement in our coding?

*Gold orchestration:* find oil-change WOs; infer object; classify activity (Service)

*Weak-agent trap:* agent treats 'change oil' as Replace, or can't ground 'it'

---

## WTB19 — Three-way then pick
*Topology:* P then S  ·  *Intent:* coreference ('which dominates')  ·  *Transition:* clarification arrives AFTER the compute (must redo)

- **[task]** Of failures, how do we respond — replace, repair, or service? give the split.
- **[follow]** which response dominates?
- **[clarify]** and to be clear, only count jobs where something actually failed.

*Gold orchestration:* P split among FailedState WOs; argmax; re-scope to failed-only if not already

*Weak-agent trap:* agent computed over all jobs; the late clarify forces a re-scope it skips

---

## WTB20 — Casual misdirection
*Topology:* S  ·  *Intent:* coreference ('the second')  ·  *Transition:* chat bookends

- **[chat]** Did you catch the game last night?
- **[task]** Anyway — most common fault across the whole lot?
- **[follow]** and the second most common?
- **[chat]** nice, ta.

*Gold orchestration:* group_count(fault); take rank1 then rank2

*Weak-agent trap:* agent engages the game chat as if a task, or recomputes for rank2

---

## WTB21 — Bad actor -> RCA -> abstain boundary
*Topology:* S  ·  *Intent:* coreference ('it')  ·  *Transition:* clarify lowers the bar from cause to mode

- **[task]** Find the component we run to failure the most.
- **[follow]** Why does it keep failing?
- **[clarify]** I know root cause isn't in the text — just infer the likely mode.

*Gold orchestration:* rank run-to-failure class; report dominant mode (not fabricated cause)

*Weak-agent trap:* agent invents a root cause instead of the inferable mode

---

## WTB22 — Parallel KPIs for a dashboard
*Topology:* P (4-way)  ·  *Intent:* partial: 'the last one'  ·  *Transition:* single compound dashboard ask

- **[task]** Give me four numbers for a board slide: total jobs, % replacements, % with a fault, top failing component.
- **[follow]** tighten the last one to a plain-English label.

*Gold orchestration:* P: count||share||share||rank; humanize the component label

*Weak-agent trap:* agent serialises the 4 (poor path) or mislabels with ontology jargon

---

## WTB23 — Refer by position
*Topology:* S, S  ·  *Intent:* coreference by ORDINAL ('third','fifth')  ·  *Transition:* positional reference into a prior list

- **[task]** Top 5 most-replaced components.
- **[follow]** what's the third one used for / what is it?
- **[follow]** and how often is the fifth a breakdown?

*Gold orchestration:* rank5; index 3 -> describe; index 5 -> failed-share

*Weak-agent trap:* agent miscounts ordinals or re-ranks, shifting positions

---

## WTB24 — Self-correcting user
*Topology:* S then P  ·  *Intent:* coreference correction (part vs whole)  ·  *Transition:* user revises intent

- **[task]** How many pump replacements?
- **[follow]** actually I meant pump SEAL replacements, not whole pumps.
- **[follow]** and whole pumps separately for contrast.

*Gold orchestration:* count(Replace & InfillingObject on pump) vs count(Replace & pump whole)

*Weak-agent trap:* agent keeps the whole-pump count after the correction

---

## WTB25 — Chat that contains a constraint
*Topology:* S  ·  *Intent:* long-range: the 'only faults' constraint set in a chat turn  ·  *Transition:* constraint hidden in casual aside

- **[chat]** FYI we don't care about routine servicing, only actual faults.
- **[task]** With that, what's our most common job?
- **[follow]** by equipment type now.

*Gold orchestration:* apply fault-only filter from the chat turn; top (activity,object); then group

*Weak-agent trap:* agent ignores the chat-stated constraint and counts routine work

---

## WTB26 — Two sets, then their overlap
*Topology:* P then S  ·  *Intent:* coreference ('both')  ·  *Transition:* two parallel tasks then an intersection

- **[task]** Find jobs that mention a failed state.
- **[task]** Separately, find jobs that mention a replacement.
- **[follow]** how many are in both — reactive replacements?

*Gold orchestration:* P: setA=failed; setB=replace; |A∩B|

*Weak-agent trap:* agent recomputes or counts union/either instead of intersection

---

## WTB27 — Escalating specificity with chat
*Topology:* S chain  ·  *Intent:* coreference ('those' twice, narrowing)  ·  *Transition:* motivational chat mid-thread

- **[task]** Anything on cooling systems?
- **[chat]** summer's coming, want to get ahead of it.
- **[follow]** of those, which had an actual failure?
- **[follow]** and what did we do for those?

*Gold orchestration:* search(cooling); filter failed; extract remedies

*Weak-agent trap:* agent loses the cooling scope after the chat turn

---

## WTB28 — Compare remedies across two faults
*Topology:* P then compare  ·  *Intent:* coreference ('they')  ·  *Transition:* two parallel asks then a diff

- **[task]** For leaks, what do we do? For cracks, what do we do?
- **[follow]** where do they differ most?

*Gold orchestration:* P: remedy_dist(leak)||remedy_dist(crack); compare()

*Weak-agent trap:* agent reports both but never computes the difference asked

---

## WTB29 — Long horizon with a casual derail
*Topology:* S (heavy) then S  ·  *Intent:* coreference ('#1')  ·  *Transition:* derail then drill into result 1

- **[task]** Walk the whole set and give me the top 3 job signatures (object+fault+fix).
- **[chat]** this is gold for standard work.
- **[follow]** take #1 and tell me how many variants it's written as.

*Gold orchestration:* rank3 signatures; for #1 count surface variants

*Weak-agent trap:* agent re-derives signatures or picks a different one to drill

---

## WTB30 — Ambiguous 'it' resolved by context
*Topology:* S then P  ·  *Intent:* coreference ('it'=the replace/repair pattern; 'they'=bearings)  ·  *Transition:* analogical follow-up

- **[task]** Bearings — replace or repair, mostly?
- **[follow]** and is it the same story for the housings they sit in?

*Gold orchestration:* bearing replace vs repair; then same metric on enclosing/housing class

*Weak-agent trap:* agent mis-resolves 'they/it' or changes the metric

---

## WTB31 — Counting with a moving filter
*Topology:* S progressive  ·  *Intent:* coreference (progressive AND filters)  ·  *Transition:* stacking filters across turns

- **[task]** How many faults total?
- **[follow]** now only the ones on protective gear.
- **[follow]** now only those we replaced.

*Gold orchestration:* count(fault); +ProtectingObject; +Replace

*Weak-agent trap:* agent treats each turn as independent (loses the stack)

---

## WTB32 — Parallel then conditional branch
*Topology:* S then Selection  ·  *Intent:* coreference ('it'=the share)  ·  *Transition:* embedded conditional in a follow-up

- **[task]** What share of replacements are breakdown-driven?
- **[follow]** if it's over a third, show me the worst component; if not, just say it's fine.

*Gold orchestration:* compute share; branch: if>33% rank worst else 'fine'

*Weak-agent trap:* agent always shows the component (ignores the condition) or mis-evaluates it

---

## WTB33 — Re-scope after a wrong assumption
*Topology:* S  ·  *Intent:* coreference ('its')  ·  *Transition:* clarify forces a representation change (asset->class)

- **[task]** Which asset fails most?
- **[clarify]** oh the tags are junk — do it by equipment type from the text instead.
- **[follow]** good, now its top failure mode.

*Gold orchestration:* pivot from tag to text-derived object_class; rank; top mode

*Weak-agent trap:* agent persists with the misleading asset tag

---

## WTB34 — Terse expert
*Topology:* S  ·  *Intent:* coreference (ordinal '#2')  ·  *Transition:* extremely terse, elliptical

- **[task]** replace counts by class, desc.
- **[follow]** top3 only.
- **[follow]** #2's fault mix.

*Gold orchestration:* rank replace by class; top3; for #2 group_count(fault)

*Weak-agent trap:* agent misreads terse commands or wrong ordinal

---

## WTB35 — Two metrics, pick by user value
*Topology:* P then S  ·  *Intent:* coreference ('the messy one','its')  ·  *Transition:* user re-weights the metric

- **[task]** Most-failing component — give me both raw count and failure variety.
- **[clarify]** I care more about variety, that's the messy one.
- **[follow]** so which is it, and what are its modes?

*Gold orchestration:* P: rank by count || rank by distinct-modes; pick variety winner; list modes

*Weak-agent trap:* agent answers by count (the obvious) not the variety metric the user chose

---

## WTB36 — Inspection -> fix chain, with aside
*Topology:* S then S  ·  *Intent:* coreference ('that')  ·  *Transition:* approving aside

- **[task]** How often do we inspect then fix in the same job?
- **[chat]** that's the good kind of job.
- **[follow]** on what equipment does that happen most?

*Gold orchestration:* count(Inspect & remedy same WO); group_count(object_class) on that set

*Weak-agent trap:* agent counts inspect-only or any-remedy, not the conjunction

---

## WTB37 — Compare and then combine differently
*Topology:* S then S  ·  *Intent:* coreference (the per-type table feeds 'which')  ·  *Transition:* progressive granularity

- **[task]** Reactive vs proactive split overall.
- **[follow]** now per equipment type.
- **[follow]** which type is most reactive?

*Gold orchestration:* overall split; group by class; argmax reactive share

*Weak-agent trap:* agent recomputes or ranks by raw reactive count not share

---

## WTB38 — Distractor numbers
*Topology:* S  ·  *Intent:* coreference ('that')  ·  *Transition:* clarify what 'number' means (data-quality angle)

- **[task]** How many jobs mention a number like a quantity?
- **[clarify]** I mean the masked <num> placeholders, those carry no info.
- **[follow]** what fraction of all jobs is that?

*Gold orchestration:* count(<num> token); /total

*Weak-agent trap:* agent counts digits in text or miscounts the placeholder

---

## WTB39 — Multi-component stocking plan
*Topology:* P then S  ·  *Intent:* coreference ('the unplanned ones')  ·  *Transition:* parallel then split then filter

- **[task]** Top wear items by replacement: bearings, seals, belts, filters — counts.
- **[follow]** which are unplanned (failure) demand vs plannable?
- **[follow]** just the unplanned ones, ranked.

*Gold orchestration:* P counts 4 items; split failed vs routine; filter+rank failed

*Weak-agent trap:* agent loses the 4-item scope or mixes planned into the final rank

---

## WTB40 — User changes the question after seeing data
*Topology:* S  ·  *Intent:* coreference ('it'); intent pivot mode->component  ·  *Transition:* user pivots dimension after seeing results

- **[task]** Show the failure-mode pareto.
- **[follow]** hmm, actually forget modes — redo it for components.
- **[follow]** top one, and is it mostly outright failure?

*Gold orchestration:* rank components by fault; top; failed-share

*Weak-agent trap:* agent stays on modes or carries stale numbers

---

## WTB41 — Parallel sanity check
*Topology:* P then verify  ·  *Intent:* coreference ('the two')  ·  *Transition:* compute-two-then-cross-check

- **[task]** Give me replacements by class, and also class totals by activity.
- **[follow]** do the replacement totals reconcile across the two?

*Gold orchestration:* P: by-object replace || by-activity; assert totals equal

*Weak-agent trap:* agent doesn't actually cross-check, just restates both

---

## WTB42 — Chat reveals scope
*Topology:* S  ·  *Intent:* long-range scope in chat; then user flags it's unsplittable  ·  *Transition:* constraint then self-doubt

- **[chat]** We're only responsible for the mobile fleet, not fixed plant.
- **[task]** With that, what's our most-replaced component?
- **[clarify]** though honestly we can't split mobile vs fixed from this data, can we?

*Gold orchestration:* acknowledge no mobile/fixed field; answer overall + caveat

*Weak-agent trap:* agent fabricates a mobile-only subset

---

## WTB43 — Stacked superlatives
*Topology:* S chain  ·  *Intent:* coreference chain ('its','that') 3 deep  ·  *Transition:* nested superlatives

- **[task]** Worst component.
- **[follow]** its worst fault.
- **[follow]** the worst (most-skewed) fix for that fault.

*Gold orchestration:* rank component; its top fault; most-skewed remedy for that fault

*Weak-agent trap:* agent's chain drifts — final fix not tied to the resolved component/fault

---

## WTB44 — Two unrelated tasks then a join
*Topology:* P then synthesise  ·  *Intent:* coreference ('those','the gap')  ·  *Transition:* two tasks then an interpretive follow

- **[task]** Count diagnose-only jobs.
- **[task]** Count replace jobs with no diagnosis.
- **[follow]** what does the gap between those say about our RCA habit?

*Gold orchestration:* P: count(Diagnose-only)||count(Replace&!Diagnose); interpret

*Weak-agent trap:* agent gives raw numbers, never interprets the requested gap

---

## WTB45 — Resolve 'the usual' from data
*Topology:* S then S  ·  *Intent:* coreference ('that change'=the remedy)  ·  *Transition:* 'usual' = modal remedy

- **[task]** What's the usual fix when a sensor plays up?
- **[follow]** and when it's fully failed, does that change?

*Gold orchestration:* modal remedy on SensingObject faults; then condition on FailedState

*Weak-agent trap:* agent reports a non-modal fix, or ignores the failed-state condition

---

## WTB46 — Parallel across three faults + pick
*Topology:* P then argmax  ·  *Intent:* coreference ('which fault')  ·  *Transition:* 3 parallel then a selection by replace-share

- **[task]** For seized, leaking, and cracked — what's the dominant remedy each?
- **[follow]** which fault is the most 'just replace it' one?

*Gold orchestration:* P: remedy_dist for 3 faults; argmax replace-share

*Weak-agent trap:* agent picks by raw replace count not share, or drops one fault

---

## WTB47 — Long callback after detour
*Topology:* S, S, S  ·  *Intent:* long-range callback to valves across a detour task  ·  *Transition:* topic switch and return

- **[task]** Most common job on valves?
- **[chat]** valves everywhere in this plant.
- **[task]** Different thing: how many jobs have no object recorded?
- **[follow]** and back to valves — what's the second most common job there?

*Gold orchestration:* valve top job (remember); DQ count; valve 2nd job

*Weak-agent trap:* agent loses valve context or recomputes valve set after detour

---

## WTB48 — Conditional on data availability
*Topology:* Selection then S  ·  *Intent:* coreference ('the top mode')  ·  *Transition:* user pre-authorises a fallback branch

- **[task]** Trend our failures over time.
- **[clarify]** if there's no date field, just give me the static failure-mode breakdown instead.
- **[follow]** and flag the top mode.

*Gold orchestration:* detect no dates -> fallback: group_count(fault); flag rank1

*Weak-agent trap:* agent stalls on the impossible trend instead of taking the offered fallback

---

## WTB49 — Build then critique own answer
*Topology:* S then reflect  ·  *Intent:* coreference ('it'=the headline)  ·  *Transition:* self-critique follow-up

- **[task]** Give me a one-line reliability headline from the data.
- **[follow]** now poke holes in it — what's the weakest assumption?
- **[chat]** fair.

*Gold orchestration:* compose headline (top class+mode+reactive%); state its caveat (no time/cost/asset)

*Weak-agent trap:* agent gives a second headline instead of critiquing the first

---

## WTB50 — Everything, prioritised, your call
*Topology:* S (long-horizon)  ·  *Intent:* coreference ('it'); clarify defines the metric  ·  *Transition:* open mandate then metric clarify then structured output

- **[task]** Scan the lot. Tell me the single most important reliability action.
- **[clarify]** 'important' = biggest failure burden, since we've no cost data.
- **[follow]** name the component, the evidence, and the one task you'd add.

*Gold orchestration:* rank by fault*failed-share; pick; counts as evidence; recommend one task

*Weak-agent trap:* agent gives a vague theme, or recommends for a component other than the ranked one

---

## Sources
- WildToolBench, ICLR 2026: https://arxiv.org/abs/2604.06185 · https://github.com/yupeijei1997/WildToolBench
