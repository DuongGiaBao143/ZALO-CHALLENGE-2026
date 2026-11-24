# Project: DataMate Technical Handoff Plan (HANDOFF_PLAN.md)

## Architecture
- Product: Comprehensive Technical Handoff Document `HANDOFF_PLAN.md` at repository root.
- Domain: Zalo AI Challenge 2026 - DataMate (Natural-Language Vietnamese QA over Tabular Data).
- Target Model: Qwen/Qwen2.5-14B-Instruct-1M.
- Components Covered:
  1. 6 Domain-Agnostic Lean Helpers in `src/agent/sandbox.py`.
  2. ReAct reasoning protocol, Ephemeral Thinking (context pruning for 16,384 tokens), and Dynamic In-Context Rule Generalization (`rulebook.md` + shop `README.md`).
  3. Abstain-First Gate and Empirical Error Analysis on Dev 30 benchmark (fixing PA -0.1667 base / -0.0667 LoRA).
  4. Google Colab evaluation guide (`notebooks/Evaluate_Qwen25_14B_1M_Colab_G4.ipynb`) and LoRA SFT training trajectory specification.
  5. Git version control: commit & push to remote `origin/giabao`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | 6 Lean Helpers Spec | Signature, params, return, edge cases, pseudo-code for explore_data, fuzzy_find, load_clean_df, resolve_date, emit_obs, emit_final | M2 | R1.1 |
| 2 | ReAct & Ephemeral Thinking | 3-5 line Thought, stripping raw think from turns 1..N-1, preserving summary+code+obs to fit 16384 ctx | M2 | R1.2 |
| 3 | Dynamic Rule Extraction | Adapting to unknown domains in Private Test via rulebook.md and shop README.md; fallback to Rulebook §7 abstain | M2 | R1.2 |
| 4 | Abstain-First Gate Design | Analysis of Dev 30 errors, empty filter trap, unverified 0, out of scope §7 -> abstain (0 pts instead of -1 pt) | M2 | R1.3 |
| 5 | Colab Eval & LoRA Guide | Step-by-step Colab notebook run, Qwen2.5-14B-Instruct-1M baseline, SFT dataset format (Thought + Helper trajectory) | M2 | R1.4 |
| 6 | Scope Enforcement | Strict check: no modifications to src/ or notebooks/ | M3 | R2 |
| 7 | Git Commit & Push | Commit HANDOFF_PLAN.md and push to branch giabao | M4 | R3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Survey & Codebase Investigation | Inspect sandbox.py, solver.py, rulebook.md, evaluation notebook, benchmark logs | none | DONE |
| M2 | Draft HANDOFF_PLAN.md | Write complete, production-grade HANDOFF_PLAN.md at repo root | M1 | DONE |
| M3 | Review & Forensic Audit | Check against acceptance criteria, ensure zero changes to src/notebooks | M2 | DONE |
| M4 | Git Commit & Push | Commit HANDOFF_PLAN.md and push to origin/giabao | M3 | DONE |

## Interface Contracts & Guidelines
- File path: `d:\PROJECT\ZALO-AI-CHALLENGE-2026\HANDOFF_PLAN.md`
- Target Branch: `giabao`
- Scope constraint: NO direct edits to `src/` or `notebooks/`.
