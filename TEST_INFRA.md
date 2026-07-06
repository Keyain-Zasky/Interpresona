# E2E Test Infra: Interpresona

## Test Philosophy
- Opaque-box, requirement-driven. No dependency on implementation design.
- Methodology: Category-Partition + BVA + Pairwise + Workload Testing.

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | Study & Spec Verification | ORIGINAL_REQUEST §R1 | 5      | 5      | ✓      |
| 2 | String Extraction | ORIGINAL_REQUEST §R2 | 5      | 5      | ✓      |
| 3 | Variable Masking | ORIGINAL_REQUEST §R2 | 5      | 5      | ✓      |
| 4 | Non-Corrupting Injection | ORIGINAL_REQUEST §R2 | 5      | 5      | ✓      |
| 5 | Orchestration Interface | ORIGINAL_REQUEST §R3 | 5      | 5      | ✓      |

## Test Architecture
- Test runner: `python interpresona/tests/run_all_tests.py` or `pytest`
- Test case format: Automated input and validation scripts verifying the preservation of variables and binary data integrity.
- Directory layout: `interpresona/tests/`

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Extract, mask, simulate translate, unmask, and inject a complex dialogue sheet with multiple variables, conditions, and line breaks, verifying identical variable structures and binary consistency. | F2, F3, F4 | High |
| 2 | Load and display a translated sheet in the UI, verify strings can be modified manually and successfully written to output files. | F2, F3, F4, F5 | Medium |

## Coverage Thresholds
- Tier 1: ≥5 per feature
- Tier 2: ≥5 per feature (where boundaries exist)
- Tier 3: pairwise coverage of major feature interactions
- Tier 4: ≥5 realistic application scenarios
