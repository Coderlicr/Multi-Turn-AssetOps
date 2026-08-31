# WildToolBench Scenarios — Ground Truth & Verification (WTB01-WTB50)

For each multi-turn scenario, every turn carries: the **resolved intent**, the **optimal tool plan** (parallel-groups in required sequence; `[]` = no tool call, e.g. chat/clarify), and the **computed gold result** from the IE graph. `judge=Y` marks turns that also need an LLM-judged narrative on top of the numbers.

## How to reproduce & score
```bash
python3 wtb_ground_truth.py gold_release.json   # writes wtb_ground_truth.json + demo scoring
```
Scoring harness `score(agent_turns, gold_turns)` returns **Optimal Path Rate** (did the agent use the right parallel/sequential tool plan, with no redundant calls and no tool call on chat/clarify turns) and **Accomplish Progress Rate** (fraction of compute-turns whose result equals gold). Verified demo: perfect trace -> 1.0/1.0; a trace that serialises a parallel call, returns a wrong result, and calls a tool on a clarify turn -> 0.5/0.67.

---

## WTB01 — Replace vs repair, then drill in
*Topology:* P then S · *Intent:* coreference ('the replacements'), long-range to turn-1 set · *Transition:* clarify mid-stream then resume

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | How many of our jobs are replacements versus repairs? | count replacements & repairs | count:Replace∥count:Repair | `{'replace': 347, 'repair': 127}` |  |
| 2 | [follow] | Ok, and of the replacements, which equipment shows up most? | of replacements, top object class | filter:Replace>group:object>rank:1 | `{'top': [['Lines & drives', 89]]}` |  |
| 3 | [clarify] | Wait — does 'change out' count as a replacement here? | confirm 'change out'==Replace; no tool | — (no tool call) | `—` |  |
| 4 | [follow] | Right, with that in mind give me the top three. | top 3 replaced classes (reuse grouping) | rank:3 | `{'top3': [['Lines & drives', 89], ['Engines & motors', 44], ['Structural/mounting parts', 36]]}` |  |

## WTB02 — Leaks chat interlude
*Topology:* S · *Intent:* coreference ('those','the worst') back to leak set · *Transition:* casual chat between tasks

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Pull everything about leaks for me. | build leak set | search:process_fault | `{'leak_WOs': 146}` |  |
| 2 | [chat] | Cheers. Long week. Anyway — | acknowledge; no tool | — (no tool call) | `—` |  |
| 3 | [follow] | of those, how many did we just seal versus replace? | on leak set: seal vs replace | count:Modify@set∥count:Replace@set | `{'seal': 0, 'replace': 22}` |  |
| 4 | [follow] | and which one's the worst offender? | worst object class in leak set | rank:1@set | `{'worst': ['Guards & protective parts', 45]}` |  |

## WTB03 — Two components in parallel
*Topology:* P (then expand) · *Intent:* long-range: extend the same comparison frame · *Transition:* chat acknowledgement then expand

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Compare bearings and seals for me — how often each fails and what we do. | compare bearings & seals (parallel) | extract:bearing∥extract:seal | `{'bearing': {'fault': 10, 'remedy': {'Replace': 9, 'Inspect': 6, 'Service': 1, 'Diagnose': 1, 'Repair': 1}}, 'seal': {'fault': 14, 'remedy': {'Replace': 7, 'Rep …` |  |
| 2 | [follow] | Which of the two is more of a problem? | which of the two worse | compare | `{'worse': 'seal'}` |  |
| 3 | [chat] | Makes sense, those seals are rubbish. | acknowledge; no tool | — (no tool call) | `—` |  |
| 4 | [follow] | Add belts into that comparison too. | add belts -> 3-way | extract:belt | `{'belt': {'fault': 31, 'remedy': {'Replace': 56, 'Inspect': 5, 'Repair': 5, 'Service': 1, 'Adjust': 2}}}` |  |

## WTB04 — Vague then precise
*Topology:* S · *Intent:* coreference ('it'=the resolved top component) · *Transition:* clarify the metric mid-task

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | What's our biggest reliability headache? | ambiguous 'biggest headache' -> await metric or assume fault-count | rank:fault_class:1 | `{'top': ['Lines & drives', 107]}` | Y |
| 2 | [clarify] | by that I mean which component fails the most, not cost. | metric = most-failing component (not cost); no new tool | — (no tool call) | `—` |  |
| 3 | [follow] | ok now show me what we usually do about it. | usual remedy for that component | filter:top>remedy_dist>argmax | `{'remedy': 'Replace'}` |  |

