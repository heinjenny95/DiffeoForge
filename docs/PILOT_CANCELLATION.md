# Prompt cancellation delivery for a running pilot

The desktop controller can now deliver cancellation directly to the existing
Linux/WSL supervisor for a verified running attempt. It no longer has to wait for
the execution worker's stdin reader before that supervisor receives the request.
The original pipe route remains the fallback during preparation or when matching
live evidence is unavailable.

The direct route requires the immutable manifest digest, run/config identities,
running receipt, session-leader identity, matching working directory and private
launch token. It writes the token-bound command atomically and never signals a
numerical PID itself. The original supervisor independently verifies the live
boot/start/parent/session identity before signalling only its owned session.
Its existing escalation remains SIGINT immediately, SIGTERM after ten seconds
and SIGKILL after fifteen seconds. Completion still requires verified shutdown;
an unverified stop cannot become a successful result. No numerical code changes.

Focused tests cover matching delivery, wrong/missing/finished attempt evidence,
the pipe fallback and queued prelaunch cancellation. A harmless Windows-to-WSL
process probe exercises the real supervisor with a child that ignores SIGINT
and SIGTERM; an unrelated process and a checkpoint fixture must survive.
The source probe verified shutdown in 15.72 seconds, including the deliberate
SIGINT/SIGTERM resistance and final session check. These are process-control
checks, not new scientific fits.

The owner's externally terminated attempt remains untouched. Its absence of a
normal completion receipt is not success, and it is not resumed automatically.
The precise cause of every earlier slow cancellation is not established by the
saved evidence. The bounded supervisor probe does not promise a universal GUI
latency during separate preparation or post-processing work.
