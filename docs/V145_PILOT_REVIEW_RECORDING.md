# v145: pilot-specific recording speeds

Owner clarification, 20 October 2026: normal interaction, including path selection
and landmarking, must remain **10×**. Only visual evaluation of pilot fits uses
**2×**. Busy calculation and loading retain **1000×**. This replaces v144's broad
1× human-action rate.

The pilot fit comparison viewer explicitly marks its recording context. Ready
individual, combined and saved-fit comparison views use 2×; the pilot dashboard,
other reviews and ordinary owned dialogs retain 10×. Owned popups inherit the
viewer context. Busy tasks and pending mesh loads take precedence, including
while a popup is open. Closing the viewer restores the ordinary action rate.
Mouse movement, typing and focus do not select a slower mode.

New MP4 timing companions declare all three rates; capture scheduling, status,
tooltip and video footer agree. The recording remains one continuous opted-in
project session, with bounded background encoding and GUI-stall omission.
Delayed capture is declared in both interaction modes. Existing completed videos
are not rewritten; recovery retains sealed legacy 1× and 10× timing and frames.

Verification covers actual pilot viewer wiring, nested popup/loading precedence,
return to ordinary interaction, mixed-rate encoded/decoded MP4 duration,
GUI-stall omission and both legacy recovery policies. Synthetic presentation
checks do not start owner scientific runs or change anatomy approvals.
Windows frozen and installed probes pass; see [verified delivery](V145_DELIVERY.md).
Independent real-pilot first use remains separate. Actual capture cadence still
depends on host load.
