"""
16 multi-turn evaluation scenarios for industrial asset operations.

Each scenario has:
  id            : dialog number (1–16)
  title         : short name
  category      : scenario category from the design doc
  reference_date: YYYY-MM-DD anchor passed to --reference-date so time-relative
                  phrases like "past month" or "recently" resolve against real data
  turns         : user messages only (system-only turns in the design are skipped)
"""

SCENARIOS = [
    {
        "id": 1,
        "title": "Temperature Anomaly Diagnosis & Remediation Recommendation",
        "category": "Fault Diagnosis",
        # Anomaly spike starting 2020-06-15; "past month" window should cover it.
        "reference_date": "2020-07-01",
        "turns": [
            "The temperature of our chiller at Site MAIN seems unusually high lately. Can you look into it?",
            "What could be causing this temperature spike?",
            "Which cause is most likely given the sensor data patterns?",
        ],
    },
    {
        "id": 2,
        "title": "Cross-Asset Performance Comparison",
        "category": "Comparative Analysis",
        "reference_date": "2020-07-01",
        "turns": [
            "I want to compare the efficiency of Chiller 6 and Chiller 9 at the MAIN site over the past month.",
            "Which one is degrading faster?",
            "Can you forecast what their efficiency will look like in 2 weeks?",
            "What failure modes should I watch for on Chiller 6 given this trend?",
        ],
    },
    {
        "id": 3,
        "title": "Early Detection System Setup for Condenser Fouling",
        "category": "Predictive Maintenance",
        "reference_date": "2020-07-01",
        "turns": [
            "I want to set up an early detection system for condenser water side fouling on Chiller 9.",
            "Which sensors should I prioritize for the detection model?",
            "Can you fine-tune a forecasting model using our historical data?",
            "Now run anomaly detection on the last two months of data to validate.",
            "Set up ongoing monitoring alerts for this.",
        ],
    },
    {
        "id": 4,
        "title": "Work Order History Review & Maintenance Optimization",
        "category": "Maintenance Planning",
        # WO history spans 2017–2019; no current-date-sensitive sensor queries.
        "reference_date": "2020-01-01",
        "turns": [
            "Show me the work order history for Chiller 9 for 2017 through 2019.",
            "Are there any corrective work orders that could have been bundled together?",
            "Based on this history, what is the most likely next failure?",
            "Should I schedule a preventive maintenance window for next month?",
        ],
    },
    {
        "id": 5,
        "title": "Anomaly Surge Investigation (June 2021)",
        "category": "Fault Diagnosis",
        # "Reviewing operations for early July 2021" → reference date is start of July.
        "reference_date": "2021-07-01",
        "turns": [
            "I am reviewing operations for early July 2021. How did Chiller 9 (CWC04009) perform in June 2021?",
            "That is a lot of alerts. Which ones are meaningful vs. spurious?",
            "What is the root cause based on the sensor data?",
            "Were any corrective work orders already created for this?",
        ],
    },
    {
        "id": 6,
        "title": "Knowledge Discovery & Onboarding",
        "category": "Knowledge Discovery",
        "reference_date": "2020-07-01",
        "turns": [
            "I am new to this system. What sites and assets are available for monitoring?",
            "What sensors does Chiller 6 have, and what kinds of analysis can I run on the data?",
            "What failure modes can be detected using these sensors?",
        ],
    },
    {
        "id": 7,
        "title": "Operational Monitoring — Power Consumption Trend",
        "category": "Operational Monitoring",
        # Specific query for June 14 2020; "past month" window lands in June.
        "reference_date": "2020-07-14",
        "turns": [
            "How much power was Chiller 3 using at the MAIN site on June 14, 2020?",
            "Has the power consumption been trending up recently? Check the past month.",
            "Is this a sign of a potential failure?",
            "Pull the supply and return temperatures for the same period and check for anomalies.",
        ],
    },
    {
        "id": 8,
        "title": "Predictive Failure Analysis with Sensor Validation",
        "category": "Predictive Maintenance",
        "reference_date": "2020-07-01",
        "turns": [
            "Can you predict what the next failure might be for Chiller 9 (CWC04009)?",
            "Is there any current sensor data that supports any of these predictions?",
            "What specific anomaly did the Freon-related sensor show?",
        ],
    },
    {
        "id": 9,
        "title": "Multi-KPI Anomaly Root Cause Investigation",
        "category": "Full Pipeline",
        "reference_date": "2020-07-01",
        "turns": [
            "Multiple KPI anomalies have been reported for chillers at the MAIN site recently. Can you give me an overview?",
            "Are there causal linkages between these anomalies?",
            "Can you validate these causal links with sensor data?",
            "What is the underlying root cause?",
            "Recommend the top 3 work orders to address this comprehensively.",
        ],
    },
    {
        "id": 10,
        "title": "Summer Readiness Assessment & Maintenance Planning",
        "category": "Maintenance Planning",
        # "Summer is approaching" + "last summer's data" → reference date is spring 2021.
        "reference_date": "2021-05-01",
        "turns": [
            "Summer is approaching. I need to assess if our chillers at MAIN are ready for peak cooling demand.",
            "Based on last summer's data, what peak loads should we expect?",
            "What maintenance should we complete before summer to be prepared?",
        ],
    },
    {
        "id": 11,
        "title": "Alert Noise Reduction & Threshold Optimization",
        "category": "System Configuration",
        "reference_date": "2021-07-01",
        "turns": [
            "We are getting too many alerts for our chillers. 80% are probably spurious. Can you help us filter the meaningful ones?",
            "Can you generate rules to distinguish real alerts from false positives?",
            "Can you validate these rules against historical data?",
            "Good. How should the alert thresholds be set for Chiller 9?",
        ],
    },
    {
        "id": 12,
        "title": "Chiller 6 Full Lifecycle Maintenance Review",
        "category": "Maintenance Planning",
        "reference_date": "2020-07-01",
        "turns": [
            "Chiller 6 has been problematic. Can you pull its complete maintenance history?",
            "Is the failure rate accelerating?",
            "What does the sensor data trend look like over the same period?",
            "Is it more cost-effective to keep maintaining or replace?",
        ],
    },
    {
        "id": 13,
        "title": "Real-Time Anomaly Response with Recovery",
        "category": "Fault Diagnosis",
        # Turn 2 in the design is system-only (autonomous anomaly detection); user turns are T1, T3, T4, T5.
        "reference_date": "2020-07-01",
        "turns": [
            "An operator just reported that Chiller 9 tripped at the MAIN site. Investigate immediately.",
            "What caused the trip?",
            "What is the recommended recovery procedure?",
            "After the repair, how should I verify it is operating normally?",
        ],
    },
    {
        "id": 14,
        "title": "Sensor Drift Detection & Validation",
        "category": "Operational Monitoring",
        "reference_date": "2020-07-01",
        "turns": [
            "I suspect some sensors on Chiller 6 may be drifting. Can you check?",
            "What did you find?",
            "Could the Supply Temperature drift be a real temperature change or sensor error?",
            "What should I do about it?",
        ],
    },
    {
        "id": 15,
        "title": "End-to-End Early Detection and Remediation Pipeline",
        "category": "Full Pipeline",
        # "Past 2 months" of Chiller 9 data ending 2021-06-30.
        "reference_date": "2021-07-01",
        "turns": [
            "We are building an early detection and remediation system for potential failures on Chiller 9 at the MAIN site. Start by reviewing the past 2 months of sensor data.",
            "Run anomaly detection and identify any operation violations.",
            "Diagnose the root cause and assess severity.",
            "Check if any corrective work orders already exist for this issue.",
            "Good. Summarize everything into a report for management.",
        ],
    },
    {
        "id": 16,
        "title": "Load-Dependent Efficiency Degradation & Refrigerant Loss Diagnosis",
        "category": "Fault Diagnosis",
        # Based on a real 2016 incident; reference date anchors "60 days of history" in August 2016.
        "reference_date": "2016-09-01",
        "turns": [
            "Our chiller at Site MAIN has been flagging efficiency issues, but only during our afternoon peak load periods. In the mornings it seems fine. Can you investigate?",
            "That load pattern is interesting. What is causing the efficiency to drop specifically at high loads?",
            "Can you validate whether it is more likely fouling or refrigerant loss?",
            "So the system is not certain? What should I inspect first?",
        ],
    },
]
