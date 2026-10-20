# Changelog

## 0.2.0

Both changes are additive: existing code behaves as it did in 0.1.6.

### Added

- `TypeWire.with_creator(fn, *, keep_imports=True)` — an override that keeps the
  wire's declared imports. Applying it registers them; they are resolved, and their
  creators run, only when `fn` awaits `original_creator()` (a 1-arg `fn` never
  resolves them). This matches TypeWire TS `withCreator(fn)` and the Go port.
- `TypeWireContainer(raise_teardown_errors=True)` and
  `TypeWireContainer.sync(raise_teardown_errors=True)` — teardown (explicit
  `teardown()`, `__aexit__` and the sync `__exit__`) runs every cleanup, then raises
  one `TeardownError` if any failed.
- `TeardownError`, exported from `typewirepy`: an `ExceptionGroup` subclass that is
  also a `TypeWireError`. `exceptions` holds every cleanup exception in the order the
  cleanups ran (reverse creation order), each with a note naming its wire; the message
  names the first failure. Works with `except TeardownError`, `except TypeWireError`
  and `except*`. Raised from a context-manager exit whose body is already raising, it
  carries the body's exception as `__context__`.

### Unchanged (now documented and pinned by tests)

- `with_creator(fn)` with the default `keep_imports=False` and a 1-arg `fn` replaces
  the whole subgraph: the override has no imports, so applying it does not register
  the original's imports. The 2-arg form keeps the imports and resolves them before
  `fn` runs.
- Without `raise_teardown_errors`, teardown still logs each cleanup failure and raises
  nothing. Opting in is a behaviour change for that container only: its
  `async with` / `with` block can now raise `TeardownError` on exit.
- Teardown order and once-only cleanup are unchanged. Teardown now removes each
  generator before finalizing it, so a teardown interrupted by a `BaseException`
  (e.g. `KeyboardInterrupt`) never re-runs a cleanup that already ran.
- After teardown the container is empty and reusable; resolving raises
  `WireNotRegisteredError` until wires are applied again.
