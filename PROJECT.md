# Project: Interpresona — FFXIV Dialogue and Interface Text Translation Tool

## Architecture
The system consists of three main components:
1. **Binary Parser/Injector Engine (Interpresona-PIE)**: Parses binary FFXIV EXH (Excel Header) and EXD (Excel Data) sheet formats from scratch. It handles reading columns, string tables, row headers, and rebuilding them upon injection.
2. **Translation pipeline (Interpresona-Trans-Pipeline)**: Extracts localizable strings, parses/masks control codes (using placeholder tags like `⟪VAR_X⟫`), handles translation formatting, and unmasks tags back to binary control codes on injection.
3. **Control Interface (Interpresona-GUI)**: A user-friendly interface to manage files, trigger extraction/injection, view differences, and run translation simulation.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| 1 | Research & Format Proof-of-Concept | Research FFXIV EXH/EXD format, control code structure, and document variables. Create mock generator and proof-of-concept parsing scripts. | None | COMPLETED |
| 2 | E2E Testing Framework | Create E2E test runner, mock file creators, and test suites (Tiers 1-4) in accordance with the Dual Track methodology. | M1 | COMPLETED |
| 3 | Core Parser & Injector Pipeline | Implement robust binary EXH/EXD parser, string extractor, variable masking/unmasking, and non-corrupting binary injector. | M2 | COMPLETED |
| 4 | User Management Interface | Develop single-screen UI (CLI/GUI) to orchestrate loading files, viewing, and executing the translation pipeline. | M3 | COMPLETED |
| 5 | Integration & Hardening | Run E2E tests, perform adversarial coverage hardening (Tier 5), run forensic integrity audit, and achieve final verification. | M4 | COMPLETED |

## Interface Contracts
### Binary Parser ↔ Translation Pipeline
- `extract()`: Parses EXH and EXD sheets and extracts all text column fields with row IDs and raw bytes as `ExtractionRecord` instances.
- `mask(raw_string: bytes) -> MaskedString`: Identifies FFXIV control codes (starting with `0x02`, ending with `0x03`) and masks them with placeholder tokens (e.g. `⟪VAR_0⟫`), returning the masked string and a placeholder map.
- `unmask(masked_string: str, placeholder_map: dict) -> bytes`: Restores placeholders back to original FFXIV control code bytes.
- `inject_all() -> dict[int, bytes]`: Rebuilds EXD structures with new string offsets and lengths, updating the binary headers and offset arrays.

## Code Layout
All source code and tests are located in the `interpresona` directory.
- `interpresona/core/`: Contains source code.
  - `parser.py`: EXH/EXD parser and injector logic.
  - `pipeline.py`: Extraction, masking/unmasking, and translation logic.
  - `injector.py`: EXD binary rebuild and injection.
  - `masker.py`: Variable masking and placeholder integrity checks.
  - `sqpack.py`: SqPack game directory reader and index mapping.
  - `session.py`: Session backup, save, and load structures.
- `interpresona/gui.py`: Single-screen TKinter user interface.
- `interpresona/tests/`: Unit and integration tests.
  - `mock_generator.py`: Mock EXH/EXD generators for tests.
  - `test_poc_parser.py`: Verification tests for proof-of-concept parsing.
  - `test_adversarial.py`: Boundary verification and adversarial parsing tests.
  - `test_pipeline_integration.py`: Integration tests for the full pipeline.
  - `run_all_tests.py`: CLI test suite runner.
- `interpresona/docs/`: Research documents and specifications.
