# Development practices

## Code and dependencies

- Use Python 3.10+, `uv`, precise public types, `pathlib.Path`, frozen typed
  values across boundaries, PySide6 for GUI code, and Loguru for diagnostics.
- Prefer clear standard-library solutions. Catch narrow exceptions, retain
  causes, and avoid placeholders, silent fallbacks, `Any`, and unexplained
  abstractions.
- Keep dependencies in `pyproject.toml` and commit matching `uv.lock` changes.
- Configure Loguru once at startup; modules must not add sinks or standard
  library loggers.

Black is canonical with its configured effectively unlimited line width. Use:

```bash
make install
make format
make lint
make test
make check
make run
```

`make performance-test` and `make gui-capture-test` are opt-in native
presentation checks and are not part of `make check`.

## Runtime safety

- Never probe, scan media, encode, or infer on the GUI thread. Marshal results
  through Qt signals and give every worker one owner and joined shutdown path.
- Preserve queued, active, cancelling, cancelled, failed, and completed states;
  run one frontend-independent FIFO job at a time.
- Execute external tools with argument arrays, `shell=False`, explicit timeouts,
  bounded output, process-group cancellation, and an INFO `RUN <quoted args>`
  diagnostic immediately before launch.
- Use Qt application-data/cache locations. Persist only typed, schema-versioned,
  non-secret settings through private temporary files and atomic replacement;
  quarantine malformed current documents and reject newer schemas.
- Blank executable paths mean `PATH`; a blank model directory means discovery
  beside Real-ESRGAN. Validate tool edits off-thread and apply them only to
  future drafts.
- Bind dropped-stream acknowledgement to the exact reviewed job inventory.
- Keep rotating local logs (`10 MB`, five retained, `enqueue=True`) and add no
  telemetry, update checks, downloads, or other application network activity.

## Documentation and validation

[ARCHITECTURE.md](ARCHITECTURE.md) owns implemented/binding behavior;
[v3/plans.md](v3/plans.md) owns roadmap status; each authorized phase file owns
its scope and evidence. User guides describe only verified behavior. Update
affected documents together.

Use unit tests for validation, commands, paths, state, and error mapping;
integration tests for tiny FFmpeg fixtures; and fakes for Real-ESRGAN. Default
tests require no GPU, network, large model, or long media. Native tests run only
through their Make targets on an interactive supported Apple Silicon desktop.
If a check cannot run, report the command, blocker, and next-best evidence.
