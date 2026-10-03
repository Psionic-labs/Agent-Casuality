# Benchmark result: experiment1

## Methodology
Experiment 1 evaluates the same four counterfactual B/C cells with Agent-Casuality Shapley interaction and a direct 2x2 contrast. Offline mode uses the deterministic scenario evaluators. The current Fastino catalog exposes no structured-output capability, and GLiNER-2.5-Decide returns a single intent classification rather than good/bad branch decisions; therefore the external Experiment 1 path remains blocked until a compatible model/API mode exists.

## Machine-readable result

```json
{
  "aggregate": {
    "agent_casuality": {
      "false_negative": 0,
      "false_positive": 0,
      "false_positive_rate": 0.0,
      "true_negative": 12,
      "true_positive": 12,
      "true_positive_rate": 1.0
    },
    "cache_hits": 0,
    "naive_2x2": {
      "false_negative": 0,
      "false_positive": 0,
      "false_positive_rate": 0.0,
      "true_negative": 12,
      "true_positive": 12,
      "true_positive_rate": 1.0
    },
    "requests": 0
  },
  "configuration": {
    "max_requests": 48,
    "max_tokens": null,
    "num_bootstrap": 20,
    "samples_per_cell": 1,
    "seed": 0
  },
  "kind": "experiment1",
  "provider": "offline",
  "repetitions": 3,
  "rows": [
    {
      "agent_casuality": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          1.0,
          1.0,
          1.0
        ],
        "true_negative": 0,
        "true_positive": 3
      },
      "counterfactual_cells": [
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        },
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        },
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        }
      ],
      "expected_interaction": true,
      "ground_truth": {
        "decision_outcome": "failure",
        "interaction": true
      },
      "input": [
        {
          "content": "Return JSON only with independent fields left and right. Each field must be exactly 'bad' or 'good'. Scenario: interaction.",
          "role": "user"
        }
      ],
      "model": null,
      "naive_2x2": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          1.0,
          1.0,
          1.0
        ],
        "true_negative": 0,
        "true_positive": 3
      },
      "number_of_runs": 3,
      "provider": "offline",
      "raw_model_responses": [],
      "run_id": "experiment1-interaction-0.0-2",
      "scenario": "interaction",
      "seed": 2,
      "temperature": 0.0
    },
    {
      "agent_casuality": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          -1.0,
          -1.0,
          -1.0
        ],
        "true_negative": 3,
        "true_positive": 0
      },
      "counterfactual_cells": [
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        },
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        },
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        }
      ],
      "expected_interaction": false,
      "ground_truth": {
        "decision_outcome": "failure",
        "interaction": false
      },
      "input": [
        {
          "content": "Return JSON only with independent fields left and right. Each field must be exactly 'bad' or 'good'. Scenario: multiple_parents.",
          "role": "user"
        }
      ],
      "model": null,
      "naive_2x2": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          -1.0,
          -1.0,
          -1.0
        ],
        "true_negative": 3,
        "true_positive": 0
      },
      "number_of_runs": 3,
      "provider": "offline",
      "raw_model_responses": [],
      "run_id": "experiment1-multiple_parents-0.0-2",
      "scenario": "multiple_parents",
      "seed": 2,
      "temperature": 0.0
    },
    {
      "agent_casuality": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          1.0,
          1.0,
          1.0
        ],
        "true_negative": 0,
        "true_positive": 3
      },
      "counterfactual_cells": [
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        },
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        },
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        }
      ],
      "expected_interaction": true,
      "ground_truth": {
        "decision_outcome": "failure",
        "interaction": true
      },
      "input": [
        {
          "content": "Return JSON only with independent fields left and right. Each field must be exactly 'bad' or 'good'. Scenario: interaction.",
          "role": "user"
        }
      ],
      "model": null,
      "naive_2x2": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          1.0,
          1.0,
          1.0
        ],
        "true_negative": 0,
        "true_positive": 3
      },
      "number_of_runs": 3,
      "provider": "offline",
      "raw_model_responses": [],
      "run_id": "experiment1-interaction-0.3-2",
      "scenario": "interaction",
      "seed": 2,
      "temperature": 0.3
    },
    {
      "agent_casuality": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          -1.0,
          -1.0,
          -1.0
        ],
        "true_negative": 3,
        "true_positive": 0
      },
      "counterfactual_cells": [
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        },
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        },
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        }
      ],
      "expected_interaction": false,
      "ground_truth": {
        "decision_outcome": "failure",
        "interaction": false
      },
      "input": [
        {
          "content": "Return JSON only with independent fields left and right. Each field must be exactly 'bad' or 'good'. Scenario: multiple_parents.",
          "role": "user"
        }
      ],
      "model": null,
      "naive_2x2": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          -1.0,
          -1.0,
          -1.0
        ],
        "true_negative": 3,
        "true_positive": 0
      },
      "number_of_runs": 3,
      "provider": "offline",
      "raw_model_responses": [],
      "run_id": "experiment1-multiple_parents-0.3-2",
      "scenario": "multiple_parents",
      "seed": 2,
      "temperature": 0.3
    },
    {
      "agent_casuality": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          1.0,
          1.0,
          1.0
        ],
        "true_negative": 0,
        "true_positive": 3
      },
      "counterfactual_cells": [
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        },
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        },
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        }
      ],
      "expected_interaction": true,
      "ground_truth": {
        "decision_outcome": "failure",
        "interaction": true
      },
      "input": [
        {
          "content": "Return JSON only with independent fields left and right. Each field must be exactly 'bad' or 'good'. Scenario: interaction.",
          "role": "user"
        }
      ],
      "model": null,
      "naive_2x2": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          1.0,
          1.0,
          1.0
        ],
        "true_negative": 0,
        "true_positive": 3
      },
      "number_of_runs": 3,
      "provider": "offline",
      "raw_model_responses": [],
      "run_id": "experiment1-interaction-0.7-2",
      "scenario": "interaction",
      "seed": 2,
      "temperature": 0.7
    },
    {
      "agent_casuality": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          -1.0,
          -1.0,
          -1.0
        ],
        "true_negative": 3,
        "true_positive": 0
      },
      "counterfactual_cells": [
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        },
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        },
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        }
      ],
      "expected_interaction": false,
      "ground_truth": {
        "decision_outcome": "failure",
        "interaction": false
      },
      "input": [
        {
          "content": "Return JSON only with independent fields left and right. Each field must be exactly 'bad' or 'good'. Scenario: multiple_parents.",
          "role": "user"
        }
      ],
      "model": null,
      "naive_2x2": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          -1.0,
          -1.0,
          -1.0
        ],
        "true_negative": 3,
        "true_positive": 0
      },
      "number_of_runs": 3,
      "provider": "offline",
      "raw_model_responses": [],
      "run_id": "experiment1-multiple_parents-0.7-2",
      "scenario": "multiple_parents",
      "seed": 2,
      "temperature": 0.7
    },
    {
      "agent_casuality": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          1.0,
          1.0,
          1.0
        ],
        "true_negative": 0,
        "true_positive": 3
      },
      "counterfactual_cells": [
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        },
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        },
        {
          "00": false,
          "01": false,
          "10": false,
          "11": true
        }
      ],
      "expected_interaction": true,
      "ground_truth": {
        "decision_outcome": "failure",
        "interaction": true
      },
      "input": [
        {
          "content": "Return JSON only with independent fields left and right. Each field must be exactly 'bad' or 'good'. Scenario: interaction.",
          "role": "user"
        }
      ],
      "model": null,
      "naive_2x2": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          1.0,
          1.0,
          1.0
        ],
        "true_negative": 0,
        "true_positive": 3
      },
      "number_of_runs": 3,
      "provider": "offline",
      "raw_model_responses": [],
      "run_id": "experiment1-interaction-1.0-2",
      "scenario": "interaction",
      "seed": 2,
      "temperature": 1.0
    },
    {
      "agent_casuality": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          -1.0,
          -1.0,
          -1.0
        ],
        "true_negative": 3,
        "true_positive": 0
      },
      "counterfactual_cells": [
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        },
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        },
        {
          "00": false,
          "01": true,
          "10": true,
          "11": true
        }
      ],
      "expected_interaction": false,
      "ground_truth": {
        "decision_outcome": "failure",
        "interaction": false
      },
      "input": [
        {
          "content": "Return JSON only with independent fields left and right. Each field must be exactly 'bad' or 'good'. Scenario: multiple_parents.",
          "role": "user"
        }
      ],
      "model": null,
      "naive_2x2": {
        "false_negative": 0,
        "false_positive": 0,
        "score_distribution": [
          -1.0,
          -1.0,
          -1.0
        ],
        "true_negative": 3,
        "true_positive": 0
      },
      "number_of_runs": 3,
      "provider": "offline",
      "raw_model_responses": [],
      "run_id": "experiment1-multiple_parents-1.0-2",
      "scenario": "multiple_parents",
      "seed": 2,
      "temperature": 1.0
    }
  ],
  "targets": {
    "agent_casuality_false_positive_under_1_percent": {
      "measured": 0.0,
      "status": "TARGET MET",
      "threshold": 0.01
    },
    "naive_comparison_over_15_percent": {
      "measured": 0.0,
      "status": "TARGET NOT MET",
      "threshold": 0.15
    }
  },
  "temperatures": [
    0.0,
    0.3,
    0.7,
    1.0
  ]
}
```
