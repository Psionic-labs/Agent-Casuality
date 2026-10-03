# Benchmark result

```json
{
  "aggregate": {
    "false_interaction_rate": 0.0,
    "requests": 0
  },
  "kind": "experiment1",
  "provider": "offline",
  "rows": [
    {
      "expected_interaction": true,
      "false_interaction_detections": 0,
      "interaction_detections": 3,
      "interaction_score_distribution": [
        1.0,
        1.0,
        1.0
      ],
      "missed_interactions": 0,
      "number_of_runs": 3,
      "raw_model_responses": [],
      "scenario": "interaction",
      "temperature": 0.0
    },
    {
      "expected_interaction": false,
      "false_interaction_detections": 0,
      "interaction_detections": 0,
      "interaction_score_distribution": [
        -1.0,
        -1.0,
        -1.0
      ],
      "missed_interactions": 0,
      "number_of_runs": 3,
      "raw_model_responses": [],
      "scenario": "multiple_parents",
      "temperature": 0.0
    },
    {
      "expected_interaction": true,
      "false_interaction_detections": 0,
      "interaction_detections": 3,
      "interaction_score_distribution": [
        1.0,
        1.0,
        1.0
      ],
      "missed_interactions": 0,
      "number_of_runs": 3,
      "raw_model_responses": [],
      "scenario": "interaction",
      "temperature": 0.3
    },
    {
      "expected_interaction": false,
      "false_interaction_detections": 0,
      "interaction_detections": 0,
      "interaction_score_distribution": [
        -1.0,
        -1.0,
        -1.0
      ],
      "missed_interactions": 0,
      "number_of_runs": 3,
      "raw_model_responses": [],
      "scenario": "multiple_parents",
      "temperature": 0.3
    },
    {
      "expected_interaction": true,
      "false_interaction_detections": 0,
      "interaction_detections": 3,
      "interaction_score_distribution": [
        1.0,
        1.0,
        1.0
      ],
      "missed_interactions": 0,
      "number_of_runs": 3,
      "raw_model_responses": [],
      "scenario": "interaction",
      "temperature": 0.7
    },
    {
      "expected_interaction": false,
      "false_interaction_detections": 0,
      "interaction_detections": 0,
      "interaction_score_distribution": [
        -1.0,
        -1.0,
        -1.0
      ],
      "missed_interactions": 0,
      "number_of_runs": 3,
      "raw_model_responses": [],
      "scenario": "multiple_parents",
      "temperature": 0.7
    },
    {
      "expected_interaction": true,
      "false_interaction_detections": 0,
      "interaction_detections": 3,
      "interaction_score_distribution": [
        1.0,
        1.0,
        1.0
      ],
      "missed_interactions": 0,
      "number_of_runs": 3,
      "raw_model_responses": [],
      "scenario": "interaction",
      "temperature": 1.0
    },
    {
      "expected_interaction": false,
      "false_interaction_detections": 0,
      "interaction_detections": 0,
      "interaction_score_distribution": [
        -1.0,
        -1.0,
        -1.0
      ],
      "missed_interactions": 0,
      "number_of_runs": 3,
      "raw_model_responses": [],
      "scenario": "multiple_parents",
      "temperature": 1.0
    }
  ],
  "targets": {
    "agent_casuality_false_positive_under_1_percent": {
      "measured": 0.0,
      "met": true,
      "threshold": 0.01
    },
    "naive_comparison_over_15_percent": {
      "reason": "no vendor adapter or named naive baseline is included",
      "status": "not_evaluated"
    }
  }
}
```
