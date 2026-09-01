# v2 performance history

This is an append-only summary of accepted Phase 7 performance runs. Raw
per-sample output, profiler output, and local capture files remain outside the
repository.

## Accepted records

### phase7-native-presentation-2026-09-01-01

- Date/time and timezone: 2026-09-01; time not reported; timezone not reported
- Commit: not reported; run used the working tree
- Workload ID/version: `native-window-presentation` / Phase 7 benchmark revision
- Exact command: `QT_QPA_PLATFORM=cocoa ADVANCED_AI_VIDEO_TOOLS_RUN_NATIVE_ACCEPTANCE=1 uv run pytest -m performance tests/test_native_acceptance.py --junitxml=/private/tmp/ai-video-tools-phase7-performance.xml -q`
- Host model: Apple M5 Max (`Black-Laptop-2026`)
- Architecture: Apple Silicon; exact machine architecture not reported
- macOS version/build: not reported
- Python version: not reported
- Qt/PySide6 version: not reported
- Display configuration: interactive Cocoa desktop; exact display not reported
- Power state: not reported
- Warm-up policy: one initial warmup plus two discarded warmups
- Measured sample count: 15
- Samples (seconds): `0.035, 0.035, 0.028, 0.056, 0.026, 0.026, 0.037, 0.026, 0.038, 0.047, 0.025, 0.026, 0.035, 0.036, 0.027`
- Median: `0.035` seconds
- P95: `0.050` seconds
- Minimum/maximum: `0.025` / `0.056` seconds
- Pass/fail: PASS; p95 is below the 3-second budget
- Anomalies: none reported
- Comparability notes: accepted native presentation run; compare only with the same workload revision and equivalent interactive Apple Silicon environment

### phase7-native-presentation-2026-09-01-02

- Date/time and timezone: 2026-09-01; Asia/Seoul
- Commit: uncommitted working tree
- Workload ID/version: `native-window-presentation` / Phase 7 benchmark revision
- Exact command: `make performance-test`
- Host model: Apple M5 Max
- Architecture: `arm64`
- macOS version/build: `macOS-26.6.2-arm64-arm-64bit-Mach-O`; build not reported
- Python version: `3.13.5`
- Qt/PySide6 version: `6.11.2`
- Display configuration: interactive Cocoa desktop; exact display not reported
- Power state: not reported
- Warm-up policy: one initial warmup plus two discarded warmups
- Measured sample count: 15
- Samples (seconds): `0.045, 0.025, 0.025, 0.025, 0.029, 0.028, 0.068, 0.069, 0.026, 0.068, 0.044, 0.025, 0.070, 0.031, 0.029`
- Median: `0.029` seconds
- P95: `0.069` seconds
- Minimum/maximum: `0.025` / `0.070` seconds
- Pass/fail: PASS; p95 is below the 3-second budget
- Anomalies: none in the supported direct Make invocation
- Comparability notes: comparable with record 01 at the workload level; environment metadata is more complete in this record

## Record template

```text
Run ID:
Date/time and timezone:
Commit:
Workload ID/version:
Exact command:
Host model:
Architecture:
macOS version/build:
Python version:
Qt/PySide6 version:
Display configuration:
Power state:
Warm-up policy:
Measured sample count:
Median:
P95:
Minimum/maximum:
Pass/fail:
Anomalies:
Comparability notes:
```
