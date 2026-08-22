# Unified Evidence Harness v4.0

One evidence policy and evaluator with thin adapters for Codex, Antigravity, and ZCode/GLM.

## Design

- `core/`: canonical evaluator, profiles, event normalization, and hash verification.
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

Scholar2Agent remains the canonical project-state owner. The harness consumes its profile and artifacts; it does not create a second WBS, roadmap, result registry, or research log. Set `EVIDENCE_HARNESS_PROFILE=academic` while drafting and `submission` for final gates.

## Install

```powershell
PowerShell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Platform all
```

The installer writes generated runtime bundles to the existing local plugin locations. Restart each host after installation.