## WTB05 — Inspection effectiveness, branching follow-ups
*Topology:* S then S · *Intent:* coreference chain ('that' -> the inspection set) · *Transition:* trailing chat, no new task

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Of our inspections, how many actually find a fault? | inspections that find a fault | search:Inspect>count:fault | `{'inspect_with_fault': 4}` |  |
| 2 | [follow] | Break that by equipment type. | break by equipment type | group:object@set | `{'by_class': {'Engines & motors': [2, 24], 'Structural/mounting parts': [0, 18], 'Guards & protective parts': [3, 9], 'Transformers/gearboxes': [1, 8], 'Pumps/f …` |  |
| 3 | [follow] | Which type is basically wasted inspection? | lowest-yield (wasted) type | rank_asc:yield | `{'low_yield': [['Structural/mounting parts', 0.0], ['Tanks & storage', 0.0], ['Pumps/fans/generators', 0.0]]}` |  |
| 4 | [chat] | Thought so. | no tool | — (no tool call) | `—` |  |

## WTB06 — Spares list with a detour
*Topology:* S+P · *Intent:* long-range: 'those ten' reused twice · *Transition:* chat then two dependent follows

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Give me the ten most-replaced components — stocking list. | top10 most-replaced | rank:replace:10 | `{'top10': [['Lines & drives', 89], ['Engines & motors', 44], ['Structural/mounting parts', 36], ['Pumps/fans/generators', 29], ['Valves/breakers/switches', 19], …` |  |
| 2 | [chat] | Stores will love that. | no tool | — (no tool call) | `—` |  |
| 3 | [follow] | Of those ten, which ones are because something broke vs routine? | of those10: broken vs routine | split:failed@top10 | `{'breakdown_within_top10': {'Filters & separators': 5, 'Covers & seals': 2, 'Pumps/fans/generators': 6, 'Valves/breakers/switches': 12, 'Lines & drives': 19, 'S …` |  |
| 4 | [follow] | Just the broken ones then. | just the broken ones | filter:failed@top10 | `{'broken': {'Filters & separators': 5, 'Covers & seals': 2, 'Pumps/fans/generators': 6, 'Valves/breakers/switches': 12, 'Lines & drives': 19, 'Structural/mounti …` |  |

## WTB07 — Pump deep-dive, identity clarify
*Topology:* S · *Intent:* coreference ('them'=text-identified pumps) · *Transition:* clarify to override the misleading asset tag

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Tell me about our pump problems. | pump problems (vague) | search:pump_text | `{'pump_text_WOs': 42}` | Y |
| 2 | [clarify] | real pumps — go by what the job text says, not the asset tag. | use text not asset tag; no tool | — (no tool call) | `—` |  |
| 3 | [follow] | what fails on them and how we fix it. | faults & remedies on text-pumps | extract@set | `{'remedies': {'Replace': 22, 'Repair': 1, 'Diagnose': 1}, 'top_fault': 'Failed/broken'}` |  |

## WTB08 — Failure-mode pareto, then one slice
*Topology:* S chain · *Intent:* long-range: top mode feeds the last turn · *Transition:* pure task chain (no chat) but deep dependency

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Rank our failure modes, most common first. | failure-mode pareto | group:fault>rank | `{'pareto': [['Failed/broken', 215], ['Faulty', 178], ['Active failure (leak/overheat)', 146], ['Worn/degraded', 45], ['Defect (crack/hole/noise)', 32]]}` |  |
| 2 | [follow] | How many modes make up most of it — say 80%? | modes for 80% | cumsum | `{'modes_for_80pct': 3}` |  |
| 3 | [follow] | Take the top mode and tell me which kit it hits. | top mode -> which kit | filter:topmode>group:object>rank:1 | `{'top_mode': 'Failed/broken', 'top_kit': ['Lines & drives', 50]}` |  |

## WTB09 — Parallel two-sites mental model (trap)
*Topology:* P attempted -> S · *Intent:* coreference ('that' dropped) · *Transition:* user self-corrects an impossible ask mid-stream

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Compare failures on the day shift versus night shift. | shift comparison (will fail: no shift field) | attempt:group:shift | `{'shift_field': 'absent'}` | Y |
| 2 | [clarify] | oh — we don't tag shift, do we? skip that. | user drops shift; no tool | — (no tool call) | `—` |  |
| 3 | [follow] | just give me overall failures by type then. | pivot: failures by type | group:object,fault | `{'by_class': [['GuidingObject', 107], ['HoldingObject', 82], ['ProtectingObject', 75], ['EmittingObject', 72], ['GeneratingObject', 68]]}` |  |

