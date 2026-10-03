# Benchmark result: baseline

## Methodology
The named historical Phase 2 memory baseline was passed through its adapter for all five scenarios. No executable or version-pinned checkout exists, so execution is blocked and unsupported capabilities are explicitly unscored.

## Machine-readable result

```json
{
  "baseline": {
    "command": "historical Phase 2 executable (not present in this checkout)",
    "commit_or_build": null,
    "input": "the five deterministic benchmark scenarios",
    "methodology": "The named historical Phase 2 memory implementation is not an independent diff-oriented debugger. It is retained as the required baseline reference, but no executable, pinned checkout, or output contract is present.",
    "procedure": "adapter invoked once per scenario",
    "status": "blocked",
    "tool": "Phase 2 sdk/memory.py resource dependency capture",
    "version": "unavailable"
  },
  "comparison": [
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "cause_identification",
      "comparable": false,
      "scenario": "single_cause"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "multiple_parents",
      "comparable": false,
      "scenario": "single_cause"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "distractor_handling",
      "comparable": false,
      "scenario": "single_cause"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "interaction",
      "comparable": false,
      "scenario": "single_cause"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "shared_state_causality",
      "comparable": false,
      "scenario": "single_cause"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "minimal_causal_reduction",
      "comparable": false,
      "scenario": "single_cause"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "cause_identification",
      "comparable": false,
      "scenario": "multiple_parents"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "multiple_parents",
      "comparable": false,
      "scenario": "multiple_parents"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "distractor_handling",
      "comparable": false,
      "scenario": "multiple_parents"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "interaction",
      "comparable": false,
      "scenario": "multiple_parents"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "shared_state_causality",
      "comparable": false,
      "scenario": "multiple_parents"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "minimal_causal_reduction",
      "comparable": false,
      "scenario": "multiple_parents"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "cause_identification",
      "comparable": false,
      "scenario": "interaction"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "multiple_parents",
      "comparable": false,
      "scenario": "interaction"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "distractor_handling",
      "comparable": false,
      "scenario": "interaction"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "interaction",
      "comparable": false,
      "scenario": "interaction"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "shared_state_causality",
      "comparable": false,
      "scenario": "interaction"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "minimal_causal_reduction",
      "comparable": false,
      "scenario": "interaction"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "cause_identification",
      "comparable": false,
      "scenario": "distractor"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "multiple_parents",
      "comparable": false,
      "scenario": "distractor"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "distractor_handling",
      "comparable": false,
      "scenario": "distractor"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "interaction",
      "comparable": false,
      "scenario": "distractor"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "shared_state_causality",
      "comparable": false,
      "scenario": "distractor"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "minimal_causal_reduction",
      "comparable": false,
      "scenario": "distractor"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "cause_identification",
      "comparable": false,
      "scenario": "memory_contamination"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "multiple_parents",
      "comparable": false,
      "scenario": "memory_contamination"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "distractor_handling",
      "comparable": false,
      "scenario": "memory_contamination"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "interaction",
      "comparable": false,
      "scenario": "memory_contamination"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "shared_state_causality",
      "comparable": false,
      "scenario": "memory_contamination"
    },
    {
      "agent_casuality": "measured by deterministic benchmark",
      "baseline": "unsupported",
      "capability": "minimal_causal_reduction",
      "comparable": false,
      "scenario": "memory_contamination"
    }
  ],
  "environment": {
    "platform": "Windows-11-10.0.26200-SP0",
    "python": "3.12.13 (main, Jun 23 2026, 15:23:43) [MSC v.1944 64 bit (AMD64)]",
    "repository_head": "a3427a67c551df4f936a85161d25ef6457e6917e",
    "tools_checked": [
      {
        "reason": "does not analyze execution causality or interactions",
        "tool": "git",
        "usable": false,
        "version": "2.54.0.windows.1"
      },
      {
        "reason": "explicitly excluded by the baseline task",
        "tool": "OpenCode",
        "usable": false,
        "version": "1.18.32"
      },
      {
        "reason": "no executable or pinned checkout exists",
        "tool": "historical Phase 2 baseline",
        "usable": false,
        "version": "unavailable"
      }
    ]
  },
  "experiment": "baseline comparison",
  "kind": "baseline",
  "limitations": [
    "No independent diff-oriented baseline executable is available in this checkout.",
    "Git 2.54.0.windows.1 was available but cannot analyze execution causality or interactions.",
    "OpenCode 1.18.32 was installed but explicitly excluded by the task.",
    "The current ResourceRegistry and causal engine are not substituted for the baseline.",
    "Unsupported capabilities have no precision, recall, or failure score.",
    "the named historical Phase 2 baseline has no executable, pinned checkout, or documented input contract; scenario artifact was D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py"
  ],
  "reproducibility": {
    "command": "uv run casuality-benchmark baseline",
    "configuration": {
      "adapter": "Phase 2 sdk/memory.py resource dependency capture"
    },
    "execution_attempted": false,
    "exit_code": null,
    "required_input": "the five benchmark scenarios under benchmark/ground_truth/"
  },
  "scenarios": [
    {
      "capabilities": {
        "cause_identification": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "distractor_handling": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "interaction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "minimal_causal_reduction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "multiple_parents": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "shared_state_causality": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        }
      },
      "execution": {
        "exit_code": null,
        "output": null,
        "status": "blocked",
        "stderr": "the named historical Phase 2 baseline has no executable, pinned checkout, or documented input contract; scenario artifact was D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
        "stdout": ""
      },
      "input_artifact": "D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
      "normalized_metrics": {},
      "scenario": "single_cause",
      "status": "blocked"
    },
    {
      "capabilities": {
        "cause_identification": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "distractor_handling": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "interaction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "minimal_causal_reduction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "multiple_parents": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "shared_state_causality": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        }
      },
      "execution": {
        "exit_code": null,
        "output": null,
        "status": "blocked",
        "stderr": "the named historical Phase 2 baseline has no executable, pinned checkout, or documented input contract; scenario artifact was D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
        "stdout": ""
      },
      "input_artifact": "D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
      "normalized_metrics": {},
      "scenario": "multiple_parents",
      "status": "blocked"
    },
    {
      "capabilities": {
        "cause_identification": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "distractor_handling": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "interaction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "minimal_causal_reduction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "multiple_parents": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "shared_state_causality": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        }
      },
      "execution": {
        "exit_code": null,
        "output": null,
        "status": "blocked",
        "stderr": "the named historical Phase 2 baseline has no executable, pinned checkout, or documented input contract; scenario artifact was D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
        "stdout": ""
      },
      "input_artifact": "D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
      "normalized_metrics": {},
      "scenario": "interaction",
      "status": "blocked"
    },
    {
      "capabilities": {
        "cause_identification": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "distractor_handling": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "interaction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "minimal_causal_reduction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "multiple_parents": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "shared_state_causality": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        }
      },
      "execution": {
        "exit_code": null,
        "output": null,
        "status": "blocked",
        "stderr": "the named historical Phase 2 baseline has no executable, pinned checkout, or documented input contract; scenario artifact was D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
        "stdout": ""
      },
      "input_artifact": "D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
      "normalized_metrics": {},
      "scenario": "distractor",
      "status": "blocked"
    },
    {
      "capabilities": {
        "cause_identification": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "distractor_handling": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "interaction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "minimal_causal_reduction": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "multiple_parents": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        },
        "shared_state_causality": {
          "reason": "the selected baseline has no runnable implementation or output contract in this checkout",
          "status": "unsupported"
        }
      },
      "execution": {
        "exit_code": null,
        "output": null,
        "status": "blocked",
        "stderr": "the named historical Phase 2 baseline has no executable, pinned checkout, or documented input contract; scenario artifact was D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
        "stdout": ""
      },
      "input_artifact": "D:\\Coding\\Agent-Casuality\\benchmark\\scenarios.py",
      "normalized_metrics": {},
      "scenario": "memory_contamination",
      "status": "blocked"
    }
  ]
}
```

