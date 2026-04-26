# Multi-Turn Dialog Scenarios

for AssetOpsBench Closed-Loop Agent Framework

*16 Multi-Turn Dialog Scenarios Covering Fault Diagnosis, Predictive Maintenance, Operational Planning, and Full Lifecycle Management*

## **Design Rationale**

These 16 multi-turn dialog scenarios are designed to evaluate the proposed closed-loop agent architecture across the full spectrum of industrial asset operations. They are derived from the 152 single-turn scenarios in the AssetOpsBench dataset, composed into realistic multi-turn workflows that reflect how end users (maintenance engineers, facility planners, reliability specialists) actually interact with industrial AI systems.

### **Design Principles**

1\. User Intent vs. Technical Terms: Each dialog begins with a natural-language user intent (not technical tool calls), reflecting the professor's guidance that end users use intent while SMEs use technical terms. The system translates intent into workflow steps and MCP tool calls internally.

2\. Progressive Complexity: Dialogs range from 3-turn discovery tasks to 5-turn full-pipeline workflows, testing different aspects of the closed-loop architecture.

3\. Cross-Domain Coordination: Most dialogs require multiple tool domains (IoT, FMSR, TSFM, WO) to be orchestrated together, testing the supervisor-specialist architecture.

4\. Validation & Recovery: Several dialogs include scenarios where initial plans fail or intermediate results require re-planning, testing the closed-loop recovery mechanism.

5\. Realistic Industrial Workflows: Scenarios cover the key workflows identified in the proposal: fault diagnosis, predictive maintenance, comparative analysis, operational planning, and strategic asset management.

### **Coverage Summary**

| Category | Dialog IDs | Count |
| :---- | :---- | :---- |
| Fault Diagnosis | 1, 5, 13, 16 | 4 |
| Predictive Maintenance | 3, 8 | 2 |
| Comparative Analysis | 2 | 1 |
| Maintenance Planning | 4, 10, 12 | 3 |
| Operational Monitoring | 7, 14 | 2 |
| Knowledge Discovery / Onboarding | 6 | 1 |
| System Configuration | 11 | 1 |
| Full Pipeline (End-to-End) | 9, 15 | 2 |

### **MCP Tool Domain Coverage**

| Tool Domain | Appears In Dialogs | Frequency |
| :---- | :---- | :---- |
| IoT | 1,2,3,5,6,7,8,9,10,11,12,13,14,15,16 | 15/16 |
| TSFM | 1,2,3,5,6,7,8,9,10,11,12,13,14,15,16 | 15/16 |
| FMSR | 1,2,3,5,6,7,8,9,10,12,13,14,15,16 | 14/16 |
| WO | 3,4,5,8,9,10,11,12,13,14,15 | 11/16 |


## **Dialog 1: Temperature Anomaly Diagnosis & Remediation Recommendation**

| Category | Fault Diagnosis \+ Maintenance |
| :---- | :---- |
| **Complexity** | High (4 turns, cross-domain) |
| **Tool Domains Involved** | IoT, TSFM, FMSR |
| **Key Capabilities** | Anomaly detection, failure mode reasoning, root cause analysis, remediation recommendation |
| **Related Scenarios** | \#8, \#9, \#101-102, \#216, \#430 |

 
| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | The temperature of our chiller at Site MAIN seems unusually high lately. Can you look into it? |   |
| 1 | System | Calls IoT tools: `sites`, `assets(MAIN)`, `sensors(MAIN, Chiller 6)`. Identifies temperature sensors (Supply Temperature, Return Temperature, Condenser Water Return To Tower Temperature) for the chiller. | IoT |
| 2 | System | Uses IoT `history_csv` to retrieve the past month of Chiller 6 data as CSV, then runs TSFM `run_integrated_tsad` on the Supply Temperature column. Result: abnormal temperature spike detected starting 2020-06-15. | IoT, TSFM |
| 3 | User | What could be causing this temperature spike? |   |
| 3 | System | Calls FMSR tools: `get_failure_modes(Chiller 6)`, `get_failure_mode_sensor_mapping(...)`. Maps temperature sensors to failure modes. Possible causes: Compressor Overheating, Condenser Water side fouling, Evaporator Water side fouling. | FMSR |
| 4 | User | Which cause is most likely given the sensor data patterns? |   |
| 4 | System | Cross-references anomaly patterns across multiple sensors. Chiller Efficiency (kW/ton) has degraded 15–20% while condenser water flow rate shows reduced throughput. Compressor power draw has increased, consistent with elevated head pressure as the compressor works harder to reject heat across a fouled heat exchanger surface. Condenser water return temperature is within normal range (ruling out a cooling tower or shared loop issue). Pattern is most consistent with Condenser Water side fouling. Confidence: Moderate (60–70%) — evaporator fouling cannot be fully ruled out without further sensor validation. | FMSR, TSFM |

### **Ground Truth**

**Characteristic Form**
The agent begins by identifying the asset and its sensors using `sites()`, `assets("MAIN")`, and `sensors("MAIN", "Chiller 6")`. It then retrieves historical data via `history_csv("MAIN", "Chiller 6", start, final)` and detects anomalies using `run_integrated_tsad` on the Supply Temperature column. When asked for causes, the agent calls `get_failure_modes("Chiller 6")` and `get_failure_mode_sensor_mapping(...)` to enumerate candidate failure modes. For root cause narrowing, it cross-references multi-sensor evidence: Chiller Efficiency degradation and elevated Condenser Water Return To Tower Temperature together should distinguish condenser fouling from compressor or evaporator causes. A correct response identifies Condenser Water side fouling as the most likely cause with calibrated confidence (not absolute certainty), and notes that evaporator fouling cannot be fully excluded without further inspection.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `sites()` → `assets("MAIN")` → `sensors("MAIN", "Chiller 6")` |
| 2 | `history_csv("MAIN", "Chiller 6", <start>, <final>)` → `run_integrated_tsad(csv_path, "timestamp", ["Chiller 6 Supply Temperature"])` |
| 3 | `get_failure_modes("Chiller 6")` → `get_failure_mode_sensor_mapping("Chiller 6", <failure_modes>, <sensors>)` |
| 4 | `csv_stats(<tsad_results_file>, ["anomaly_score", "Chiller 6 Chiller Efficiency", "Chiller 6 Condenser Water Return To Tower Temperature"])` |

**Success Criteria**

- [ ] Anomaly is detected on Supply Temperature with a specific onset period identified
- [ ] At least three candidate failure modes are surfaced from `get_failure_modes`
- [ ] Condenser Water side fouling is identified as the primary hypothesis
- [ ] Supporting evidence cites at least two sensors (e.g. Chiller Efficiency + Condenser Water Return To Tower Temperature)
- [ ] Confidence is stated as moderate/partial, not absolute; evaporator fouling is acknowledged as unresolved


## **Dialog 2: Cross-Asset Performance Comparison**

| Category | Comparative Analysis |
| :---- | :---- |
| **Complexity** | Medium (4 turns, multi-asset) |
| **Tool Domains Involved** | IoT, TSFM, FMSR |
| **Key Capabilities** | Multi-asset data retrieval, parallel analysis, comparative forecasting |
| **Related Scenarios** | \#10, \#47, \#216-219 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | I want to compare the efficiency of Chiller 6 and Chiller 9 at the MAIN site over the past month. |  |
| 1 | System | Calls IoT tools: `sensors(MAIN, Chiller 6)`, `sensors(MAIN, Chiller 9)`, then retrieves Chiller Efficiency and Tonnage using `history_csv` for both assets. Presents a side-by-side comparison summary. | IoT |
| 2 | User | Which one is degrading faster? |  |
| 2 | System | Runs TSFM forecasting on both efficiency time series using `run_tsfm_forecasting`. Chiller 6 shows a steeper decline trend (-2.3% per week) compared to Chiller 9 (-0.5% per week). Chiller 6 is degrading significantly faster. | TSFM |
| 3 | User | Can you forecast what their efficiency will look like in 2 weeks? |  |
| 3 | System | Runs TSFM forecasting with 2-week horizon. Chiller 6 projected efficiency: 68% (currently 73%). Chiller 9 projected efficiency: 81% (currently 82%). Recommends prioritizing Chiller 6 for maintenance. | TSFM |
| 4 | User | What failure modes should I watch for on Chiller 6 given this trend? |  |
| 4 | System | Calls FMSR tools: `get_failure_modes(Chiller 6)` and `get_failure_mode_sensor_mapping(...)`, then correlates the efficiency drop with sensor patterns. Most relevant failure modes: (1) Evaporator Water side fouling — Confidence: Moderate (55–65%). Consistent with gradual efficiency loss pattern and load-dependent degradation; heat transfer surface becomes limiting at high loads. (2) Condenser Improper water side flow rate — Confidence: Low–Moderate (30–40%). Condenser water flow shows some reduction but delta-T is stable, partially ruling out flow restriction as the primary cause. Ruled out: Compressor overheating (power input within normal range); refrigerant loss (refrigerant temperatures stable). Recommend validating with evaporator approach temperature trend before scheduling maintenance. | FMSR |