## WTB10 — Bearings then 'the same for'
*Topology:* P (parallel-isable) · *Intent:* partial intent: 'same for X' inherits the metric · *Transition:* terse elliptical follow-ups

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | How many bearing jobs were replacements? | bearing replacements | count:Replace&bearing | `{'bearing': 9}` |  |
| 2 | [follow] | Same for seals. | same for seals (elliptical) | count:Replace&seal | `{'seal': 7}` |  |
| 3 | [follow] | And same for belts. Put all three side by side. | same for belts; table all 3 (parallelisable) | count:Replace&belt | `{'belt': 56, 'table': {'bearing': 9, 'seal': 7, 'belt': 56}}` |  |

## WTB11 — Chat-heavy, buried task
*Topology:* S then P · *Intent:* coreference ('that'=valve action) · *Transition:* heavy chat preamble then task + compare

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [chat] | Morning! Coffee machine's broken again, ironic for a maintenance team. | coffee-machine banter; no tool | — (no tool call) | `—` |  |
| 2 | [chat] | Anyway. | 'anyway'; no tool | — (no tool call) | `—` |  |
| 3 | [task] | Can you find me the most common thing we do to valves? | most common action on valves | filter:ControllingObject>remedy>argmax | `{'valve_top': 'Replace'}` |  |
| 4 | [follow] | and is that different from what we do to sensors? | different from sensors? | filter:Sensor>remedy>argmax | `{'sensor_top': 'Replace'}` |  |

## WTB12 — Worst offender, evidence, fix
*Topology:* S chain · *Intent:* coreference ('its','that') across 3 turns · *Transition:* task -> evidence -> recommendation

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Who's our worst repeat offender, component-wise? | worst repeat offender | rank:fault_class:1 | `{'worst': ['Lines & drives', 107]}` |  |
| 2 | [follow] | Show me the evidence — counts and its main failure. | evidence: counts+main fault | filter:top>count∥filter:top>group:fault>rank:1 | `{'count': 107, 'main_fault': 'Failed/broken'}` |  |
| 3 | [follow] | Draft what we should change. | draft change (narrative) | compose | `{'target': 'Lines & drives', 'basis': 'Failed/broken'}` | Y |

## WTB13 — Two questions in one breath
*Topology:* P then S · *Intent:* coreference ('the worse one') · *Transition:* compound single-turn (two asks + a compare)

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | How many leaks do we get, and separately how many cracks — and which is worse? | count leaks & cracks; which worse | count:leak∥count:crack | `{'leak': 146, 'crack': 32, 'worse': 'leak'}` |  |
| 2 | [follow] | For the worse one, what's the usual remedy? | usual remedy for the worse one | filter:worse>remedy>argmax | `{'remedy': 'Replace'}` |  |

## WTB14 — Long-range callback
*Topology:* S, S, S · *Intent:* long-range: 'that component from before' spans 3 turns + a distractor task · *Transition:* topic switch then callback

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Pull the most-replaced component. | most-replaced component | rank:replace:1 | `{'top': 'Lines & drives'}` |  |
| 2 | [chat] | ok good. | no tool | — (no tool call) | `—` |  |
| 3 | [task] | Now, unrelated — how many inspections did we do total? | total inspections (distractor) | count:Inspect | `{'inspections': 62}` |  |
| 4 | [follow] | Right, and that component from before — do we ever inspect it? | callback: do we inspect THAT component? | count:Inspect&topcomp | `{'inspect_top_component': 6}` |  |

## WTB15 — Filter then re-filter
*Topology:* S progressive · *Intent:* coreference: progressive narrowing of one set · *Transition:* successive refinement

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Show failures on lines and drives — belts, chains, hoses, cables. | failures on lines & drives | search:GuidingObject&fault | `{'n': 107}` |  |
| 2 | [follow] | Narrow to just the ones we replaced. | narrow to replaced | filter:Replace@set | `{'n': 40}` |  |
| 3 | [follow] | Now just hoses out of those. | narrow to hoses | filter:hose@set | `{'n': 24}` |  |

## WTB16 — Clarify the unit of count
*Topology:* S · *Intent:* coreference ('those parts') · *Transition:* clarify the counting unit

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | How many replacements did we do? | how many replacements | count:Replace | `{'replace_jobs': 347}` |  |
| 2 | [clarify] | do you mean jobs or actual parts? I want distinct parts. | unit = distinct parts; recompute | distinct:object@Replace | `{'distinct_parts': 18}` |  |
| 3 | [follow] | ok and how many of those parts are wear items? | of those, wear items | intersect:wear | `{'wear_parts': 0}` |  |

