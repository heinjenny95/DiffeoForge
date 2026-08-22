# Recompute query-tile checkpoint grouping

Status: **exact graph-administration optimization in Modern engine implementation 0.3**

Blockwise recompute trades additional backward calculation for a smaller saved
autograd payload. Earlier code wrapped every deterministic `query × source`
tile in an independent PyTorch checkpoint. For `Q` query tiles and `S` source
tiles, one Gaussian convolution therefore created `Q*S` checkpoint contexts,
even though all `S` source tiles contribute to the same query output.

Implementation 0.3 moves the boundary around the source-tile loop:

```text
pairwise Gaussian work: unchanged Q*S tiles
largest pair tile:      unchanged declared query_rows × source_rows
checkpoint contexts:    Q*S -> Q
```

The same grouping applies to the explicit Gaussian x-gradient. Equal-tile
symmetric Current and Varifold self terms group their upper-triangle
contributions per query tile and return them in their original accumulation
order; Current cross terms use grouped Gaussian convolution and Varifold cross
terms group their unchanged source-tile loop behind one checkpoint boundary per
query tile.

Tests require bit-identical standard/recompute convolution forward values and
gradients on the existing probe, dense-tolerance Current objective/gradient
parity through the complete public CC0 mesh path, declared pair-tile bounds,
and exact checkpoint-call counts equal to the number of query groups. The
optimization changes graph administration, not the mathematical interaction
count or tile-size provenance.

This is not a measured full-resolution RAM or runtime claim. Representative
fresh-process measurements remain necessary after the active qualification run
finishes; concurrent measurements would not be benchmark evidence.
