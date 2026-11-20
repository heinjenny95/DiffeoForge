# v127 — reopen completed pilots from the main workflow

The parameter page previously offered applying a completed pilot or starting a
new project, while its normal open action consumed the completed result instead
of displaying it. This made the optional chosen-fit control-density comparison
unreachable after closing the pilot window.

**Open saved pilot & density test** now appears above the parameter-page footer
whenever the current project has a saved pilot. The completed-pilot action in the
calibration card also reopens it. Saved evidence is verified in the background;
completed studies display the existing pilot window, including **Compare
control-point density of chosen fit**. Browsing requires no backend readiness
check and starts no scientific worker. A missing saved study fails without
creating a replacement. Existing context-change and close-during-load guards
remain in force.

Closing an unchanged completed pilot after browsing does not apply its parameters.
The separate **Apply completed pilot calibration** action retains its existing
behavior. A newly selected completed successor still follows the ordinary
parameter handoff when its pilot window finishes. The density protocol, original
approvals, new-fit QC and numerical completion gates are unchanged.

Regression checks cover main-page button placement, completed-result browsing,
unchanged-close versus successor handoff, missing-study refusal, asynchronous
context invalidation and existing completion/application behavior. Source,
frozen and installed read-only UI probes are recorded separately from scientific
first-use acceptance. No optimizer, Shooting, full atlas or PCA is started by
development or installation. Installer distribution remains request-only.

Thirty-four scoped regressions passed: saved-pilot responsiveness and access,
existing desktop application and engine-switch routes, the eight density cases,
and version/installer consistency. Lint and diff checks passed. These checks do
not replace native scientific acceptance of a new density fit.