## WTB17 — Parallel compare + casual + extend
*Topology:* P, P, then aggregate · *Intent:* partial ('same question'), long-range (combine) · *Transition:* chat then parallel extend then merge

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Replace vs repair — which do we lean on for engines? | engines: replace vs repair | count:eR∥count:eP | `{'engine': {'replace': 20, 'repair': 9}}` |  |
| 2 | [chat] | engines are always drama. | no tool | — (no tool call) | `—` |  |
| 3 | [follow] | what about motors, same question? | motors: same | count:mR∥count:mP | `{'motor': {'replace': 16, 'repair': 3}}` |  |
| 4 | [follow] | combine engines and motors and tell me the overall lean. | combine -> overall lean | merge | `{'overall': {'replace': 36, 'repair': 12, 'lean': 'replace'}}` |  |

## WTB18 — Implicit object
*Topology:* S · *Intent:* coreference ('it','that') · *Transition:* short, implicit-object task

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | We change a lot of oil — what's it usually on? | oil changes - what's it on | search:oil>infer_object | `{'oil_WOs': 70}` | Y |
| 2 | [follow] | and is that a service or a replacement in our coding? | service or replacement in our coding | classify_activity@set | `{'service': 2, 'replace': 16}` |  |

## WTB19 — Three-way then pick
*Topology:* P then S · *Intent:* coreference ('which dominates') · *Transition:* clarification arrives AFTER the compute (must redo)

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Of failures, how do we respond — replace, repair, or service? give the split. | of failures: replace/repair/service split | filter:failed>split3 | `{'split': {'Replace': 51, 'Repair': 4, 'Service': 0}}` |  |
| 2 | [follow] | which response dominates? | which dominates | argmax | `{'dominant': 'Replace'}` |  |
| 3 | [clarify] | and to be clear, only count jobs where something actually failed. | ensure failed-only scope (re-scope if needed); no NEW tool if already scoped | — (no tool call) | `—` |  |

## WTB20 — Casual misdirection
*Topology:* S · *Intent:* coreference ('the second') · *Transition:* chat bookends

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [chat] | Did you catch the game last night? | game banter; no tool | — (no tool call) | `—` |  |
| 2 | [task] | Anyway — most common fault across the whole lot? | most common fault overall | group:fault>rank:1 | `{'top1': ['Failed/broken', 215]}` |  |
| 3 | [follow] | and the second most common? | second most common | index:2 | `{'top2': ['Faulty', 178]}` |  |
| 4 | [chat] | nice, ta. | no tool | — (no tool call) | `—` |  |

## WTB21 — Bad actor -> RCA -> abstain boundary
*Topology:* S · *Intent:* coreference ('it') · *Transition:* clarify lowers the bar from cause to mode

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Find the component we run to failure the most. | run-to-failure component | rank:rtf:1 | `{'top': ['Lines & drives', 21]}` |  |
| 2 | [follow] | Why does it keep failing? | why it fails (infer mode, not cause) | filter:top>group:fault>rank:1 | `{'likely_mode': 'Failed/broken'}` |  |
| 3 | [clarify] | I know root cause isn't in the text — just infer the likely mode. | mode not cause; no tool | — (no tool call) | `—` |  |

## WTB22 — Parallel KPIs for a dashboard
*Topology:* P (4-way) · *Intent:* partial: 'the last one' · *Transition:* single compound dashboard ask

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Give me four numbers for a board slide: total jobs, % replacements, % with a fault, top failing component. | 4 dashboard numbers (parallel) | count:all∥share:replace∥share:fault∥rank:fault:1 | `{'total': 1076, 'replace_pct': 32.2, 'fault_pct': 51.9, 'top_component': 'Lines & drives'}` |  |
| 2 | [follow] | tighten the last one to a plain-English label. | plain label for last one | humanize | `{'top_component_label': 'Lines & drives'}` |  |

## WTB23 — Refer by position
*Topology:* S, S · *Intent:* coreference by ORDINAL ('third','fifth') · *Transition:* positional reference into a prior list

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Top 5 most-replaced components. | top5 most-replaced | rank:replace:5 | `{'top5': [['Lines & drives', 89], ['Engines & motors', 44], ['Structural/mounting parts', 36], ['Pumps/fans/generators', 29], ['Valves/breakers/switches', 19]]}` |  |
| 2 | [follow] | what's the third one used for / what is it? | what's the 3rd | index:3 | `{'third': 'Structural/mounting parts'}` |  |
| 3 | [follow] | and how often is the fifth a breakdown? | how often is the 5th a breakdown | filter:5th&failed>count | `{'fifth': 'Valves/breakers/switches', 'breakdown': 12}` |  |

