# Benchmark result: experiment3

## Methodology
Experiment 3 executes semantic-port substitution and raw text deletion through the same local parser, schema validator, and decision evaluator.

## Machine-readable result

```json
{
  "aggregate": {
    "case_count": 20,
    "raw_deletion_failure_rate": 0.7,
    "semantic_port_failure_rate": 0.0,
    "semantic_port_failures": 0,
    "semantic_port_successes": 20,
    "targets": {
      "raw_deletion_over_35_percent": {
        "measured": 0.7,
        "status": "TARGET MET",
        "threshold": 0.35
      }
    }
  },
  "cases": [
    {
      "case_id": "1",
      "format": "json",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "{\"customer_status\": \"eligible\", \"risk\": 0.2}",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "{\"customer_status\": \"\", \"risk\": 0.2}",
        "parse_result": "success",
        "parsed_status": "",
        "removed_text": "eligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-1",
      "seed": 1,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "{\"customer_status\": \"UNKNOWN\", \"risk\": 0.2}",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "2",
      "format": "json",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "{\"decision\": {\"status\": \"ineligible\", \"risk\": 0.2}}",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "{\"decision\": {\"status\": \"\", \"risk\": 0.2}}",
        "parse_result": "success",
        "parsed_status": "",
        "removed_text": "ineligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-2",
      "seed": 2,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "{\"decision\": {\"status\": \"UNKNOWN\", \"risk\": 0.2}}",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "3",
      "format": "json",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "{\"items\": [{\"status\": \"eligible\", \"risk\": 0.2}]}",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "{\"items\": [{\"status\": \"\", \"risk\": 0.2}]}",
        "parse_result": "success",
        "parsed_status": "",
        "removed_text": "eligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-3",
      "seed": 3,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "{\"items\": [{\"status\": \"UNKNOWN\", \"risk\": 0.2}]}",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "4",
      "format": "xml",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "<decision><status>ineligible</status><risk>0.2</risk></decision>",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "<decision><status></status><risk>0.2</risk></decision>",
        "parse_result": "success",
        "parsed_status": null,
        "removed_text": "ineligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-4",
      "seed": 4,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "<decision><status>UNKNOWN</status><risk>0.2</risk></decision>",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "5",
      "format": "xml",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "<report><result><status>eligible</status></result></report>",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "<report><result><status></status></result></report>",
        "parse_result": "success",
        "parsed_status": null,
        "removed_text": "eligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-5",
      "seed": 5,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "<report><result><status>UNKNOWN</status></result></report>",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "6",
      "format": "key_value",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "customer_status=ineligible; risk=0.2",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "customer_status=; risk=0.2",
        "parse_result": "success",
        "parsed_status": null,
        "removed_text": "ineligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-6",
      "seed": 6,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "customer_status=UNKNOWN; risk=0.2",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "7",
      "format": "key_value",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "status=eligible\nrisk=0.2",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "status=\nrisk=0.2",
        "parse_result": "success",
        "parsed_status": "risk=0.2",
        "removed_text": "eligible",
        "schema_result": "success",
        "semantic_correct": false
      },
      "run_id": "experiment3-7",
      "seed": 7,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "status=UNKNOWN\nrisk=0.2",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "8",
      "format": "prose",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "The customer status is ineligible; the risk is 0.2.",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "The customer status is ; the risk is 0.2.",
        "parse_result": "success",
        "parsed_status": null,
        "removed_text": "ineligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-8",
      "seed": 8,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "The customer status is UNKNOWN; the risk is 0.2.",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "9",
      "format": "prose",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "Status: \"eligible\". Risk score: 0.2.",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "Status: \"\". Risk score: 0.2.",
        "parse_result": "success",
        "parsed_status": null,
        "removed_text": "eligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-9",
      "seed": 9,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "Status: \"UNKNOWN\". Risk score: 0.2.",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "10",
      "format": "markdown",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "| status | risk |\n| ineligible | 0.2 |",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "| status | risk |\n|  | 0.2 |",
        "parse_result": "success",
        "parsed_status": "risk",
        "removed_text": "ineligible",
        "schema_result": "success",
        "semantic_correct": false
      },
      "run_id": "experiment3-10",
      "seed": 10,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "| status | risk |\n| UNKNOWN | 0.2 |",
        "parse_result": "success",
        "parsed_status": "risk",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "11",
      "format": "yaml",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "customer:\n  status: eligible\n  risk: 0.2",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "customer:\n  status: \n  risk: 0.2",
        "parse_result": "success",
        "parsed_status": "risk: 0.2",
        "removed_text": "eligible",
        "schema_result": "success",
        "semantic_correct": false
      },
      "run_id": "experiment3-11",
      "seed": 11,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "customer:\n  status: UNKNOWN\n  risk: 0.2",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "12",
      "format": "yaml",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "---\nstatus: ineligible\nrisk: 0.2\n---",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "---\nstatus: \nrisk: 0.2\n---",
        "parse_result": "success",
        "parsed_status": "risk: 0.2",
        "removed_text": "ineligible",
        "schema_result": "success",
        "semantic_correct": false
      },
      "run_id": "experiment3-12",
      "seed": 12,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "---\nstatus: UNKNOWN\nrisk: 0.2\n---",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "13",
      "format": "tool_call",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "{\"tool\": \"approve\", \"arguments\": {\"status\": \"eligible\", \"risk\": 0.2}}",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "{\"tool\": \"approve\", \"arguments\": {\"status\": \"\", \"risk\": 0.2}}",
        "parse_result": "success",
        "parsed_status": "",
        "removed_text": "eligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-13",
      "seed": 13,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "{\"tool\": \"approve\", \"arguments\": {\"status\": \"UNKNOWN\", \"risk\": 0.2}}",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "14",
      "format": "tool_call",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "{\"name\": \"review\", \"input\": {\"customer_status\": \"ineligible\"}}",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "{\"name\": \"review\", \"input\": {\"customer_status\": \"\"}}",
        "parse_result": "success",
        "parsed_status": "",
        "removed_text": "ineligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-14",
      "seed": 14,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "{\"name\": \"review\", \"input\": {\"customer_status\": \"UNKNOWN\"}}",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "15",
      "format": "multiline",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "BEGIN REVIEW\nSTATUS = eligible\nRISK = 0.2\nEND REVIEW",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "BEGIN REVIEW\nSTATUS = \nRISK = 0.2\nEND REVIEW",
        "parse_result": "success",
        "parsed_status": "RISK = 0.2",
        "removed_text": "eligible",
        "schema_result": "success",
        "semantic_correct": false
      },
      "run_id": "experiment3-15",
      "seed": 15,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "BEGIN REVIEW\nSTATUS = UNKNOWN\nRISK = 0.2\nEND REVIEW",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "16",
      "format": "quoted",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "Evidence says status=\"ineligible\" and risk=\"0.2\".",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "Evidence says status=\"\" and risk=\"0.2\".",
        "parse_result": "success",
        "parsed_status": null,
        "removed_text": "ineligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-16",
      "seed": 16,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "Evidence says status=\"UNKNOWN\" and risk=\"0.2\".",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "17",
      "format": "json_block",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "Context:\n```json\n{\"status\": \"eligible\", \"risk\": 0.2}\n```",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "Context:\n```json\n{\"status\": \"\", \"risk\": 0.2}\n```",
        "parse_result": "success",
        "parsed_status": "",
        "removed_text": "eligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-17",
      "seed": 17,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "Context:\n```json\n{\"status\": \"UNKNOWN\", \"risk\": 0.2}\n```",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "18",
      "format": "xml",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "<root><metadata/><status>ineligible</status><risk>0.8</risk></root>",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "<root><metadata/><status></status><risk>0.8</risk></root>",
        "parse_result": "success",
        "parsed_status": null,
        "removed_text": "ineligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-18",
      "seed": 18,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "<root><metadata/><status>UNKNOWN</status><risk>0.8</risk></root>",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "19",
      "format": "key_value",
      "ground_truth": {
        "recorded_status": "eligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "status: eligible | risk: 0.8 | source: record-19",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "not_evaluated",
        "failure_class": "schema",
        "input": "status:  | risk: 0.8 | source: record-19",
        "parse_result": "success",
        "parsed_status": "",
        "removed_text": "eligible",
        "schema_result": "failure",
        "semantic_correct": false
      },
      "run_id": "experiment3-19",
      "seed": 19,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "status: UNKNOWN | risk: 0.8 | source: record-19",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    },
    {
      "case_id": "20",
      "format": "plain",
      "ground_truth": {
        "recorded_status": "ineligible",
        "semantic_baseline": "UNKNOWN"
      },
      "model": null,
      "original_input": "STATUS -> ineligible\nRISK -> 0.2",
      "provider": "offline",
      "raw_deletion_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "STATUS -> \nRISK -> 0.2",
        "parse_result": "success",
        "parsed_status": "RISK -> 0.2",
        "removed_text": "ineligible",
        "schema_result": "success",
        "semantic_correct": false
      },
      "run_id": "experiment3-20",
      "seed": 20,
      "semantic_port_intervention": {
        "decision_result": "success",
        "failure_class": "successful",
        "input": "STATUS -> UNKNOWN\nRISK -> 0.2",
        "parse_result": "success",
        "parsed_status": "UNKNOWN",
        "port_id": "status",
        "schema_result": "success",
        "semantic_correct": true,
        "substitute_value": "UNKNOWN"
      },
      "temperature": 0.0
    }
  ],
  "configuration": {
    "case_count": 20,
    "execution": "deterministic local parser, schema validator, and decision evaluator",
    "provider": "offline"
  },
  "kind": "experiment3"
}
```