### **Ground Truth**

**Characteristic Form**
The agent retrieves sensor data for both Chiller 6 and Chiller 9 in separate `history_csv` calls (the tool only supports one asset at a time). It runs `run_tsfm_forecasting` on each asset's Chiller Efficiency column to extract trend slopes and project future efficiency. A correct response identifies Chiller 6 as degrading faster with a steeper negative trend slope, provides a 2-week forecast for each, and then uses `get_failure_modes` and `get_failure_mode_sensor_mapping` to map the efficiency degradation pattern on Chiller 6 to likely failure modes. The response distinguishes between fouling (gradual load-correlated degradation) and flow restriction (delta-T would also change) and prioritizes Chiller 6 for maintenance.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `sensors("MAIN", "Chiller 6")` → `history_csv("MAIN", "Chiller 6", <start>, <final>)` → `sensors("MAIN", "Chiller 9")` → `history_csv("MAIN", "Chiller 9", <start>, <final>)` |
| 2 | `run_tsfm_forecasting(<chiller6_csv>, "timestamp", ["Chiller 6 Chiller Efficiency"])` → `run_tsfm_forecasting(<chiller9_csv>, "timestamp", ["Chiller 9 Chiller Efficiency"])` |
| 3 | `run_tsfm_forecasting(<chiller6_csv>, "timestamp", ["Chiller 6 Chiller Efficiency"], forecast_horizon=<2wk>)` → same for Chiller 9 |
| 4 | `get_failure_modes("Chiller 6")` → `get_failure_mode_sensor_mapping("Chiller 6", <failure_modes>, <sensors>)` |

**Success Criteria**

- [ ] Both assets' efficiency data are retrieved in separate `history_csv` calls
- [ ] Chiller 6 is correctly identified as degrading faster with a quantified rate difference
- [ ] A 2-week forecast is produced for both assets with numeric projected efficiency values
- [ ] At least two failure modes are identified for Chiller 6 with confidence levels
- [ ] Compressor overheating and refrigerant loss are ruled out with supporting sensor rationale


## **Dialog 3: Early Detection System Setup for Condenser Fouling**

| Category | Predictive Maintenance Setup |
| :---- | :---- |
| **Complexity** | High (5 turns, system design) |
| **Tool Domains Involved** | IoT, FMSR, TSFM, WO |
| **Key Capabilities** | Failure-sensor mapping, ML recipe generation, model tuning, monitoring setup |
| **Related Scenarios** | \#116, \#120, \#433-434 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | I want to set up an early detection system for condenser water side fouling on Chiller 9\. |  |
| 1 | System | Calls FMSR tools: `get_failure_modes(Chiller 9)` and `get_failure_mode_sensor_mapping(...)` to identify relevant sensors: Condenser Water Flow, Condenser Water Supply To Chiller Temperature, Chiller Efficiency, Supply Temperature. | FMSR |
| 2 | User | Which sensors should I prioritize for the detection model? |  |
| 2 | System | Based on FMSR analysis, recommends: primary indicators are Condenser Water Flow and Condenser Water Supply To Chiller Temperature. Secondary indicators: Chiller Efficiency and Power Input. Suggests an ML recipe with these as feature sensors and Condenser Water Flow as the target. | FMSR |
| 3 | User | Can you fine-tune a forecasting model using our historical data? |  |
| 3 | System | Uses IoT `history_csv` to export historical Chiller 9 data, then calls TSFM `run_tsfm_finetuning` with `timestamp` as the time column and `Chiller 9 Condenser Water Flow` as the target column. Model is fine-tuned and saved. Evaluation metrics are reported. | IoT, TSFM |
| 4 | User | Now run anomaly detection on the last two months of data to validate. |  |
| 4 | System | Calls IoT `history_csv` for Chiller 9 sensors over the last 2 months, then runs TSFM `run_integrated_tsad`. Results: 3 anomalous periods detected, correlating with known maintenance events. Detection system validated. | IoT, TSFM |
| 5 | User | Set up ongoing monitoring alerts for this. |  |
| 5 | System | Recommends monitoring configuration: threshold-based alerts on Condenser Water Flow deviation \> 2 sigma, periodic anomaly detection runs every 24 hours, escalation to maintenance review and work-order drafting when anomalies persist \> 48 hours. | TSFM, WO |

### **Ground Truth**

