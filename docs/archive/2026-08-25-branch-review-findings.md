# Archived Branch Review Findings

Archived from the repository root on 2026-08-25. All findings were completed
and verified before archival.

## Security

- [x] **Low:** Resolve native acceptance commands through trusted absolute paths instead of `PATH` to prevent executable substitution in manipulated environments. See [`hardware.py`](../../src/advanced_ai_video_tools/system/hardware.py) and [`test_native_acceptance.py`](../../tests/test_native_acceptance.py).

## Test gaps

- [x] **P1:** Add tests for `OSError` and `subprocess.TimeoutExpired` handling in [`hardware.py`](../../src/advanced_ai_video_tools/system/hardware.py).
- [x] **P1:** Add malformed and empty JSON coverage for [`hardware.py`](../../src/advanced_ai_video_tools/system/hardware.py).
- [x] **P2:** Test the default profiler runner's exact arguments, 15-second timeout, and `shell=False` contract in [`hardware.py`](../../src/advanced_ai_video_tools/system/hardware.py).
- [x] **P2:** Verify unsupported platform checks short-circuit without invoking the profiler runner. See [`hardware.py`](../../src/advanced_ai_video_tools/system/hardware.py) and [`test_hardware.py`](../../tests/test_hardware.py).

## Maintainability

- [x] **Medium:** Replace the partial `_EmptyQueue` test double and `type: ignore` with a typed queue protocol implementation or controlled real queue. See [`test_native_acceptance.py`](../../tests/test_native_acceptance.py).
- [x] **Medium:** Make screen-capture coordinate mapping robust to Retina scaling, multiple displays, and capture origins. See [`test_native_acceptance.py`](../../tests/test_native_acceptance.py).
- [x] **Medium:** Rename the warm-start benchmark or add an explicit warm-up sample; the current test creates fresh windows for all samples. See [`test_native_acceptance.py`](../../tests/test_native_acceptance.py).
- [x] **Low:** Replace the broad recursive Metal-field heuristic with parsing of known profiler capability fields and explicit accepted values. See [`hardware.py`](../../src/advanced_ai_video_tools/system/hardware.py).