## WTB24 — Self-correcting user
*Topology:* S then P · *Intent:* coreference correction (part vs whole) · *Transition:* user revises intent

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | How many pump replacements? | pump replacements | count:Replace&pump | `{'whole_pump': 23}` |  |
| 2 | [follow] | actually I meant pump SEAL replacements, not whole pumps. | correction: pump SEAL replacements | count:Replace&seal | `{'pump_seal': 7}` |  |
| 3 | [follow] | and whole pumps separately for contrast. | whole pumps separately | count:Replace&pump | `{'whole_pump': 23}` |  |

## WTB25 — Chat that contains a constraint
*Topology:* S · *Intent:* long-range: the 'only faults' constraint set in a chat turn · *Transition:* constraint hidden in casual aside

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [chat] | FYI we don't care about routine servicing, only actual faults. | constraint set: faults only; no tool | — (no tool call) | `—` |  |
| 2 | [task] | With that, what's our most common job? | most common job (faults only) | filter:fault>top(activity,object) | `{'top_job': [['Replace', 'Lines & drives'], 40]}` |  |
| 3 | [follow] | by equipment type now. | by equipment type | group:object@fault | `{'by_class': [['GuidingObject', 107], ['HoldingObject', 82], ['ProtectingObject', 75], ['EmittingObject', 72], ['GeneratingObject', 68]]}` |  |

## WTB26 — Two sets, then their overlap
*Topology:* P then S · *Intent:* coreference ('both') · *Transition:* two parallel tasks then an intersection

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Find jobs that mention a failed state. | set A: failed | search:failed | `{'A': 211}` |  |
| 2 | [task] | Separately, find jobs that mention a replacement. | set B: replace | search:replace | `{'B': 347}` |  |
| 3 | [follow] | how many are in both — reactive replacements? | intersection (reactive replacements) | intersect:A,B | `{'both': 51}` |  |

## WTB27 — Escalating specificity with chat
*Topology:* S chain · *Intent:* coreference ('those' twice, narrowing) · *Transition:* motivational chat mid-thread

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Anything on cooling systems? | anything on cooling | search:cooling | `{'n': 8}` |  |
| 2 | [chat] | summer's coming, want to get ahead of it. | no tool | — (no tool call) | `—` |  |
| 3 | [follow] | of those, which had an actual failure? | of those, failed | filter:failed@set | `{'failed': 0}` |  |
| 4 | [follow] | and what did we do for those? | remedies for those | remedy_dist@set | `{'remedies': {}}` |  |

## WTB28 — Compare remedies across two faults
*Topology:* P then compare · *Intent:* coreference ('they') · *Transition:* two parallel asks then a diff

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | For leaks, what do we do? For cracks, what do we do? | leak remedies & crack remedies (parallel) | remedy:leak∥remedy:crack | `{'leak': {'Replace': 22, 'Inspect': 3, 'Repair': 15, 'Diagnose': 3}, 'crack': {'Repair': 13}}` |  |
| 2 | [follow] | where do they differ most? | where differ most | compare | `{'max_diff_action': 'Replace'}` |  |

## WTB29 — Long horizon with a casual derail
*Topology:* S (heavy) then S · *Intent:* coreference ('#1') · *Transition:* derail then drill into result 1

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Walk the whole set and give me the top 3 job signatures (object+fault+fix). | top3 job signatures | scan>group:(obj,fault,act)>rank:3 | `{'top3': [[['Engines & motors', '(none)', 'Replace'], 66], [['Lines & drives', '(none)', 'Replace'], 63], [['Pumps/fans/generators', '(none)', 'Replace'], 42]]}` |  |
| 2 | [chat] | this is gold for standard work. | no tool | — (no tool call) | `—` |  |
| 3 | [follow] | take #1 and tell me how many variants it's written as. | #1 variant count | count_variants:#1 | `{'sig1': ['Engines & motors', '(none)', 'Replace']}` | Y |

## WTB30 — Ambiguous 'it' resolved by context
*Topology:* S then P · *Intent:* coreference ('it'=the replace/repair pattern; 'they'=bearings) · *Transition:* analogical follow-up

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Bearings — replace or repair, mostly? | bearings replace vs repair | count:bR∥count:bP | `{'bearing': {'replace': 9, 'repair': 1}}` |  |
| 2 | [follow] | and is it the same story for the housings they sit in? | same for housings | count:hR∥count:hP | `{'housing': {'replace': 7, 'repair': 4}}` |  |

