# v117 — open recovered final exports

The completed-result importer previously required fresh objective observations.
A successful saved-state final export intentionally has none, so a valid recovered
atlas could be discovered but could not open for anatomical QC or momenta analysis.

The importer now accepts this case only through its protected export declaration,
matching original manifest/result/checkpoint/native-log hashes, inventoried
unchanged-state receipt and retained original convergence CSV. CSV observations
must exactly match the bound native log. The analysis bundle copies these records,
retains their hashes and regenerates the original curve. No run log, checkpoint,
parameter or completed result is rewritten; no optimizer or shooting job is started.

The UI labels the curve as **Original fit history**, displays the saved iteration
and zero additional optimizer iterations, and separates final-export duration.
An unknown original duration remains **not recorded**. Native tolerance stops and
iteration caps retain their original meaning; neither supplies anatomical approval.
Ordinary runs without objective evidence and incomplete/unbound recovery evidence
remain blocked. Existing analysis-bundle versions remain readable.

Within a single result-open operation, the full output inventory is checked once.
PCA creation/reverification uses that operation-local snapshot while rechecking
critical metadata and parameter hashes. Each explicit reopening performs a fresh
complete check; this is not a persistent UI validation cache.

Scoped regression coverage includes recovery import, exact source-history binding,
unchanged original files, invalid receipts, mismatched checkpoints/logs/CSV, missing
sources, ordinary empty-history rejection, unknown duration, capped-run disclosure,
recomputed PCA/SVG evidence, and single-operation verification/reopening behavior.
The actual retained cohort is also checked through the normal result-review route;
private inputs and receipts remain outside the public repository.

The full-cohort import passed with all specimen QC pairs available, the original
native tolerance stop retained and no additional optimizer iterations. Complete
opening took approximately 14.5 minutes; geometric QC and inventory checks remain
expensive. See [build and local installation status](V117_DELIVERY.md).

Creating or revalidating a source-bound recovery analysis requires the retained
original run to remain available at its declared path. The copied analysis bundle
can be verified on its own; it does not claim portability of the entire linked run.
Large inventories still require a complete hash pass, and anatomical QC remains
the researcher's decision. Build, installation and scientific acceptance are
separate states.
