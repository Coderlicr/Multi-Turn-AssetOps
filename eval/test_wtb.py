from copy import deepcopy

from eval.wtb_scenarios import GOLD_FILE, WTB_SCENARIOS, load_wtb_gold
from eval.wtb_score import load_agent_trace, score_dialog
from eval.wtb_tool_policy import ALLOWED_TOOLS
from src.servers.maintie import tools as maintie_tools


def test_wtb_scenarios_are_complete_and_aligned():
    assert len(WTB_SCENARIOS) == 50
    assert sum(len(scenario["turns"]) for scenario in WTB_SCENARIOS) == 152
    assert WTB_SCENARIOS[0]["id"] == 1
    assert WTB_SCENARIOS[0]["scenario_id"] == "WTB01"
    assert WTB_SCENARIOS[-1]["id"] == 50
    assert WTB_SCENARIOS[-1]["scenario_id"] == "WTB50"
    assert all("[task]" not in turn for scenario in WTB_SCENARIOS for turn in scenario["turns"])


def test_perfect_trace_scores_one():
    gold = [
        {"tools": [["a", "b"]], "result": {"n": 2}, "judge": False},
        {"tools": [], "result": None, "judge": False},
    ]
    agent = deepcopy(gold)
    score = score_dialog(agent, gold)
    assert score["optimal_path_rate"] == 1.0
    assert score["accomplish_progress_rate"] == 1.0
    assert score["no_tool_decision_accuracy"] == 1.0


def test_parallel_order_does_not_matter_but_serial_order_does():
    gold = [{"tools": [["a", "b"]], "result": None, "judge": False}]
    assert score_dialog([{"tools": [["b", "a"]]}], gold)["optimal_path_rate"] == 1.0
    assert score_dialog([{"tools": [["a"], ["b"]]}], gold)["optimal_path_rate"] == 0.0


def test_parallel_duplicate_calls_are_not_collapsed():
    gold = [{"tools": [["count", "count"]], "result": None, "judge": False}]
    assert score_dialog([{"tools": [["count", "count"]]}], gold)["optimal_path_rate"] == 1.0
    assert score_dialog([{"tools": [["count"]]}], gold)["optimal_path_rate"] == 0.0


def test_equivalent_real_tool_plan_is_accepted():
    gold = [{
        "tools": [["count", "count"]],
        "accepted_tool_plans": [
            [["count", "count"]],
            [["group_count"]],
        ],
        "result": None,
        "judge": False,
    }]
    score = score_dialog([{"tools": [["maintie.group_count"]]}], gold)
    assert score["optimal_path_rate"] == 1.0


def test_wtb_opr_policy_uses_only_real_maintie_tools():
    gold = load_wtb_gold(GOLD_FILE)
    for turns in gold.values():
        for turn in turns:
            assert "reasoning_plan" in turn
            for plan in turn["accepted_tool_plans"]:
                assert all(tool in ALLOWED_TOOLS for group in plan for tool in group)


def test_opr_allowlist_exactly_matches_maintie_server_tools():
    exposed = {
        tool.__name__
        for tool in (
            maintie_tools.search,
            maintie_tools.extract,
            maintie_tools.count,
            maintie_tools.group_count,
            maintie_tools.rank,
            maintie_tools.get_text,
            maintie_tools.compare,
        )
    }
    assert ALLOWED_TOOLS == exposed


def test_local_followup_computation_requires_no_external_tool():
    gold = load_wtb_gold(GOLD_FILE)
    # WTB20 turn 3 asks for the second item from the already returned ranking.
    assert gold["WTB20"][2]["reasoning_plan"] == [["index:2"]]
    assert gold["WTB20"][2]["tools"] == []