## WTB31 — Counting with a moving filter
*Topology:* S progressive · *Intent:* coreference (progressive AND filters) · *Transition:* stacking filters across turns

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | How many faults total? | total faults | count:fault | `{'n': 558}` |  |
| 2 | [follow] | now only the ones on protective gear. | +protective gear | filter:ProtectingObject@set | `{'n': 75}` |  |
| 3 | [follow] | now only those we replaced. | +replaced | filter:Replace@set | `{'n': 3}` |  |

## WTB32 — Parallel then conditional branch
*Topology:* S then Selection · *Intent:* coreference ('it'=the share) · *Transition:* embedded conditional in a follow-up

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | What share of replacements are breakdown-driven? | breakdown share of replacements | count:replace∥count:replace&fault>ratio | `{'share': 0.27}` |  |
| 2 | [follow] | if it's over a third, show me the worst component; if not, just say it's fine. | branch: if>1/3 worst else 'fine' | select | `{'branch': 'fine', 'worst': None}` |  |

## WTB33 — Re-scope after a wrong assumption
*Topology:* S · *Intent:* coreference ('its') · *Transition:* clarify forces a representation change (asset->class)

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Which asset fails most? | which asset fails most (tags junk) | attempt:group:tag | `{'note': 'tags unreliable'}` | Y |
| 2 | [clarify] | oh the tags are junk — do it by equipment type from the text instead. | pivot to text-class | group:object_class | `{'top': ['Lines & drives', 107]}` |  |
| 3 | [follow] | good, now its top failure mode. | its top mode | filter:top>group:fault>rank:1 | `{'top_mode': 'Failed/broken'}` |  |

## WTB34 — Terse expert
*Topology:* S · *Intent:* coreference (ordinal '#2') · *Transition:* extremely terse, elliptical

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | replace counts by class, desc. | replace counts by class desc | group:object>rank | `{'ranked': [['Lines & drives', 89], ['Engines & motors', 44], ['Structural/mounting parts', 36], ['Pumps/fans/generators', 29], ['Valves/breakers/switches', 19] …` |  |
| 2 | [follow] | top3 only. | top3 | index:1..3 | `{'top3': [['Lines & drives', 89], ['Engines & motors', 44], ['Structural/mounting parts', 36]]}` |  |
| 3 | [follow] | #2's fault mix. | #2 fault mix | filter:#2>group:fault | `{'second': 'Engines & motors', 'fault_mix': {'Active failure (leak/overheat)': 7, 'Failed/broken': 5}}` |  |

## WTB35 — Two metrics, pick by user value
*Topology:* P then S · *Intent:* coreference ('the messy one','its') · *Transition:* user re-weights the metric

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Most-failing component — give me both raw count and failure variety. | most-failing: count & variety (parallel) | rank:count:1∥rank:variety:1 | `{'by_count': ['Lines & drives', 107], 'by_variety': ['Filters & separators', 5]}` |  |
| 2 | [clarify] | I care more about variety, that's the messy one. | choose variety; no tool | — (no tool call) | `—` |  |
| 3 | [follow] | so which is it, and what are its modes? | its modes | filter:variety_winner>list:fault | `{'modes': ['Faulty', 'Active failure (leak/overheat)', 'Failed/broken', 'Worn/degraded', 'Defect (crack/hole/noise)']}` |  |

## WTB36 — Inspection -> fix chain, with aside
*Topology:* S then S · *Intent:* coreference ('that') · *Transition:* approving aside

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | How often do we inspect then fix in the same job? | inspect-then-fix same job | count:inspect&remedy | `{'n': 7}` |  |
| 2 | [chat] | that's the good kind of job. | no tool | — (no tool call) | `—` |  |
| 3 | [follow] | on what equipment does that happen most? | on what equipment most | group:object@set>rank:1 | `{'top': ['Guards & protective parts', 3]}` |  |

## WTB37 — Compare and then combine differently
*Topology:* S then S · *Intent:* coreference (the per-type table feeds 'which') · *Transition:* progressive granularity

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Reactive vs proactive split overall. | overall reactive vs proactive | count:reactive∥count:proactive | `{'reactive': 83, 'proactive': 146}` |  |
| 2 | [follow] | now per equipment type. | per equipment type | group:object | `{'per_class': [['Valves/breakers/switches', 0.92], ['Sensors & gauges', 0.8], ['Lines & drives', 0.7], ['Covers & seals', 0.67], ['Displays & alarms', 0.5]]}` |  |
| 3 | [follow] | which type is most reactive? | most reactive type | argmax:share | `{'most_reactive': ['Valves/breakers/switches', 0.92]}` |  |

