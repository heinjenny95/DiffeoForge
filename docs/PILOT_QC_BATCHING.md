# Batched surface checks without changing scientific measurements

Marked-area checks previously launched an isolated MeshLab process separately for
each direction, repeat and region. The process and native-plugin startup cost was
repeated even when all queries used the same complete reference surface.

Independent query groups on one surface now share one native distance call. The
results are split back into their original groups before computing means and
percentiles. Original faces, deterministic area samples, random seeds, repeat
counts and the unsigned point-to-triangle definition remain unchanged. Reverse
samples outside a marked area still contribute no evidence; an empty reverse
query remains unknown rather than zero error. No proxy or nearest-vertex distance
replaces the surface calculation. Native-plugin isolation, supervised worker
lifetime, timeout, crash reporting and cleanup remain in effect.

This reduces the marked-area pass to at most two native-worker launches regardless
of the number of regions. The regional preservation checker also combines its
two identical-surface repeats per direction. Source surfaces, saved runs, reviews,
optimizer settings, acceptance bounds and native fitting equations are unchanged.
This optimizes post-fit checking, not the optimizer itself.

Verification includes 29 targeted source/native-worker cases, four new grouped
query cases, analytic interior/edge/off-surface triangle distances, translated
coordinates, empty reverse queries, Qt-worker lifetime, child crash/timeout and
cleanup, and actual regional geometry regressions. Independent native calls and
grouped calls return bit-identical query values in the controlled cases. A
separate read-only old/new comparison on saved development surfaces also retained
every per-area/repeat metric exactly, with fewer worker launches and lower local
checking time. That observation is not a full-fit speedup or anatomical-quality
claim. Local timing and private geometry evidence stay outside this repository.