## Capability Comparison

| Scenario | Capability | Baseline | Agent-Casuality | Comparable |
| --- | --- | --- | --- | --- |
| single_cause | cause_identification | unsupported | measured by deterministic benchmark | no |
| single_cause | multiple_parents | unsupported | measured by deterministic benchmark | no |
| single_cause | distractor_handling | unsupported | measured by deterministic benchmark | no |
| single_cause | interaction | unsupported | measured by deterministic benchmark | no |
| single_cause | shared_state_causality | unsupported | measured by deterministic benchmark | no |
| single_cause | minimal_causal_reduction | unsupported | measured by deterministic benchmark | no |
| multiple_parents | cause_identification | unsupported | measured by deterministic benchmark | no |
| multiple_parents | multiple_parents | unsupported | measured by deterministic benchmark | no |
| multiple_parents | distractor_handling | unsupported | measured by deterministic benchmark | no |
| multiple_parents | interaction | unsupported | measured by deterministic benchmark | no |
| multiple_parents | shared_state_causality | unsupported | measured by deterministic benchmark | no |
| multiple_parents | minimal_causal_reduction | unsupported | measured by deterministic benchmark | no |
| interaction | cause_identification | unsupported | measured by deterministic benchmark | no |
| interaction | multiple_parents | unsupported | measured by deterministic benchmark | no |
| interaction | distractor_handling | unsupported | measured by deterministic benchmark | no |
| interaction | interaction | unsupported | measured by deterministic benchmark | no |
| interaction | shared_state_causality | unsupported | measured by deterministic benchmark | no |
| interaction | minimal_causal_reduction | unsupported | measured by deterministic benchmark | no |
| distractor | cause_identification | unsupported | measured by deterministic benchmark | no |
| distractor | multiple_parents | unsupported | measured by deterministic benchmark | no |
| distractor | distractor_handling | unsupported | measured by deterministic benchmark | no |
| distractor | interaction | unsupported | measured by deterministic benchmark | no |
| distractor | shared_state_causality | unsupported | measured by deterministic benchmark | no |
| distractor | minimal_causal_reduction | unsupported | measured by deterministic benchmark | no |
| memory_contamination | cause_identification | unsupported | measured by deterministic benchmark | no |
| memory_contamination | multiple_parents | unsupported | measured by deterministic benchmark | no |
| memory_contamination | distractor_handling | unsupported | measured by deterministic benchmark | no |
| memory_contamination | interaction | unsupported | measured by deterministic benchmark | no |
| memory_contamination | shared_state_causality | unsupported | measured by deterministic benchmark | no |
| memory_contamination | minimal_causal_reduction | unsupported | measured by deterministic benchmark | no |

## Baseline Description

Tool: `Phase 2 sdk/memory.py resource dependency capture`

Version: `unavailable`

Command: `historical Phase 2 executable (not present in this checkout)`

## Version and Environment

Platform: `Windows-11-10.0.26200-SP0`

Python: `3.12.13 (main, Jun 23 2026, 15:23:43) [MSC v.1944 64 bit (AMD64)]`

Repository head: `a3427a67c551df4f936a85161d25ef6457e6917e`

## Limitations

- No independent diff-oriented baseline executable is available in this checkout.
- Git 2.54.0.windows.1 was available but cannot analyze execution causality or interactions.
- OpenCode 1.18.32 was installed but explicitly excluded by the task.
- The current ResourceRegistry and causal engine are not substituted for the baseline.
- Unsupported capabilities have no precision, recall, or failure score.
- the named historical Phase 2 baseline has no executable, pinned checkout, or documented input contract; scenario artifact was D:\Coding\Agent-Casuality\benchmark\scenarios.py

## Reproduction

```powershell
uv run casuality-benchmark baseline
```

The available Git executable was audited but rejected as a baseline because it does not consume these execution artifacts or produce causal analysis.
