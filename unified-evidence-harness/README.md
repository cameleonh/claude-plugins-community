# Unified Evidence Harness v4.0

One evidence policy and evaluator with thin adapters for Codex, Antigravity, and ZCode/GLM.

## Design

- `core/`: canonical evaluator, profiles, event normalization, Scholar2Agent bridge, Antigravity transcript adapter, and hash verification.
- `adapters/`: platform manifests only. Every adapter runs the same hook program.
- `profiles/`: proportional enforcement. Functional comparison is not treated like academic verification.
- `scripts/install.ps1`: builds local platform bundles without making Google Drive a runtime dependency.
- `scripts/build_hashes.py`: records SHA-256 trust hashes for every distributed file.
- `tests/`: deterministic regression cases for phantom evidence, wrapper tools, modes, and compaction.

## Profiles

- `routine`: action and artifact integrity; no blanket research requirement.
- `research`: URL, DOI, quotation, attribution, and current-session evidence checks.
- `academic`: research checks plus academic identifier and claim-ledger checks.
- `submission`: fail-closed academic mode requiring supported material claims.

The prompt classifier may raise the profile but never lowers an explicitly configured profile.

## Scholar2Agent

Scholar2Agent remains the canonical project-state owner. The harness reads its profile, claims registry, result artifacts, manuscript anchors, and reviewer receipts into an in-memory ledger; it does not create a second WBS, roadmap, result registry, or research log.

A supported or refuted project claim requires a current successful read event for the exact result artifact. Write events and path substrings do not count. Malformed receipts, receipt overflow, unsafe redirects, broken JSON pointers, and uninspected claim artifacts remain blocking at submission time.

Codex and ZCode receive prompt and final-response content from their native hook fields. Antigravity uses its host-provided transcript only when it is inside the host artifact directory, the expected user/model records are unambiguous, and `fullyIdle` is true. Missing or malformed transcript state fails closed.

## Install

```powershell
PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Platform all
```

The installer writes generated runtime bundles to the existing local plugin locations. Restart each host after installation.
