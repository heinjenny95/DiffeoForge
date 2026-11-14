# Experimental original-grid augmentation cache

Incremental material-point augmentation shares parsed copies of the current
and previous original grids across its prefix recursion. The public `augment`
signature, field/source checks, endpoint writer, ordered geometry and receipt
metadata are preserved. One explicit private context belongs to one outer call;
there is no process-global loader replacement or persistent cache.

The context retains at most two grids and 256MiB of parsed vertex/face arrays,
with least-recently-used eviction and bypass for an oversized grid. Arrays use
immutable byte owners and cannot be made writable. Every lookup checks complete
SHA256, actual file identity, size and modification time, including cache hits.
Opened-handle and source-path identities must agree before/after hashing and
parsing; reparse paths and offline/recall placeholders are rejected. Successful
operation exit reseals all used grids. Cache entries and bindings are cleared
on both normal and exceptional exits. Eviction does not forget a source binding.

Windows path-stat and fstat have different legacy `ctime` meanings, so they are
compared using actual volume/file index, size and mtime plus the full content
hash. A size/mtime match alone never permits reuse.

Focused tests cover changed same-size contents with preserved mtime, replacement
by an identical-content different file ID, immutable arrays, entry/byte budgets,
eviction, operation lifetime, unsafe paths, changes during parsing and exact
multi-prefix output bytes. Eighteen focused tests, Ruff and diff checks pass.
A separate integrated-source check directly calls the actual public `augment`,
without a shadow cache adapter or loader replacement: all five canonical VTK
files, Float64 vertex bits, ordered Int64 face bits, metadata and recursive
receipt semantics match, allowing only new output destination paths. All
seventeen scientific input and two production-module identity/hash seals stay
unchanged. The observed recursion makes two grid parses across ten lookups,
retains at most two entries and clears the cache before returning. This extends
the earlier private shadow check rather than substituting it for source parity.

This avoids repeated parsing within augmentation; it does not change fitted
fields, numerical parameters, contact judgments or anatomical acceptance. It
does not establish a full-pilot speedup or interactive-runtime qualification.
The integration timing includes call profiling and may overlap other native
work; it has no valid original-versus-cached timing ratio. Wider independent
data/runtime qualification remains open. Installed and distributed runtimes
remain unchanged.
