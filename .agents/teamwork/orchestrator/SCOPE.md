# Scope Document: Technical Evaluation & Critical Review of 3-Step Pipeline Proposal

## Architecture & Objective
Evaluate feasibility, critique deeply, and review technical risks and blind spots in the 3-step pipeline proposal:
1. Compact Data Map (schema, sheet, columns, types, unique value labels for low-cardinality, counts & explicit sample labels for high-cardinality)
2. Targeted Sandbox Exploration (search data, return relevant context via observation loop)
3. Suspicious Result Sanity Check (0, [], empty joins, row counts before/after filter, applied labels)
Cross-referencing directly against 30 questions in `result/qwen25_14b_1m_code_only_rulebook_20261111_155610/eval_dev_30_colab_a100_40gb_ctx16384/failure_analysis.md`.

## Feature Inventory / Evaluation Items
| # | Item | Scope | Owner Milestone | Status |
|---|------|-------|-----------------|--------|
| 1 | R1: Step-by-Step Feasibility & Critique | Step 1, 2, 3 mechanisms, pros/cons, real-world feasibility, gaps | M1 | IN_PROGRESS |
| 2 | R2: Case-by-Case Cross-Reference | 30 questions from failure_analysis.md mapped to solved vs unsolved vs worsened | M1 | IN_PROGRESS |
| 3 | R3: Blind Spots & Technical Risks | Latency/offline docker, Abstain gate & PA metric, messy Excel/tables, sandbox errors/hallucinations | M2 | IN_PROGRESS |
| 4 | R4: Synthesis, Recommendations & Roadmap | Verdict, keep vs adjust, priorities before retraining model | M3 | PLANNED |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Deep Analysis & Case Mapping | failure_analysis.md 30 cases mapping + Step 1/2/3 evaluation | none | IN_PROGRESS |
| M2 | Risk & Blind Spot Assessment | Technical constraints, Docker offline, PA score impact, complex data formats | none | IN_PROGRESS |
| M3 | Comprehensive Technical Synthesis | Final critical evaluation report answering R1-R4 & Acceptance Criteria | M1, M2 | PLANNED |
