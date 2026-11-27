# v130 automatic process recording

Enable **Auto-record process** once in the left rail. The choice is remembered
for future sessions. Recording begins when the main window is visible. Every
completed computation automatically exports the current MP4 and starts the next
recording, so subsequent QC and exploration are included. **Finish** exports
without closing DiffeoForge; **New recording** continues afterwards. Closing
waits for presentation export after the existing scientific close guards.

Videos go to the current project’s `recordings` folder. Before a project exists,
they remain in the local application recording folder. **Videos** opens the latest
destination. Recording is opt-in and local; it never uploads a video.

## Timing and capture

- Active interaction is sampled at three frames per second and played at 30 fps
  (10×). After 30 seconds without interaction, waiting is compressed to 300×.
  Mouse/keyboard interaction and video playback restore active capture;
  minimized windows use waiting mode. Long calculation waits therefore take
  much less presentation time.
- The recorder renders only DiffeoForge-owned Qt windows, dialogs and popups,
  with the pointer/click location, real session time and speed shown. While
  recording, file choosers use Qt dialogs so they are captured too. Other
  applications and audio are excluded. Demo content remains a separate removal
  backlog item and is excluded from recording.
- A declared one-second final hold makes the actual terminal screen readable.
  Each MP4 has a JSON timing companion with mode changes, sample/frame counts,
  sizes and hashes. This is a presentation recording, not scientific run evidence.
- Delayed active samples are visibly marked as held frames and listed in the
  timing companion. No recorder can reconstruct UI motion missed during a GUI
  stall, operating-system sleep or application failure. Three-fps sampling also
  cannot retain every sub-second interaction. Independent first-use and long
  real-study acceptance remain open.

## Resource and failure boundaries

Encoding runs on a separate thread with a bounded six-frame queue, one FFmpeg
encoding thread and compressed H.264 segments. The recorder neither reloads
mesh data nor changes calculation parameters. Assembly copies encoded video
packets, verifies frame count/dimensions/rate and hashes the delivered copy;
temporary fragments are removed only after verified local delivery.

An export/capture failure reports the problem without stopping or restarting
scientific work. Completed fragments remain recoverable through **Recover
interrupted video…**. Recovery requires the recording folder, an available OS
lock and unchanged sealed segment hashes; it exports a labelled partial video.
An unfinished segment can be lost after a crash. This action never recovers or
resumes a scientific run. Disk space below 512 MiB stops new recording segments.

## Engineering verification

Native FFmpeg encode/decode fixtures check both timing rates, segment joins,
final state, atomic project delivery, live-lock rejection, partial recovery and
tamper/path/dimension rejection. Qt tests exercise owned/foreign windows,
dialog capture, saved opt-in, smoke isolation, GUI-thread delivery, automatic
computation boundaries and follow-up recording, and export-aware closing.
Existing pilot lifecycle, responsiveness, result-release and packaging checks
remain separate from scientific validation. Frozen/installed delivery is
tracked separately from source implementation.

A public 178,800-face mesh fixture exercised proxy and original-detail views,
live camera motion and 1080p capture: 33 samples over 10.55 seconds, 62 decoded
frames including the end hold, 35 distinct video frames, no queue drops or
capture gaps, and successful native Qt MP4 playback. The same loaded mesh object
and source bytes were preserved. This short engineering observation is not a
12-hour recording or scientific performance qualification.