## WTB38 — Distractor numbers
*Topology:* S · *Intent:* coreference ('that') · *Transition:* clarify what 'number' means (data-quality angle)

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | How many jobs mention a number like a quantity? | jobs mentioning a number | search:number | `{'raw': 'ambiguous'}` | Y |
| 2 | [clarify] | I mean the masked <num> placeholders, those carry no info. | mean <num> placeholders; no tool | — (no tool call) | `—` |  |
| 3 | [follow] | what fraction of all jobs is that? | fraction of all | count:placeholder>ratio | `{'placeholder_WOs': 126, 'pct': 11.7}` |  |

## WTB39 — Multi-component stocking plan
*Topology:* P then S · *Intent:* coreference ('the unplanned ones') · *Transition:* parallel then split then filter

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Top wear items by replacement: bearings, seals, belts, filters — counts. | top wear items by replacement (parallel) | count:bearing∥count:seal∥count:belt∥count:filter | `{'counts': {'bearing': 9, 'seal': 7, 'belt': 56, 'filter': 12}}` |  |
| 2 | [follow] | which are unplanned (failure) demand vs plannable? | unplanned vs plannable | split:failed@4 | `{'unplanned': {'bearing': 0, 'seal': 1, 'belt': 15, 'filter': 2}}` |  |
| 3 | [follow] | just the unplanned ones, ranked. | unplanned only, ranked | rank:unplanned | `{'ranked': [['belt', 15], ['filter', 2], ['seal', 1], ['bearing', 0]]}` |  |

## WTB40 — User changes the question after seeing data
*Topology:* S · *Intent:* coreference ('it'); intent pivot mode->component · *Transition:* user pivots dimension after seeing results

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Show the failure-mode pareto. | failure-mode pareto | group:fault>rank | `{'pareto': [['Failed/broken', 215], ['Faulty', 178], ['Active failure (leak/overheat)', 146], ['Worn/degraded', 45], ['Defect (crack/hole/noise)', 32]]}` |  |
| 2 | [follow] | hmm, actually forget modes — redo it for components. | pivot: redo for components | group:object>rank | `{'top_component': ['Lines & drives', 107]}` |  |
| 3 | [follow] | top one, and is it mostly outright failure? | top one mostly outright failure? | filter:top>failed_share | `{'failed_share': 0.47}` |  |

## WTB41 — Parallel sanity check
*Topology:* P then verify · *Intent:* coreference ('the two') · *Transition:* compute-two-then-cross-check

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Give me replacements by class, and also class totals by activity. | replace by class & class by activity (parallel) | group:object∥group:activity | `{'replace_total': 349, 'activity_replace': 349}` |  |
| 2 | [follow] | do the replacement totals reconcile across the two? | reconcile | assert_equal | `{'reconciles': True}` |  |

## WTB42 — Chat reveals scope
*Topology:* S · *Intent:* long-range scope in chat; then user flags it's unsplittable · *Transition:* constraint then self-doubt

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [chat] | We're only responsible for the mobile fleet, not fixed plant. | scope: mobile fleet only; no tool | — (no tool call) | `—` |  |
| 2 | [task] | With that, what's our most-replaced component? | most-replaced component (overall; no mobile/fixed field) | rank:replace:1 | `{'top': [['Lines & drives', 89]]}` | Y |
| 3 | [clarify] | though honestly we can't split mobile vs fixed from this data, can we? | confirm cannot split mobile/fixed; no tool | — (no tool call) | `—` |  |

## WTB43 — Stacked superlatives
*Topology:* S chain · *Intent:* coreference chain ('its','that') 3 deep · *Transition:* nested superlatives

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Worst component. | worst component | rank:fault_class:1 | `{'worst': ['Lines & drives', 107]}` |  |
| 2 | [follow] | its worst fault. | its worst fault | filter:top>group:fault>rank:1 | `{'worst_fault': 'Failed/broken'}` |  |
| 3 | [follow] | the worst (most-skewed) fix for that fault. | most-skewed fix for that fault | filter:fault>remedy>argmax_share | `{'fix': 'Replace', 'share': 0.93}` |  |