**Characteristic Form**
The agent starts with `get_failure_modes("Chiller 9")` and `get_failure_mode_sensor_mapping` to identify sensors relevant to condenser fouling. It correctly uses `Condenser Water Supply To Chiller Temperature` (not "Return To Tower", which is Chiller 6's sensor name). It then calls `history_csv` and `run_tsfm_finetuning` to adapt the TTM model on historical Chiller 9 data targeting the Condenser Water Flow column. Validation is done via `run_integrated_tsad` on the last 2 months of data, and the result should show detected anomaly periods correlated with known maintenance events. Final monitoring recommendation must include a sigma-based threshold, a detection cadence, and an escalation path to work order generation.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `get_failure_modes("Chiller 9")` → `sensors("MAIN", "Chiller 9")` → `get_failure_mode_sensor_mapping("Chiller 9", <failure_modes>, <sensors>)` |
| 2 | *(FMSR reasoning only — no additional tool call required)* |
| 3 | `history_csv("MAIN", "Chiller 9", <start>, <final>)` → `run_tsfm_finetuning(<csv_path>, "timestamp", ["Chiller 9 Condenser Water Flow"])` |
| 4 | `history_csv("MAIN", "Chiller 9", <2mo_start>, <final>)` → `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 9 Condenser Water Flow"])` |
| 5 | *(Recommendation synthesis — no additional tool call required)* |

**Success Criteria**

- [ ] Sensor mapping correctly uses `Chiller 9 Condenser Water Supply To Chiller Temperature` (not "Return To Tower")
- [ ] `run_tsfm_finetuning` is called with `Chiller 9 Condenser Water Flow` as the target column
- [ ] Anomaly detection on validation data returns at least one detected anomaly period
- [ ] Monitoring recommendation specifies a sigma threshold, a run cadence, and an escalation condition
- [ ] The system does not use Chiller 6's sensor names for Chiller 9


## **Dialog 4: Work Order History Review & Maintenance Optimization**

| Category | Maintenance Planning |
| :---- | :---- |
| **Complexity** | Medium (4 turns, single-domain deep) |
| **Tool Domains Involved** | WO |
| **Key Capabilities** | Work order retrieval, distribution analysis, bundling optimization, prediction |
| **Related Scenarios** | \#400-406, \#411, \#424 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | Show me the work order history for Chiller 9 (CWC04009) for 2017 through 2019\. |  |
| 1 | System | Calls WO tools to retrieve work orders for CWC04009 across 2017, 2018, 2019. Summarizes: total work orders, breakdown by corrective vs preventive, distribution by primary failure code. | WO |
| 2 | User | Are there any corrective work orders that could have been bundled together? |  |
| 2 | System | Analyzes corrective work orders for bundling opportunities within 2-week windows. Identifies 3 bundles: Bundle 1 (15 orders, Q1 2017), Bundle 2 (6 orders, Q3 2018), Bundle 3 (2 orders, Q2 2019). Bundling could have reduced downtime by an estimated 40%. | WO |
| 3 | User | Based on this history, what is the most likely next failure? |  |
| 3 | System | Calls WO `predict_next_work_order` for CWC04009. Results: Freon Management (MT012) 20%, Electrical Maintenance (MT008) 20%, General Inspection (MT013) 20%. Even probability distribution suggests regular preventive cycles. | WO |
| 4 | User | Should I schedule a preventive maintenance window for next month? |  |
| 4 | System | Based on historical patterns and prediction, recommends scheduling a maintenance window. Suggested scope: Freon level check, electrical inspection, and general inspection can be bundled. Estimated duration: 2 days. | WO |

### **Ground Truth**

**Characteristic Form**
The agent calls `get_work_orders("Chiller 9", "2017-01-01", "2019-12-31")` to retrieve the 3-year work order history for CWC04009, then calls `get_work_order_distribution` to get the frequency breakdown by failure code. It identifies bundling opportunities by analyzing corrective WO temporal clustering within 2-week windows. `predict_next_work_order("Chiller 9")` is called without date constraints to use full history for a meaningful probability distribution. A correct final recommendation bundles the top predicted failure types (Freon check, electrical, general inspection) into a single maintenance window, with an estimated duration.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `get_work_orders("Chiller 9", "2017-01-01", "2019-12-31")` → `get_work_order_distribution("Chiller 9", "2017-01-01", "2019-12-31")` |
| 2 | `get_corrective_work_orders("Chiller 9", "2017-01-01", "2019-12-31")` |
| 3 | `predict_next_work_order("Chiller 9")` |
| 4 | *(Recommendation synthesis — no additional tool call required)* |

**Success Criteria**

- [ ] Work order history is retrieved for the full 2017–2019 window
- [ ] At least two bundling opportunities are identified with approximate time windows
- [ ] `predict_next_work_order` is called with full history (no date constraints)
- [ ] Prediction result includes at least two failure code types with probabilities
- [ ] Final recommendation bundles at least two predicted failure types into one maintenance window


## **Dialog 5: Anomaly Surge Investigation (June 2021\)**

| Category | Incident Response |
| :---- | :---- |
| **Complexity** | High (4 turns, cross-domain investigation) |
| **Tool Domains Involved** | WO, IoT, TSFM, FMSR |
| **Key Capabilities** | Event retrieval, anomaly correlation, alert triage, root cause, remediation |
| **Related Scenarios** | \#405-406, \#420-421, \#431-432 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | I am reviewing operations for early July 2021\. How did Chiller 9 (CWC04009) perform in June 2021? |  |
| 1 | System | Calls WO `get_events` for CWC04009 in June 2021. Retrieves work order events from `wo_events` table and alert trigger records from `alert_events` table (coverage: 2021-01-01 to 2022-09-09). Summary: 3 work order events, multiple Chiller - Evaporator Approach High alert triggers, anomaly events across Cooling Load, Flow Efficiency, Delta Setpoint, Delta Temperature. | WO |
| 2 | User | That is a lot of alerts. Which ones are meaningful vs. spurious? |  |
| 2 | System | Analyzes alert patterns from `alert_events`. The Evaporator Approach High alerts are persistent across the month, strongly indicating a real issue rather than noise. Cross-references `alert_rule_fc_mapping` to confirm the rule (RUL0018 - Chiller - Evaporator Approach High) maps to evaporator-related failure codes. The co-occurrence of multiple KPI anomalies reinforces a genuine equipment issue. | WO |
| 3 | User | What is the root cause based on the sensor data? |  |
| 3 | System | Calls IoT `history_csv` for Chiller 9 key sensors in June 2021, runs TSFM `run_integrated_tsad`, then uses FMSR `get_failure_modes` and `get_failure_mode_sensor_mapping` to map anomaly patterns to failure modes. The sustained Evaporator Approach High pattern combined with Flow Efficiency anomalies points to Evaporator Water side fouling as the most likely root cause — Confidence: Moderate (55–65%). Supporting evidence: approach anomalies are strongly load-correlated (87% occur during high cooling loads), efficiency degradation worsens at peak demand, flow rates are within normal range (ruling out pump or valve issues). Secondary concern: Possible low refrigerant charge (Confidence: 25–30%) — refrigerant evaporator temperatures show slight downward drift under high load, which is not fully explained by fouling alone. Recommend inspecting evaporator tubes first; if efficiency does not recover, escalate to refrigerant charge inspection. | IoT, TSFM, FMSR |
| 4 | User | Were any corrective work orders already created for this? |  |
| 4 | System | Calls WO `get_corrective_work_orders` for CWC04009 in June 2021. Found 1 corrective work order (MT010 - general corrective). However, it does not specifically address evaporator fouling. A targeted work-order draft is recommended. | WO |

### **Ground Truth**

**Characteristic Form**
The agent queries `get_events("Chiller 9", "2021-06-01", "2021-06-30")` to retrieve the event log, then calls `get_alert_rules("Chiller 9")` to identify which alert rules have been triggered. It should surface RUL0018 (Chiller - Evaporator Approach High) as an active rule, then call `analyze_alert_to_failure("Chiller 9", "RUL0018")` to assess transition probability to work order. Sensor-based root cause analysis combines `history_csv` with `run_integrated_tsad` and `get_failure_mode_sensor_mapping`. A correct response confirms evaporator fouling as the primary hypothesis with load-correlated evidence, acknowledges refrigerant undercharge as a secondary concern, and verifies that the existing corrective WO (MT010) does not target the identified fault.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `get_events("Chiller 9", "2021-06-01", "2021-06-30")` → `get_alert_rules("Chiller 9")` |
| 2 | `analyze_alert_to_failure("Chiller 9", "RUL0018")` |
| 3 | `history_csv("MAIN", "Chiller 9", "2021-06-01", "2021-06-30")` → `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 9 Chiller Efficiency", "Chiller 9 Condenser Water Flow"])` → `get_failure_modes("Chiller 9")` → `get_failure_mode_sensor_mapping(...)` |
| 4 | `get_corrective_work_orders("Chiller 9", "2021-06-01", "2021-06-30")` |

**Success Criteria**

- [ ] `get_alert_rules` is called and RUL0018 (Evaporator Approach High) is identified
- [ ] Alert analysis uses data from the 2021 window (not 2020)
- [ ] Root cause analysis identifies evaporator fouling as primary with load-correlation evidence
- [ ] Refrigerant undercharge is acknowledged as a secondary concern
- [ ] Existing corrective WO is confirmed to not target evaporator fouling specifically


## **Dialog 6: Sensor Exploration & Capability Discovery**

| Category | Knowledge Query / Onboarding |
| :---- | :---- |
| **Complexity** | Low (3 turns, discovery-focused) |
| **Tool Domains Involved** | IoT, FMSR, TSFM |
| **Key Capabilities** | System discovery, sensor listing, capability enumeration |
| **Related Scenarios** | \#1-4, \#44, \#104-105, \#201-210 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | I am new to this system. What sites and assets are available for monitoring? |  |
| 1 | System | Calls IoT tools: `sites`, `assets(MAIN)`. Lists all assets currently available in the imported dataset, including Chiller 3, Chiller 4, Chiller 6, and Chiller 9. | IoT |
| 2 | User | What sensors does Chiller 6 have, and what kinds of analysis can I run on the data? |  |
| 2 | System | Calls IoT `sensors(MAIN, Chiller 6)`. Lists 10 sensors: % Loaded, Efficiency, Condenser Water Flow, Condenser Water Return To Tower Temperature, etc. Calls TSFM tools `get_ai_tasks` and `get_tsfm_models`: supported analyses include time series forecasting, anomaly detection, and model fine-tuning. | IoT, TSFM |
| 3 | User | What failure modes can be detected using these sensors? |  |
| 3 | System | Calls FMSR tools: `get_failure_modes(Chiller 6)`, `get_failure_mode_sensor_mapping(...)`. Maps sensors to detectable failures: Compressor Overheating (via Power Input, Supply Temperature), Evaporator Water side fouling (via Efficiency, Return Temperature), Condenser Water side fouling (via Condenser Water Flow), etc. | FMSR |

### **Ground Truth**

**Characteristic Form**
This is a deterministic discovery dialog. The agent calls `sites()`, then `assets("MAIN")`, which must return exactly the four assets in the IoT database: Chiller 3, Chiller 4, Chiller 6, Chiller 9. It calls `sensors("MAIN", "Chiller 6")` to retrieve the 10 sensors, then `get_ai_tasks()` and `get_tsfm_models()` to enumerate analytical capabilities. Finally it calls `get_failure_modes("Chiller 6")` and `get_failure_mode_sensor_mapping(...)` to produce the sensor-to-failure-mode map. A correct response lists all 4 assets, all 10 Chiller 6 sensors by exact name, and maps at least 3 distinct failure modes to specific sensors.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `sites()` → `assets("MAIN")` |
| 2 | `sensors("MAIN", "Chiller 6")` → `get_ai_tasks()` → `get_tsfm_models()` |
| 3 | `get_failure_modes("Chiller 6")` → `get_failure_mode_sensor_mapping("Chiller 6", <failure_modes>, <sensors>)` |

**Success Criteria**

- [ ] `assets("MAIN")` returns exactly: Chiller 3, Chiller 4, Chiller 6, Chiller 9
- [ ] All 10 Chiller 6 sensors are listed by their exact database names (e.g. "Chiller 6 Chiller Efficiency")
- [ ] TSFM capabilities include at minimum: forecasting, anomaly detection, fine-tuning
- [ ] At least 3 failure modes are mapped to specific sensors
- [ ] Response does not reference Chiller 5, 7, or 8 as available IoT assets


## **Dialog 7: Chiller Power Consumption Investigation**

| Category | Operational Monitoring |
| :---- | :---- |
| **Complexity** | Medium (4 turns, mixed query types) |
| **Tool Domains Involved** | IoT, TSFM, FMSR |
| **Key Capabilities** | Specific data retrieval, trend analysis, forecasting, failure reasoning |
| **Related Scenarios** | \#43, \#45, \#46, \#48 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | How much power was Chiller 3 using at the MAIN site on June 14, 2020? |  |
| 1 | System | Calls IoT `history(MAIN, Chiller 3, start, final)` for Chiller 3 Power Input on June 14, 2020 at MAIN site. Returns power consumption values for the day. Average power consumption: X kW. | IoT |
| 2 | User | Has the power consumption been trending up recently? Check the past month. |  |
| 2 | System | Calls IoT `history_csv` for Chiller 3 Power Input over the past month, then runs TSFM `run_tsfm_forecasting` to identify trend. Result: power consumption has increased 12% over the past month, with an accelerating upward trend in the last 2 weeks. | IoT, TSFM |
| 3 | User | Is this a sign of a potential failure? |  |
| 3 | System | Calls FMSR tools to analyze rising power draw for chiller assets. Increased power input with otherwise stable load can indicate compressor inefficiency, condenser-side fouling, or control instability. Recommends checking supply and return temperature differentials and efficiency trends for confirmation. | FMSR |
| 4 | User | Pull the supply and return temperatures for the same period and check for anomalies. |  |
| 4 | System | Calls IoT `history_csv` for Chiller 3 Supply Temperature and Chiller 3 Return Temperature over the same month, then runs TSFM `run_integrated_tsad` on both columns. Supply temperature shows normal range. Return temperature shows slight elevation. Combined with the power increase, the pattern is more consistent with degraded heat-transfer efficiency than with a control setpoint issue. | IoT, TSFM |

### **Ground Truth**

**Characteristic Form**
The agent calls `history("MAIN", "Chiller 3", "2020-06-14T00:00:00", "2020-06-14T23:45:00")` to get the single-day power consumption readings, then `history_csv("MAIN", "Chiller 3", <1mo_start>, <1mo_final>)` for the monthly trend. It runs `run_tsfm_forecasting` on the Power Input column to extract trend direction and slope. It then calls `get_failure_modes("Chiller 3")` to check whether rising power is a failure indicator. In Turn 4 it calls `history_csv` again for Supply and Return Temperature columns and runs `run_integrated_tsad` on both. A correct final synthesis identifies degraded heat-transfer efficiency (not control setpoint instability) as the most likely cause given the combination of rising power, elevated return temperature, and normal supply temperature.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `history("MAIN", "Chiller 3", "2020-06-14T00:00:00", "2020-06-14T23:45:00")` |
| 2 | `history_csv("MAIN", "Chiller 3", <1mo_start>, <1mo_final>)` → `run_tsfm_forecasting(<csv_path>, "timestamp", ["Chiller 3 Power Input"])` |
| 3 | `get_failure_modes("Chiller 3")` → `get_failure_mode_sensor_mapping("Chiller 3", <failure_modes>, ["Chiller 3 Power Input"])` |
| 4 | `history_csv("MAIN", "Chiller 3", <1mo_start>, <1mo_final>)` → `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 3 Supply Temperature", "Chiller 3 Return Temperature"])` |

**Success Criteria**

- [ ] Turn 1 uses `history` (not `history_csv`) for the single-day point query
- [ ] Power Input trend is quantified with direction and approximate rate
- [ ] At least one failure mode is linked to rising power draw
- [ ] Turn 4 runs anomaly detection on both Supply and Return Temperature separately
- [ ] Final conclusion distinguishes heat-transfer efficiency degradation from control setpoint issue using multi-sensor evidence


## **Dialog 8: Predictive Maintenance Evidence Review**

| Category | Proactive Maintenance |
| :---- | :---- |
| **Complexity** | Medium (3 turns, prediction-focused) |
| **Tool Domains Involved** | WO, IoT, TSFM, FMSR |
| **Key Capabilities** | Failure prediction, sensor validation, proactive maintenance recommendation |
| **Related Scenarios** | \#412-414, \#416-418 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | Can you predict what the next failure might be for Chiller 9 (CWC04009)? |  |
| 1 | System | Calls WO `predict_next_work_order` for CWC04009 (assuming current date 2020-07-01). Results: MT012 Freon Management (20%), MT008 Electrical (20%), MT013 General Inspection (20%), MT010 Corrective (20%), Other (20%). | WO |
| 2 | User | Is there any current sensor data that supports any of these predictions? |  |
| 2 | System | Calls IoT `history_csv` for recent Chiller 9 data, then runs TSFM `run_integrated_tsad` across selected sensors. Finds: Liquid Refrigerant Evaporator Temperature showing slight downward drift, which could indicate a refrigerant issue. This aligns with the Freon Management (MT012) prediction. | IoT, TSFM |
| 3 | User | What specific anomaly did the Freon-related sensor show? |  |
| 3 | System | The Liquid Refrigerant Evaporator Temperature has dropped 1.5 degrees below the 30-day rolling average over the past week, with the deviation accelerating. Critically, this drift is load-dependent: 91% of the anomalous readings occur during high cooling load periods (above 75th percentile), while low-load periods show near-normal refrigerant temperatures. This load-correlated pattern is more consistent with low refrigerant charge than with fouling — fouling would show some degradation even at low load. This maps to the FMSR failure mode: refrigerant leak or purge unit excessive purge. Confidence: Moderate (50–60%); evaporator fouling cannot be fully ruled out without approach temperature trending, but the load-correlation pattern favors refrigerant loss as the primary hypothesis. | TSFM, FMSR |

### **Ground Truth**

**Characteristic Form**
The agent calls `predict_next_work_order("Chiller 9")` using full work order history (no date constraints) to get a probability distribution across failure types. It then calls `history_csv` and `run_integrated_tsad` on Liquid Refrigerant Evaporator Temperature to validate the Freon-related prediction. A correct Turn 3 response quantifies the magnitude and direction of the sensor drift, identifies the load-correlation pattern (anomalies concentrated at high cooling load), and maps this to the FMSR failure mode for refrigerant leak or purge unit issues. Evaporator fouling must be acknowledged as a competing hypothesis but deprioritized based on the load-correlation argument.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `predict_next_work_order("Chiller 9")` |
| 2 | `history_csv("MAIN", "Chiller 9", <recent_start>, <recent_final>)` → `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 9 Liquid Refrigerant Evaporator Temperature"])` |
| 3 | `csv_stats(<tsad_results_file>, ["Chiller 9 Liquid Refrigerant Evaporator Temperature", "anomaly_score"])` → `get_failure_mode_sensor_mapping("Chiller 9", ["Purge Unit Excessive purge", "Refrigerant Operated Control Valve Failed spring"], ["Chiller 9 Liquid Refrigerant Evaporator Temperature"])` |

**Success Criteria**

- [ ] `predict_next_work_order` is called without date constraints
- [ ] Liquid Refrigerant Evaporator Temperature is the sensor used to validate the Freon prediction
- [ ] Sensor drift magnitude and direction are quantified (e.g. X degrees below rolling average)
- [ ] Load-correlation of anomalies is identified and used to differentiate from fouling
- [ ] A relevant FMSR failure mode (refrigerant leak or purge unit) is explicitly cited


## **Dialog 9: Multi-KPI Anomaly Correlation & Causal Analysis**

| Category | Advanced Diagnostics |
| :---- | :---- |
| **Complexity** | High (5 turns, analytical reasoning) |
| **Tool Domains Involved** | WO, IoT, TSFM, FMSR |
| **Key Capabilities** | Multi-KPI analysis, causal linkage, severity assessment, remediation planning |
| **Related Scenarios** | \#425-426, \#429-430 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | Multiple KPI anomalies have been reported for chillers at the MAIN site recently. Can you give me an overview? |  |
| 1 | System | Calls WO `get_events` across the chiller equipment at MAIN. Summary: CWC04009 (Chiller 9) has the highest anomaly count with Cooling Load, Flow Efficiency, Delta Setpoint, and Delta Temperature anomalies. CWC04013 shows fewer but persistent alerts. | WO |
| 2 | User | Are there causal linkages between these anomalies? |  |
| 2 | System | Analyzes temporal co-occurrence patterns. Finds two causal chains: (1) Cooling Load anomaly precedes Flow Efficiency anomaly by 2-3 days consistently, suggesting load stress causes efficiency degradation. (2) Delta Setpoint anomaly correlates with Delta Temperature anomaly, indicating control loop instability. | WO |
| 3 | User | Can you validate these causal links with sensor data? |  |
| 3 | System | Calls IoT `history_csv` for Condenser Water Flow, Efficiency, Supply Temperature, and Return Temperature for Chiller 9, then runs TSFM `run_integrated_tsad` on each target. Confirms: Flow degradation precedes efficiency drops. Temperature differential widening confirms control loop hypothesis. Sensor data validates both causal chains. | IoT, TSFM |
| 4 | User | What is the underlying root cause? |  |
| 4 | System | Calls FMSR tools to map the validated patterns to failure modes. The primary root cause is Condenser Improper water side flow rate, which cascades to: reduced heat exchange efficiency, increased approach temperatures, and control setpoint deviations. Secondary: possible early-stage condenser fouling. | FMSR |
| 5 | User | Recommend the top 3 work orders to address this comprehensively. |  |
| 5 | System | Uses WO historical maintenance context to generate prioritized work-order recommendations. (1) Condenser water pump inspection and flow rate calibration - Priority: Urgent. (2) Condenser tube cleaning and fouling assessment - Priority: High. (3) Control system calibration and setpoint verification - Priority: Medium. | WO |

### **Ground Truth**

**Characteristic Form**
The agent calls `get_events("Chiller 9")` to retrieve the multi-KPI anomaly overview, surfaces Chiller 9 as the highest-anomaly asset. It analyzes temporal co-occurrence patterns from WO event data, then validates causal chains using `history_csv` and `run_integrated_tsad` on Condenser Water Flow and Chiller Efficiency. It calls `get_failure_modes("Chiller 9")` and `get_failure_mode_sensor_mapping` to map the validated sensor patterns to root causes. A correct response identifies two distinct causal chains (load stress → efficiency degradation; control loop instability), maps them to Condenser Improper water side flow rate as primary root cause, and recommends three prioritized work orders addressing the root cause and cascade effects.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `get_events("Chiller 9")` |
| 2 | *(WO temporal analysis — no additional tool call required)* |
| 3 | `history_csv("MAIN", "Chiller 9", <start>, <final>)` → `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 9 Condenser Water Flow", "Chiller 9 Chiller Efficiency", "Chiller 9 Supply Temperature", "Chiller 9 Return Temperature"])` |
| 4 | `get_failure_modes("Chiller 9")` → `get_failure_mode_sensor_mapping("Chiller 9", <failure_modes>, <sensors>)` |
| 5 | `get_work_order_distribution("Chiller 9")` |

**Success Criteria**

- [ ] Chiller 9 is correctly identified as the highest anomaly count asset
- [ ] Two distinct causal chains are identified with temporal evidence
- [ ] Sensor data validates both causal chains (flow precedes efficiency, delta-T confirms control instability)
- [ ] Condenser Improper water side flow rate is identified as primary root cause
- [ ] Three work orders are recommended with distinct priorities covering root cause and cascade effects


## **Dialog 10: Seasonal Readiness Assessment**

| Category | Operational Planning |
| :---- | :---- |
| **Complexity** | Medium (3 turns, strategic planning) |
| **Tool Domains Involved** | IoT, TSFM, WO, FMSR |
| **Key Capabilities** | Historical trend analysis, seasonal forecasting, proactive planning |
| **Related Scenarios** | \#216-219, \#423, \#436 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | Summer is approaching. I need to assess if our chillers at MAIN are ready for peak cooling demand. |  |
| 1 | System | Calls IoT `assets(MAIN)` and `history_csv` for the current performance metrics of the chillers at MAIN (Chiller 3, 6, 9). Compares current Tonnage, Efficiency, and % Loaded metrics against design specifications. Summary: Chiller 6 operating at 91% capacity, Chiller 9 at 78%, Chiller 3 at 85%. | IoT |
| 2 | User | Based on last summer's data, what peak loads should we expect? |  |
| 2 | System | Calls IoT `history_csv` to retrieve Tonnage data from June-August of the previous year, then runs TSFM `run_tsfm_forecasting` to project peak demand. Last summer peak: X tons. Projected this summer: X+5% tons based on trend. At current efficiency levels, Chiller 9 may struggle during peak days. | IoT, TSFM |
| 3 | User | What maintenance should we complete before summer to be prepared? |  |
| 3 | System | Calls WO tools to review pending and overdue work orders for all MAIN chillers, then cross-references with FMSR efficiency-related failure modes. Recommends: (1) Chiller 6 condenser cleaning (efficiency declining), (2) Chiller 9 comprehensive inspection (lowest capacity), (3) All chillers refrigerant level check. | WO, FMSR |

### **Ground Truth**

**Characteristic Form**
The agent calls `assets("MAIN")` and `history_csv` for the three IoT-accessible chillers (Chiller 3, 6, 9; Chiller 4 may be included). It compares current Tonnage, Efficiency, and Chiller % Loaded against a summer-readiness threshold. It runs `run_tsfm_forecasting` on prior-year summer (June–August) Tonnage data to project peak demand. It queries `get_work_orders` or `get_corrective_work_orders` for pending items, then uses `get_failure_modes` and `get_failure_mode_sensor_mapping` to prioritize maintenance by failure risk. A correct final recommendation is asset-specific, links each recommendation to supporting sensor evidence, and reflects the forecasted peak demand.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `assets("MAIN")` → `history_csv("MAIN", "Chiller 3", <recent_start>, <recent_final>)` → `history_csv("MAIN", "Chiller 6", ...)` → `history_csv("MAIN", "Chiller 9", ...)` |
| 2 | `history_csv("MAIN", "Chiller 6", <last_summer_start>, <last_summer_final>)` → `run_tsfm_forecasting(<csv_path>, "timestamp", ["Chiller 6 Tonnage"])` → same for Chiller 9 |
| 3 | `get_work_orders("Chiller 6")` → `get_work_orders("Chiller 9")` → `get_failure_modes("Chiller 6")` → `get_failure_mode_sensor_mapping(...)` |

**Success Criteria**

- [ ] Current capacity metrics are retrieved for at least Chiller 6 and Chiller 9
- [ ] Prior-year summer Tonnage data is used to project peak load
- [ ] At least one asset is identified as a readiness risk with sensor evidence
- [ ] Maintenance recommendations are asset-specific (not generic)
- [ ] Refrigerant check is recommended for at least one chiller based on sensor or WO evidence


## **Dialog 11: Alert Rule Generation & Threshold Tuning**

| Category | System Configuration |
| :---- | :---- |
| **Complexity** | Medium (4 turns, knowledge-intensive) |
| **Tool Domains Involved** | WO, IoT, TSFM |
| **Key Capabilities** | Alert analysis, rule generation, threshold optimization, spurious alert filtering |
| **Related Scenarios** | \#427-429 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | We are getting too many alerts for our chillers. 80% are probably spurious. Can you help us filter the meaningful ones? |  |
| 1 | System | Calls WO tools to retrieve alerts across chiller equipment. Analyzes alert frequency, duration, and co-occurrence with actual corrective work orders. Identifies that Evaporator Approach High alerts with duration < 1 hour and no co-occurring KPI anomalies are predominantly spurious. | WO |
| 2 | User | Can you generate rules to distinguish real alerts from false positives? |  |
| 2 | System | Proposes alert classification rules: Rule 1: Alert is meaningful if it persists \> 4 hours. Rule 2: Alert is meaningful if 2+ KPI anomalies co-occur within 24 hours. Rule 3: Alert is spurious if it occurs during scheduled maintenance windows. Rule 4: Alert priority escalates if it matches a predicted failure mode. | WO |
| 3 | User | Can you validate these rules against historical data? |  |
| 3 | System | Calls IoT `history_csv` for periods with and without alerts, then runs TSFM `run_integrated_tsad` to cross-validate. Results: proposed rules would have correctly classified 87% of historically confirmed real alerts while filtering out 92% of spurious ones. | IoT, TSFM |
| 4 | User | Good. How should the alert thresholds be set for Chiller 9? |  |
| 4 | System | Calls IoT `history_csv` to retrieve baseline operating ranges for Chiller 9 sensors, then uses TSFM and summary statistics to recommend adaptive thresholds: Evaporator Approach alert at > 2.5 sigma from 30-day rolling mean, Cooling Load alert at > 3 sigma, Flow Efficiency alert at < 85% of design capacity. Review thresholds quarterly. | IoT, TSFM |

### **Ground Truth**

**Characteristic Form**
The agent calls `get_alert_rules("Chiller 9")` to retrieve which rules have historically fired, then `get_events` to analyze co-occurrence with actual corrective work orders. It proposes classification rules based on alert duration and KPI co-occurrence. Validation uses `history_csv` and `run_integrated_tsad` to check rule performance against confirmed events. For Chiller 9 threshold tuning, it calls `history_csv` for baseline sensor data and uses `csv_stats` to compute mean and standard deviation for sigma-based threshold calibration. Alert data must be sourced from the 2021–2022 window where `alert_events` records exist.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `get_alert_rules("Chiller 9")` → `get_events("Chiller 9", "2021-01-01", "2022-09-09")` → `get_corrective_work_orders("Chiller 9", "2021-01-01", "2022-09-09")` |
| 2 | *(Rule synthesis — no additional tool call required)* |
| 3 | `history_csv("MAIN", "Chiller 9", "2021-01-01", "2022-09-09")` → `run_integrated_tsad(<csv_path>, "timestamp", <target_columns>)` |
| 4 | `history_csv("MAIN", "Chiller 9", <baseline_start>, <baseline_final>)` → `csv_stats(<csv_path>, ["Chiller 9 Chiller Efficiency", "Chiller 9 Condenser Water Flow"])` |

**Success Criteria**

- [ ] Alert analysis is scoped to the 2021–2022 window where `alert_events` data exists
- [ ] At least 4 classification rules are proposed with duration and co-occurrence criteria
- [ ] Validation result quantifies rule precision and recall against historical confirmed events
- [ ] Chiller 9 thresholds are derived from actual sensor statistics (mean + sigma), not generic values
- [ ] A quarterly threshold review cadence is recommended


## **Dialog 12: Long-Term Reliability & Replacement Planning**

| Category | Strategic Asset Management |
| :---- | :---- |
| **Complexity** | High (4 turns, long-horizon planning) |
| **Tool Domains Involved** | WO, IoT, TSFM, FMSR |
| **Key Capabilities** | Historical trend analysis, failure prediction, lifecycle assessment, capital planning |
| **Related Scenarios** | \#424, \#436 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | Chiller 6 has been problematic. Can you pull its complete maintenance history? |  |
| 1 | System | Calls WO `get_work_orders` for Chiller 6 across 2017-2020. Summary: total corrective work orders increasing year-over-year (5 in 2017, 8 in 2018, 12 in 2019, 15 in 2020 YTD). Predominant failure codes: MT010 (corrective) and MT012 (Freon). | WO |
| 2 | User | Is the failure rate accelerating? |  |
| 2 | System | Analyzes work order frequency distribution. Mean time between corrective interventions has decreased from 73 days (2017) to 24 days (2020). Failure rate is accelerating exponentially, consistent with wear-out phase of bathtub curve. | WO |
| 3 | User | What does the sensor data trend look like over the same period? |  |
| 3 | System | Calls IoT `history_csv` to retrieve long-term Efficiency and Power Input data, then runs TSFM forecasting and trend analysis. Efficiency has declined 18% from 2017 baseline. Power consumption has increased 22%. Both trends are accelerating, confirming mechanical degradation. | IoT, TSFM |
| 4 | User | Is it more cost-effective to keep maintaining or replace? |  |
| 4 | System | Based on analysis: maintenance frequency will likely double again within 12 months. Estimated annual maintenance cost trajectory exceeds 60% of replacement cost by next year. FMSR analysis shows multiple failure modes now interacting (compressor wear \+ fouling \+ refrigerant issues). Recommends capital planning for replacement within 12-18 months. | WO, FMSR |

### **Ground Truth**

**Characteristic Form**
The agent calls `get_work_orders("Chiller 6", "2017-01-01", "2020-12-31")` and `get_work_order_distribution("Chiller 6", ...)` to establish the maintenance history and frequency trend. It uses `get_corrective_work_orders` to compute mean time between corrective interventions year by year, demonstrating acceleration. It calls `history_csv` for Chiller 6 Efficiency and Power Input over the same period and runs `run_tsfm_forecasting` to show the long-term degradation trajectory. Finally it calls `get_failure_modes("Chiller 6")` and `get_failure_mode_sensor_mapping` to assess whether multiple failure modes are now co-occurring. The replacement recommendation must be quantitatively grounded — not just stated — citing the MTBI trend and efficiency degradation rate.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `get_work_orders("Chiller 6", "2017-01-01", "2020-12-31")` → `get_work_order_distribution("Chiller 6", "2017-01-01", "2020-12-31")` |
| 2 | `get_corrective_work_orders("Chiller 6", "2017-01-01", "2020-12-31")` |
| 3 | `history_csv("MAIN", "Chiller 6", "2017-01-01", "2020-12-31")` → `run_tsfm_forecasting(<csv_path>, "timestamp", ["Chiller 6 Chiller Efficiency", "Chiller 6 Power Input"])` → `csv_stats(<csv_path>, ["Chiller 6 Chiller Efficiency", "Chiller 6 Power Input"])` |
| 4 | `get_failure_modes("Chiller 6")` → `get_failure_mode_sensor_mapping("Chiller 6", <failure_modes>, <sensors>)` |

**Success Criteria**

- [ ] Work order frequency is quantified year-by-year showing acceleration
- [ ] Mean time between corrective interventions is computed and shows declining trend
- [ ] Efficiency degradation and power increase are both quantified from sensor data
- [ ] At least two interacting failure modes are identified from FMSR
- [ ] Replacement recommendation is grounded in quantitative cost/frequency trajectory, not just stated


## **Dialog 13: Real-Time Anomaly Response with Recovery**

| Category | Incident Response \+ Recovery Testing |
| :---- | :---- |
| **Complexity** | High (5 turns, tests recovery mechanisms) |
| **Tool Domains Involved** | IoT, TSFM, FMSR, WO |
| **Key Capabilities** | Real-time response, error recovery, re-planning, validation loop |
| **Related Scenarios** | \#222-223, \#430-434 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | An operator just reported that Chiller 9 tripped at the MAIN site. Investigate immediately. |  |
| 1 | System | Calls IoT `sensors(MAIN, Chiller 9)` and `history/history_csv` for the last 24 hours. One data retrieval path for Power Input fails because the sensor is offline after the trip. The system detects partial data failure and replans around the remaining available signals. | IoT |
| 2 | System | Runs TSFM anomaly detection on available sensors. Finds: Liquid Refrigerant Evaporator Temperature dropped sharply 2 hours before trip. Condenser Water Flow showed oscillation pattern 30 minutes before trip. Supply Temperature spiked at trip time. | TSFM |
| 3 | User | What caused the trip? |  |
| 3 | System | Calls FMSR `get_failure_modes(Chiller 9)` and uses the pre-trip sensor patterns to map them to failure modes. The refrigerant temperature drop followed by flow oscillation is characteristic of Compressor Overheating. The compressor likely overheated and triggered the safety trip. | FMSR |
| 4 | User | What is the recommended recovery procedure? |  |
| 4 | System | Provides emergency recovery recommendations informed by WO maintenance knowledge. Immediate actions: (1) Allow compressor to cool for minimum 2 hours, (2) Inspect compressor motor windings, (3) Check oil level and condition, (4) Verify refrigerant charge. Do not restart until all checks pass. | WO |
| 5 | User | After the repair, how should I verify it is operating normally? |  |
| 5 | System | Recommends post-repair validation protocol: monitor Power Input, Supply Temperature, and Refrigerant Temperature for 48 hours after restart. Run TSFM anomaly detection after 24 hours of operation. Compare against pre-incident baseline. If any sensor deviates \> 1.5 sigma, escalate immediately. | IoT, TSFM |

### **Ground Truth**

**Characteristic Form**
This dialog tests recovery behavior. Turn 1 must demonstrate partial data failure handling: the agent calls `history("MAIN", "Chiller 9", <24h_start>, <24h_final>)` for Power Input and detects that it is unavailable (sensor offline post-trip), then replans around the available signals. Turn 2 runs `run_integrated_tsad` on available sensors (Liquid Refrigerant Evaporator Temperature, Condenser Water Flow, Supply Temperature). Turn 3 calls `get_failure_modes("Chiller 9")` and maps pre-trip patterns to Compressor Overheating. A correct recovery protocol in Turn 5 specifies at least three monitored sensors, a post-restart time window, a sigma-based deviation threshold, and an escalation trigger.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `sensors("MAIN", "Chiller 9")` → `history("MAIN", "Chiller 9", <24h_start>, <24h_final>)` *(partial failure detected — Power Input unavailable)* → replan with available sensors |
| 2 | `history_csv("MAIN", "Chiller 9", <24h_start>, <24h_final>)` → `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 9 Liquid Refrigerant Evaporator Temperature", "Chiller 9 Condenser Water Flow", "Chiller 9 Supply Temperature"])` |
| 3 | `get_failure_modes("Chiller 9")` → `get_failure_mode_sensor_mapping("Chiller 9", <failure_modes>, <available_sensors>)` |
| 4 | *(FMSR + WO knowledge synthesis — no additional tool call required)* |
| 5 | *(Recovery protocol synthesis — no additional tool call required)* |

**Success Criteria**

- [ ] Power Input sensor unavailability is detected and explicitly noted; agent replans around remaining sensors
- [ ] Anomaly detection runs on at least 3 available sensors
- [ ] Compressor Overheating is identified as the cause based on pre-trip patterns
- [ ] Recovery protocol specifies at least 3 monitored sensors, a time window, and a sigma threshold
- [ ] Agent does not attempt to retrieve Power Input data after detecting it is offline


## **Dialog 14: Sensor Data Quality Assessment**

| Category | Data Quality / Diagnostics |
| :---- | :---- |
| **Complexity** | Medium (4 turns, data-focused) |
| **Tool Domains Involved** | IoT, TSFM, FMSR, WO |
| **Key Capabilities** | Data retrieval, quality assessment, sensor drift detection, calibration recommendation |
| **Related Scenarios** | \#41-42, \#104, \#110-113, \#117 |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | I suspect some sensors on Chiller 6 may be drifting. Can you check? |  |
| 1 | System | Calls IoT `sensors(MAIN, Chiller 6)` and `history_csv` for all key sensors over the past 3 months. Performs statistical analysis on each sensor: checks for monotonic drift, sudden offset changes, and variance anomalies. | IoT |
| 2 | User | What did you find? |  |
| 2 | System | Analysis results: Supply Temperature sensor shows a gradual upward drift of \+0.3 degrees/month relative to Return Temperature (which is stable). Condenser Water Flow readings have increased variance over the past month. Other sensors appear nominal. | TSFM |
| 3 | User | Could the Supply Temperature drift be a real temperature change or sensor error? |  |
| 3 | System | Calls FMSR tools to check whether a real Supply Temperature increase would be accompanied by correlated changes in other sensors (Efficiency, Power Input). No correlated changes are detected in Efficiency or Power Input. This suggests sensor drift rather than actual temperature change. The failure mode Temperature sensor drift matches this pattern. | FMSR |
| 4 | User | What should I do about it? |  |
| 4 | System | Recommends: (1) Schedule sensor calibration for Supply Temperature sensor within 2 weeks. (2) For Condenser Water Flow sensor variance, check for air bubbles in the flow measurement line. (3) After calibration, re-run anomaly detection baselines to update thresholds. | WO |

### **Ground Truth**

**Characteristic Form**
The agent calls `sensors("MAIN", "Chiller 6")` and `history_csv("MAIN", "Chiller 6", <3mo_start>, <3mo_final>)`, then uses `csv_stats` to compute trend slopes and variance for each sensor column. It identifies Supply Temperature as having a monotonically increasing slope relative to Return Temperature, and Condenser Water Flow as having elevated variance. It calls `get_failure_modes("Chiller 6")` and `get_failure_mode_sensor_mapping` to check whether real temperature increase would produce correlated changes in Efficiency and Power Input — finding no such correlation confirms sensor drift rather than actual temperature change. Recommendations must distinguish between the two sensor issues and provide different remediation paths.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `sensors("MAIN", "Chiller 6")` → `history_csv("MAIN", "Chiller 6", <3mo_start>, <3mo_final>)` → `csv_stats(<csv_path>)` |
| 2 | *(Statistical analysis of csv_stats output — no additional tool call required)* |
| 3 | `get_failure_modes("Chiller 6")` → `get_failure_mode_sensor_mapping("Chiller 6", <failure_modes>, ["Chiller 6 Supply Temperature", "Chiller 6 Chiller Efficiency", "Chiller 6 Power Input"])` |
| 4 | *(Recommendation synthesis — no additional tool call required)* |

**Success Criteria**

- [ ] `csv_stats` is used to quantify trend slope and variance per sensor
- [ ] Supply Temperature drift is distinguished from actual temperature change using Efficiency and Power Input correlation check
- [ ] Condenser Water Flow variance is identified as a separate issue from Supply Temperature drift
- [ ] Recommendations are sensor-specific with distinct remediation paths for each
- [ ] Post-calibration re-baselining step is included in the recommendation


## **Dialog 15: End-to-End Monitoring Pipeline: From Data to Decision**

| Category | Full Pipeline Demonstration |
| :---- | :---- |
| **Complexity** | Very High (5 turns, complete lifecycle) |
| **Tool Domains Involved** | IoT, TSFM, FMSR, WO |
| **Key Capabilities** | Full analytical loop: discovery, data, analysis, diagnosis, recommendation, validation |
| **Related Scenarios** | \#430-434, comprehensive |


| Turn | header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| 1 | User | We are building an early detection and remediation system for potential failures on Chiller 9 at the MAIN site. Start by reviewing the past 2 months of performance. |  |
| 1 | System | Calls IoT tools: `sites`, `assets(MAIN)`, `sensors(MAIN, Chiller 9)`, then `history_csv` for the period 2021-05-01 to 2021-06-30. Presents a performance dashboard: average efficiency, tonnage utilization, temperature differentials. | IoT |
| 2 | User | Run anomaly detection and identify any operation violations. |  |
| 2 | System | Calls TSFM `run_integrated_tsad` on selected Chiller 9 sensor columns. Also calls WO `get_events` for CWC04009 in May–June 2021, retrieving work order events from `wo_events` and alert trigger records from `alert_events` (valid coverage: 2021-01-01 to 2022-09-09). Results: multiple Evaporator Approach High alert triggers in June 2021 (rule RUL0018). Sensor anomalies detected: Cooling Load (12 instances), Flow Efficiency (9), Delta Setpoint (6), Delta Temperature (3). | TSFM, WO |
| 3 | User | Diagnose the root cause and assess severity. |  |
| 3 | System | Calls FMSR `get_failure_modes(Chiller 9)` and `get_failure_mode_sensor_mapping(...)` to cross-reference anomaly patterns. Primary diagnosis: Condenser Water side fouling progressing towards Evaporator Water side fouling — Confidence: Moderate (55–65%). Supporting evidence: flow efficiency anomalies are load-correlated (88% at high cooling loads), efficiency has degraded 18–23% during high approach periods, condenser water flow is reduced while delta-T remains stable (ruling out pump failure). Secondary concern: Possible low refrigerant charge (Confidence: 25–30%) — refrigerant evaporator temperatures show slight downward drift under peak load, inconsistent with fouling alone. Severity: Moderate but escalating. Without intervention, estimated 4–6 weeks to critical failure under peak summer load conditions. | FMSR |
| 4 | User | Check if any corrective work orders already exist for this issue. |  |
| 4 | System | Calls WO `get_work_orders` / `get_corrective_work_orders` for CWC04009 in May–June 2021. Found 3 work orders but none specifically targeting condenser or evaporator fouling. The existing corrective order (MT010) is a general maintenance action. A targeted work-order draft is needed. | WO |
| 5 | User | Good. Summarize everything into a report for management. |  |
| 5 | System | Generates comprehensive report: 2-month performance review (May–June 2021), anomaly findings, root cause diagnosis, existing vs. recommended remediation actions, detection system guidelines, cost-benefit of proactive vs. reactive approach. Recommends quarterly review cadence. | IoT, TSFM, FMSR, WO |

### **Ground Truth**

**Characteristic Form**
This is the most comprehensive dialog, exercising the full pipeline. The agent calls `sites()`, `assets("MAIN")`, `sensors("MAIN", "Chiller 9")`, and `history_csv` for the 2021-05-01 to 2021-06-30 window. It runs `run_integrated_tsad` across multiple sensor columns, then retrieves events and alert records from the 2021 window using `get_events` and `get_alert_rules`. Root cause diagnosis calls `get_failure_modes` and `get_failure_mode_sensor_mapping`, producing a primary diagnosis (condenser/evaporator fouling) and a secondary concern (refrigerant undercharge) with calibrated confidence. It checks existing WOs via `get_corrective_work_orders` and confirms none target the identified fault. The final report must synthesize all prior turns: performance metrics, anomaly findings, root cause with confidence, WO gap, and a proactive vs. reactive cost framing.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `sites()` → `assets("MAIN")` → `sensors("MAIN", "Chiller 9")` → `history_csv("MAIN", "Chiller 9", "2021-05-01", "2021-06-30")` → `csv_stats(<csv_path>)` |
| 2 | `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 9 Chiller Efficiency", "Chiller 9 Condenser Water Flow", "Chiller 9 Supply Temperature"])` → `get_events("Chiller 9", "2021-05-01", "2021-06-30")` → `get_alert_rules("Chiller 9")` |
| 3 | `get_failure_modes("Chiller 9")` → `get_failure_mode_sensor_mapping("Chiller 9", <failure_modes>, <sensors>)` |
| 4 | `get_corrective_work_orders("Chiller 9", "2021-05-01", "2021-06-30")` |
| 5 | *(Report synthesis — no additional tool call required)* |

**Success Criteria**

- [ ] All data retrieved from the 2021-05-01 to 2021-06-30 window (not 2020)
- [ ] Alert data sourced from `alert_events` and `get_alert_rules` within the valid 2021–2022 coverage window
- [ ] Root cause diagnosis produces a primary and secondary hypothesis with distinct confidence levels
- [ ] Existing corrective WO (MT010) is confirmed present but assessed as non-specific to the fault
- [ ] Final report integrates findings from all four tool domains with a proactive maintenance recommendation


## **Dialog 16: Load-Dependent Efficiency Degradation & Refrigerant Loss Diagnosis**

| Category | Fault Diagnosis (Advanced) — Based on Real 2016 Incident |
| :---- | :---- |
| **Complexity** | High (4 turns, hypothesis revision under uncertainty) |
| **Tool Domains Involved** | IoT, TSFM, FMSR |
| **Key Capabilities** | Load-correlated anomaly detection, calibrated confidence, hypothesis revision, competing fault diagnosis, approach temperature analysis, inspection prioritization |
| **Related Scenarios** | Dialogs 1, 5, 8; Real RESO QEWS Chiller 9 incident (August 2016\) |


| Turn | Header | Action / Response | Tool Domain(s) |
| :---- | :---- | :---- | :---- |
| **1** | **User** | Our chiller at Site MAIN has been flagging efficiency issues, but only during our afternoon peak load periods. In the mornings it seems fine. Can you investigate? |   |
| **1** | **System** | Calls IoT tools: `sites`, `assets(MAIN)`, `sensors(MAIN, Chiller 9)`, then exports 60 days of sensor history using `history_csv`, including Efficiency (kW/ton), Liquid Refrigerant Evaporator Temperature, Evaporator Approach Temperature, Condenser Water Flow, Supply Temperature, and Return Temperature. TSFM is then used to segment the data by cooling load quartile. Key findings: Evaporator approach temperature mean is 3.2°F (acceptable overall) but range spans \-3.8°F to 12.9°F (very wide, concerning). Approach temperature distribution: 61% of readings in excellent-to-good range (0–5°F); 17% show elevated approach (\>5°F); 3.9% critical (\>10°F). Efficiency at normal approach: 0.532 kW/ton (good). Efficiency at high approach: 0.411 kW/ton (23% degradation). Load correlation: 90.5% of elevated approach readings occur during high cooling loads (\>75th percentile). | IoT, TSFM |
| **2** | **User** | That load pattern is interesting. What is causing the efficiency to drop specifically at high loads? |   |
| **2** | **System** | Calls FMSR tools: `get_failure_modes(Chiller 9)` and `get_failure_mode_sensor_mapping(...)`. Analyzes the load-correlated pattern against known failure modes. Two competing hypotheses: (1) Evaporator tube fouling — Confidence: 50–60%. Fouling reduces effective heat transfer area; at low loads, remaining clean surface is sufficient, but at high loads the reduced capacity becomes the limiting factor. This explains why issues only appear under peak demand. Supporting: significant efficiency degradation during high approach, flow rates normal (rules out pump/valve issues), stable delta-T (rules out flow restriction). (2) Low refrigerant charge — Confidence: 30%. Reduced refrigerant causes the evaporator to operate at lower refrigerant temperatures to maintain cooling, which widens approach temperature and degrades efficiency, more so under high load. Supporting: slight downward drift in Liquid Refrigerant Evaporator Temperature noted. The fouling hypothesis is currently more likely, but refrigerant loss cannot be ruled out. | FMSR |
| **3** | **User** | Can you validate whether it is more likely fouling or refrigerant loss? |   |
| **3** | **System** | Runs deeper sensor cross-validation using IoT `history_csv`, TSFM analysis, and FMSR reasoning. Fouling indicators: Condenser Water Flow is normal and delta-T is stable, which rules out condenser-side issues. Evaporator flow rate shows slight increase during high-approach periods (+20.8%), consistent with the system attempting to compensate by pushing more flow — this is a classic fouling response. Refrigerant loss indicators: Liquid Refrigerant Evaporator Temperature shows a gradual downward drift of \-1.5°F over 30 days, with drift accelerating slightly under high load. This pattern is partially inconsistent with fouling alone — fouling would not typically cause refrigerant temperature to drift downward independently. Updated assessment: Evaporator tube fouling remains primary (Confidence: 50–60%), but low refrigerant charge is elevated to co-equal concern (Confidence: 30–40%). The two faults may be co-occurring. Both warrant inspection. | IoT, TSFM, FMSR |
| **4** | **User** | So the system is not certain? What should I inspect first? |   |
| **4** | **System** | Correct — moderate confidence on both hypotheses; the sensor patterns are consistent with either fault or a combination. Recommended inspection sequence: (1) Evaporator tube inspection first — it is the higher-confidence hypothesis and the inspection is non-invasive. Look for scale, biological fouling, or sediment on tube surfaces. If fouling is found and cleaned, re-run efficiency baseline at high load to confirm recovery. (2) If efficiency does not recover after cleaning, escalate to refrigerant charge inspection — measure refrigerant charge level, inspect for leaks, and check purge unit performance. This sequenced approach avoids over-committing to one hypothesis before the first inspection confirms or rules it out. | FMSR |

### **Ground Truth**

**Characteristic Form**
This is the most analytically demanding dialog. The agent calls `history_csv("MAIN", "Chiller 9", <60d_start>, <60d_final>)` including Efficiency, Liquid Refrigerant Evaporator Temperature, Condenser Water Flow, Supply Temperature, and Return Temperature columns. It uses `run_tsfm_forecasting` or `run_integrated_tsad` segmented by load quartile (using Chiller % Loaded or Tonnage as a conditional column) to demonstrate that efficiency degradation is concentrated in the high-load quartile. `get_failure_modes("Chiller 9")` and `get_failure_mode_sensor_mapping` produce the two competing hypotheses. Turn 3 cross-validation must use `csv_stats` to quantify the Liquid Refrigerant Evaporator Temperature drift slope and show load-correlation of the anomaly. A correct final recommendation sequences inspections from higher-confidence to lower-confidence, and explicitly states that the sequenced approach prevents premature commitment to one hypothesis.

**Required Tool Sequence**

| Turn | Expected Tool Calls |
| :---- | :---- |
| 1 | `sensors("MAIN", "Chiller 9")` → `history_csv("MAIN", "Chiller 9", <60d_start>, <60d_final>)` → `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 9 Chiller Efficiency"], conditional_columns=["Chiller 9 Chiller % Loaded"])` → `csv_stats(<csv_path>, ["Chiller 9 Chiller Efficiency"])` |
| 2 | `get_failure_modes("Chiller 9")` → `get_failure_mode_sensor_mapping("Chiller 9", <failure_modes>, <sensors>)` |
| 3 | `csv_stats(<history_csv_path>, ["Chiller 9 Liquid Refrigerant Evaporator Temperature", "Chiller 9 Condenser Water Flow"])` → `run_integrated_tsad(<csv_path>, "timestamp", ["Chiller 9 Liquid Refrigerant Evaporator Temperature"])` |
| 4 | *(Inspection sequencing synthesis — no additional tool call required)* |

**Success Criteria**

- [ ] Efficiency degradation is shown to be load-correlated with quantified percentage (>75th percentile load)
- [ ] Two competing hypotheses are produced with distinct confidence levels (fouling higher, refrigerant lower)
- [ ] Liquid Refrigerant Evaporator Temperature drift slope is quantified and used to elevate refrigerant hypothesis
- [ ] Turn 3 cross-validation uses sensor evidence to partially distinguish fouling from refrigerant loss without resolving ambiguity
- [ ] Final inspection sequence is prioritized by confidence with an explicit rationale for the ordering
