# Reference runs and launcher lifetime

A native optimizer can stop because its host session disappears, without writing
a numerical stop signal or a terminal result. A terminal-backed execution session
does not itself provide a durable service boundary. Application updates, session
teardown and operating-system events must be distinguished from tolerance stops,
line-search exhaustion and completed output export.

Before recovering an abandoned reference run:

1. Check the driver and native optimizer using command line, working directory and
   creation/start time. A PID alone is insufficient. Briefly recheck for terminal
   finalization or a successor being prepared before declaring interruption.
2. Preserve the original manifest, log, lifecycle prefix and last complete atomic
   checkpoint. Check its hash, iteration, parameter dimensions and finite values;
   a later logged iteration is not necessarily a retained checkpoint.
3. With explicit recovery authorization and fresh stopped-process evidence, use
   `recover_run(..., confirm_process_stopped=True)` to record the interrupted
   lifecycle. This records an unknown exit code honestly; it does not report
   successful optimization or export.
4. Use `prepare_resume_run(..., additional_iterations=0)` for a separate immutable
   successor with the same effective iteration limit. Verify that only documented
   resume-source bindings changed. A later +300 extension requires a successfully
   sealed capped result and verified complete export.

For a deliberately detached Windows driver, verify the actual running process,
not just a successful launch return value. A hidden, one-shot WMI launch with
`CREATE_BREAKAWAY_FROM_JOB` and the base interpreter can be checked using
`IsProcessInJob`. A venv redirector may create a child job even when its launcher
was detached; checking only the launcher can therefore give a false assurance.
Retain the same verified package/source paths when using the base interpreter.
Record command, working directory, creation time and process-isolation evidence.
This is an operational launch arrangement, not a new desktop service or automatic
recovery facility, and it cannot protect against a machine shutdown or explicit
WSL termination. It must never create a second optimizer or restart a failed run.

Keep supervision separate from computation. A read-only monitor can report a
terminal failure or verified tolerance convergence plus complete final export;
it must not recover or advance the scientific chain. Quiet gradient/export work
does not establish a hang. Verify each capped export before another authorized
block and retain the original results, reviews and PCA.

Deformetrica 4.3 restores parameters and iteration but resets objective baseline,
gradient and line-search state. Identical scientific configuration does not imply
an identical uninterrupted optimizer trajectory. Numerical tolerance completion
and anatomical acceptance remain separate.

Verification: the existing ten recovery/resume regressions in `tests/test_runs.py`
passed. A guarded native launch rejected job-bound driver attempts before any
optimizer started, then verified an independent, windowless driver process and
the original native package/runtime identity. Complete convergence, final export
and scientific acceptance require their own later evidence.
