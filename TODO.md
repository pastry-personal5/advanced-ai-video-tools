# TODO

## Branch review findings

### Security

- [x] **Low:** Resolve native acceptance commands through trusted absolute paths instead of `PATH` to prevent executable substitution in manipulated environments. See [`hardware.py:13,61`](src/advanced_ai_video_tools/system/hardware.py:13) and [`test_native_acceptance.py:124,129`](tests/test_native_acceptance.py:124).

### Test gaps

- [x] **P1:** Add tests for `OSError` and `subprocess.TimeoutExpired` handling in [`hardware.py:60-63`](src/advanced_ai_video_tools/system/hardware.py:60).
- [x] **P1:** Add malformed and empty JSON coverage for [`hardware.py:68-71`](src/advanced_ai_video_tools/system/hardware.py:68).
- [x] **P2:** Test the default profiler runner's exact arguments, 15-second timeout, and `shell=False` contract in [`hardware.py:16-19`](src/advanced_ai_video_tools/system/hardware.py:16).
- [x] **P2:** Verify unsupported platform checks short-circuit without invoking the profiler runner. See [`hardware.py:57-59`](src/advanced_ai_video_tools/system/hardware.py:57) and [`test_hardware.py:30-31`](tests/test_hardware.py:30).

### Maintainability

- [x] **Medium:** Replace the partial `_EmptyQueue` test double and `type: ignore` with a typed queue protocol implementation or controlled real queue. See [`test_native_acceptance.py:35-54,85`](tests/test_native_acceptance.py:35).
- [x] **Medium:** Make screen-capture coordinate mapping robust to Retina scaling, multiple displays, and capture origins. See [`test_native_acceptance.py:136-143`](tests/test_native_acceptance.py:136).
- [x] **Medium:** Rename the warm-start benchmark or add an explicit warm-up sample; the current test creates fresh windows for all samples. See [`test_native_acceptance.py:103-117`](tests/test_native_acceptance.py:103).
- [x] **Low:** Replace the broad recursive Metal-field heuristic with parsing of known profiler capability fields and explicit accepted values. See [`hardware.py:33-45`](src/advanced_ai_video_tools/system/hardware.py:33).
