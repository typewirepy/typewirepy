# Changelog

## 0.2.0

### Changed (behaviour change)

- **Teardown raises `TeardownError` when cleanups fail.** Teardown now raises by
  default. This covers explicit `teardown()`, `__aexit__` and the sync `__exit__`. It
  runs every cleanup in reverse creation order, once each, and then raises one
  `TeardownError` if any failed.
- **What changes for existing users.** In 0.1.x a failing cleanup was logged and
  swallowed. Now an `async with TypeWireContainer()` or
  `with TypeWireContainer.sync()` block whose cleanup raises will raise on exit. If
  the block itself was already raising, that exception becomes the
  `TeardownError`'s `__context__`.
- **Not affected:** containers whose cleanups don't raise behave exactly as before.
- **To migrate,** handle `TeardownError` (or `TypeWireError`) where the container
  closes, or fix the failing cleanup. To keep the old behaviour for now, pass
  `raise_teardown_errors=False` (deprecated, see below).

### Deprecated

- `raise_teardown_errors=False` on `TypeWireContainer(...)` and
  `TypeWireContainer.sync(...)`. It restores the 0.1.x behaviour: each cleanup failure
  is logged and none is raised. Passing it emits a `DeprecationWarning`, and it will
  be removed in a future release.

### Added

- `TypeWire.with_creator(fn, *, keep_imports=True)` — an override that keeps the
  wire's declared imports. Applying it registers them; they are resolved, and their
  creators run, only when `fn` awaits `original_creator()` (a 1-arg `fn` never
  resolves them). This matches TypeWire TS `withCreator(fn)` and the Go port.
- `TeardownError`, exported from `typewirepy`:
  - It is an `ExceptionGroup` subclass that is also a `TypeWireError`.
  - `exceptions` holds every cleanup exception in the order the cleanups ran
    (reverse creation order). Each carries a note naming its wire.
  - The message names the first failure.
  - `split()`, `subgroup()` and `except*` produce `TeardownError` instances.
- `raise_teardown_errors` keyword on `TypeWireContainer(...)` and
  `TypeWireContainer.sync(...)` (default `True`).

### Unchanged (now documented and pinned by tests)

- **One-arg override:** `with_creator(fn)` with the default `keep_imports=False` and
  a 1-arg `fn` replaces the whole subgraph. The override has no imports, so applying
  it does not register the original's imports.
- **Two-arg override:** the 2-arg form keeps the imports and resolves them before
  `fn` runs.
- **Teardown order:** order and once-only cleanup are unchanged.
- **Interrupted teardown:** teardown now removes each generator before finalizing it,
  so a teardown interrupted by a `BaseException` (e.g. `KeyboardInterrupt`) never
  re-runs a cleanup that already ran.
- **After teardown:** the container is empty and reusable; resolving raises
  `WireNotRegisteredError` until wires are applied again.
- **Python floor:** still 3.11 (`requires-python = ">=3.11"`). `ExceptionGroup` is
  built in, so no backport is needed. The README badge and contributor docs that
  said 3.10 are corrected.