def test_missing_turn_is_not_dropped_from_apr_denominator():
    gold = [
        {"tools": [["a"]], "result": {"n": 1}, "judge": False},
        {"tools": [["b"]], "result": {"n": 2}, "judge": False},
    ]
    score = score_dialog([{"tools": [["a"]], "result": {"n": 1}}], gold)
    assert score["accomplish_progress_rate"] == 0.5
    assert score["missing_turns"] == 1


def test_missing_no_tool_turn_is_not_scored_as_a_correct_path():
    gold = [{"tools": [], "result": None, "judge": False}]
    score = score_dialog([], gold)
    assert score["optimal_path_rate"] == 0.0
    assert score["no_tool_decision_accuracy"] == 0.0


def test_extra_turn_is_penalized_in_path_rate():
    gold = [{"tools": [], "result": None, "judge": False}]
    agent = [{"tools": []}, {"tools": [["extra"]]}]
    score = score_dialog(agent, gold)
    assert score["optimal_path_rate"] == 0.5
    assert score["extra_turns"] == 1


def test_judge_turn_is_not_counted_as_exact_result_apr():
    gold = [{"tools": [["compose"]], "result": {"target": "x"}, "judge": True}]
    score = score_dialog([{"tools": [["compose"]], "result": {"target": "wrong"}}], gold)
    assert score["accomplish_progress_rate"] is None
    assert score["compute_turns"] == 0


def test_load_agent_trace_accepts_supervisor_jsonl(tmp_path):
    trace = tmp_path / "agent.jsonl"
    trace.write_text(
        '{"question":"q1","tools":[["maintie.count"]],"result":{"count":1}}\n'
        '{"question":"q2","tools":[],"result":{"value":"x"}}\n',
        encoding="utf-8",
    )
    assert load_agent_trace(trace) == [
        {
            "question": "q1",
            "tools": [["maintie.count"]],
            "result": {"count": 1},
        },
        {"question": "q2", "tools": [], "result": {"value": "x"}},
    ]


def test_load_agent_trace_keeps_legacy_json_array(tmp_path):
    trace = tmp_path / "agent.json"
    trace.write_text('[{"tools": [], "result": null}]', encoding="utf-8")
    assert load_agent_trace(trace) == [{"tools": [], "result": None}]


def test_apr_accepts_structured_presentation_aliases_but_not_wrong_values():
    gold = [
        {
            "tools": [],
            "result": {"replace": 347, "repair": 127},
            "judge": False,
        }
    ]
    equivalent = [{"tools": [], "result": {"replacements": 347, "repairs": 127}}]
    swapped = [{"tools": [], "result": {"replacements": 127, "repairs": 347}}]

    assert score_dialog(equivalent, gold)["result_correct"] == 1
    assert score_dialog(swapped, gold)["result_correct"] == 0


def test_apr_accepts_pair_list_remedy_and_extra_evidence_fields():
    gold = [
        {
            "tools": [],
            "result": {"bearing": {"fault": 10, "remedy": {"Replace": 9}}},
            "judge": False,
        }
    ]
    agent = [
        {
            "tools": [],
            "result": {
                "bearing": {
                    "work_orders": 28,
                    "fault_work_orders": 10,
                    "activities": [["Replace", 9]],
                }
            },
        }
    ]

    assert score_dialog(agent, gold)["result_correct"] == 1


def test_apr_normalizes_count_rank_and_selected_item_presentations():
    cases = [
        ({"count": 107}, {"n": 107}, True),
        (
            {"object_class": "Lines & drives", "count": 89},
            {"top": [["Lines & drives", 89]]},
            True,
        ),
        ({"seal": {"fault_work_orders": 14}}, {"worse": "seal"}, True),
        ({"selected": "seal"}, {"worse": "seal"}, True),
        ({"count": 106}, {"n": 107}, False),
    ]
    for actual, expected, matches in cases:
        score = score_dialog(
            [{"tools": [], "result": actual}],
            [{"tools": [], "result": expected, "judge": False}],
        )
        assert (score["result_correct"] == 1) is matches