## WTB44 — Two unrelated tasks then a join
*Topology:* P then synthesise · *Intent:* coreference ('those','the gap') · *Transition:* two tasks then an interpretive follow

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Count diagnose-only jobs. | diagnose-only count | count:diagnose_only | `{'diagnose_only': 18}` |  |
| 2 | [task] | Count replace jobs with no diagnosis. | replace-without-diagnosis count | count:replace_no_diag | `{'replace_no_diag': 51}` |  |
| 3 | [follow] | what does the gap between those say about our RCA habit? | interpret the gap (RCA habit) | synthesise | `{'gap': 33}` | Y |

## WTB45 — Resolve 'the usual' from data
*Topology:* S then S · *Intent:* coreference ('that change'=the remedy) · *Transition:* 'usual' = modal remedy

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | What's the usual fix when a sensor plays up? | usual fix when a sensor plays up | filter:sensor_fault>remedy>argmax | `{'usual': 'Replace'}` |  |
| 2 | [follow] | and when it's fully failed, does that change? | when fully failed, does it change | filter:sensor_failed>remedy>argmax | `{'when_failed': 'Replace'}` |  |

## WTB46 — Parallel across three faults + pick
*Topology:* P then argmax · *Intent:* coreference ('which fault') · *Transition:* 3 parallel then a selection by replace-share

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | For seized, leaking, and cracked — what's the dominant remedy each? | dominant remedy for seized/leaking/cracked (parallel) | remedy:seized∥remedy:leaking∥remedy:cracked | `{'dominant': {'seized': 'Replace', 'leaking': 'Replace', 'cracked': 'Repair'}}` |  |
| 2 | [follow] | which fault is the most 'just replace it' one? | most 'just replace it' fault | argmax:replace_share | `{'most_replace': 'seized', 'share': 0.88}` |  |

## WTB47 — Long callback after detour
*Topology:* S, S, S · *Intent:* long-range callback to valves across a detour task · *Transition:* topic switch and return

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Most common job on valves? | most common job on valves | filter:valve>activity>rank:1 | `{'valve_top': 'Replace'}` |  |
| 2 | [chat] | valves everywhere in this plant. | no tool | — (no tool call) | `—` |  |
| 3 | [task] | Different thing: how many jobs have no object recorded? | jobs with no object (distractor) | count:no_object | `{'no_object': 30}` |  |
| 4 | [follow] | and back to valves — what's the second most common job there? | back to valves: 2nd most common | index:2@valve | `{'valve_second': 'Repair'}` |  |

## WTB48 — Conditional on data availability
*Topology:* Selection then S · *Intent:* coreference ('the top mode') · *Transition:* user pre-authorises a fallback branch

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Trend our failures over time. | trend over time (no date field) | attempt:trend | `{'date_field': 'absent'}` | Y |
| 2 | [clarify] | if there's no date field, just give me the static failure-mode breakdown instead. | fallback authorised: static breakdown; no tool | — (no tool call) | `—` |  |
| 3 | [follow] | and flag the top mode. | static failure-mode breakdown + flag top | group:fault>rank>flag:1 | `{'breakdown': [['Failed/broken', 215], ['Faulty', 178], ['Active failure (leak/overheat)', 146], ['Worn/degraded', 45], ['Defect (crack/hole/noise)', 32]], 'top …` |  |

## WTB49 — Build then critique own answer
*Topology:* S then reflect · *Intent:* coreference ('it'=the headline) · *Transition:* self-critique follow-up

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Give me a one-line reliability headline from the data. | one-line reliability headline | compose:top_class+mode+reactive% | `{'top': 'Lines & drives', 'mode': 'Failed/broken', 'reactive_pct': 35.7}` | Y |
| 2 | [follow] | now poke holes in it — what's the weakest assumption? | critique its weakest assumption | reflect | `{'caveat': 'no time/cost/asset identity in data'}` | Y |
| 3 | [chat] | fair. | no tool | — (no tool call) | `—` |  |

## WTB50 — Everything, prioritised, your call
*Topology:* S (long-horizon) · *Intent:* coreference ('it'); clarify defines the metric · *Transition:* open mandate then metric clarify then structured output

| # | turn | dialogue | resolved intent | optimal tool plan | gold result | judge |
|---|---|---|---|---|---|---|
| 1 | [task] | Scan the lot. Tell me the single most important reliability action. | single most important action (open) | scan | `{'await_metric': True}` | Y |
| 2 | [clarify] | 'important' = biggest failure burden, since we've no cost data. | metric=failure burden; no tool | — (no tool call) | `—` |  |
| 3 | [follow] | name the component, the evidence, and the one task you'd add. | component+evidence+one task | rank:burden:1>compose | `{'target': 'Lines & drives', 'fault_WOs': 107, 'failed_share': 0.47}` | Y |
