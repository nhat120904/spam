# Parallel Incognito Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a separate macOS command that runs multiple workers, each in an independent native Chrome session.

**Architecture:** A ThreadPoolExecutor runs one task per worker. Each worker owns a separate user-data directory and Chrome process. JXA sends Apple Events to that process by PID, then addresses windows and tabs by ID. Existing form JavaScript is reused without modifying the original command.

**Tech Stack:** Python standard library, macOS osascript/JXA, installed Google Chrome. Playwright is only a test dependency.

**Spec:** User-approved design in this conversation: independent process/profile per worker; exact process/window/tab targeting; worker-local cleanup; a new command.

## Global Constraints

- New command: open_incognito_parallel.py. Original command stays untouched.
- Default 2 workers, configurable with --workers; each worker performs one attempt.
- Persistent profiles in runtime/chrome-parallel/worker-N; prohibit concurrent reuse.
- Keep native Chrome and manual CAPTCHA verification; reuse src/*.js.
- Preserve --dry-run, --open-only, --select-only, and configurable positive timeouts.
- Auto mode closes its owned Chrome on success, failure, timeout, or Ctrl+C; manual modes retain it on success.
- No network submission to the live website during verification.

## Review Focus

- A second invocation must not reuse a profile while its Chrome is still alive.
- PID targeting must work when multiple Chrome processes have the same name.
- Cancellation must stop workers before a pending submit and clean up owned processes.
- Cleanup errors must be visible and must not kill another worker's Chrome.
- Missing permission, a closed tab, and malformed browser replies must fail clearly.

### Task 1: Worker session ownership and JXA transport

**Files:** Create open_incognito_parallel.py and test/test_parallel_incognito.py.
**Interfaces:** ChromeSession(profile, chrome, stop); start(); open_tab(mode, url); evaluate(target, source); close_tab(target); close(keep_open=False). ProfileLease(profile) reserves a directory until release.

- [x] Write tests for exclusive profile reservation, PID-specific calls, retained browser ownership, cancellation, and two live independent sessions.
- [x] Run tests and observe missing implementation failures.
- [x] Implement profile reservation, native Chrome process ownership, and JXA transport.
- [x] Run unit tests; run opt-in native integration against a localhost fixture.

### Task 2: Parallel form workflow and CLI

**Interfaces:** run_worker(worker_id, args, stop) returns a status; run_parallel(args) aggregates every worker and handles Ctrl+C; main(argv=None) validates arguments.

- [x] Write tests for simultaneous execution, single submission, worker failure isolation, cleanup, cancellation, manual modes, dry run, and invalid counts/timeouts.
- [x] Observe failures, then implement the workflow using existing form JS.
- [x] Document setup and commands in README-parallel.md and link from README.md.
- [x] Run Python and Node suites; confirm original file is unchanged.
- [x] Review all new code and perform a fresh independent review.

## Execution notes

- This directory has no Git repository; Git worktrees, commits, and Git-based helper scripts do not apply.
- User explicitly requested implementation of the approved design, so execution continues in this chat.
- Native tests revealed Application(pid) could resolve to the default Chrome process. The final transport creates an NSAppleEventDescriptor process address explicitly; native cookie/storage isolation tests now pass.
- Independent review found that cancellation missed already-completed manual workers. A failing regression test reproduced it; the coordinator now retains those sessions until the entire invocation exits normally, and the regression passes.
- Final checks: new suite 19/19 passed including all three native tests; Node 35/35 passed; Windows suite 10/10 passed. Full Python run: 45 tests, 5 pre-existing failures in the unchanged original command's tests, 3 opt-in native tests skipped in this run. See runtime/reports/parallel-chrome-verification.md.
