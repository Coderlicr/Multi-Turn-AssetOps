# WTB50 real-tool OPR policy

The original `tools` values in `wtb_ground_truth.json` are compact reasoning
sketches.  They describe computations such as filtering, taking an index,
merging prior results, or composing a narrative.  They are retained as
`reasoning_plan` for auditability, but they are not all external tool calls.

Formal Optimal Path Rate (OPR) is computed by `eval/wtb_tool_policy.py` and
`eval/wtb_score.py` against only the seven tools exposed by the MaintIE MCP
server:

`search`, `extract`, `count`, `group_count`, `rank`, `get_text`, `compare`.

Policy rules:

1. Local operations over results already present in dialog memory do not count
   as MCP calls.  This includes indexing, cumulative sums, argmax, merging,
   humanising labels, branching, equality checks, synthesis, reflection, and
   narrative composition.
2. Parallel groups preserve duplicate calls.  Two parallel `count` calls are
   different from one `count` call.
3. When the general-purpose server supports more than one equally efficient
   solution, the scorer accepts each explicitly listed equivalent path.  For
   example, two independent counts and one grouped aggregation can both be
   accepted when both return the required evidence.
4. Tool-name order inside one parallel group is ignored; sequential group order
   is preserved.
5. Result correctness remains separately measured by APR, so accepting an
   equivalent tool topology does not excuse incorrect filters, arguments, or
   answers.

The scenario wording and fixed numeric results are unchanged by this policy.
