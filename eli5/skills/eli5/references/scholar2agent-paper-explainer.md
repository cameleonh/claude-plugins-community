# Scholar2Agent paper explainer mode

Use this mode only for an academic paper, paper PDF, DOI, or an explicit Scholar2Agent paper-reading request.

## Boundary

- Scholar2Agent owns the source ledger, claims registry, citation records, manuscript drafts, and all canonical project state.
- Read existing Scholar2Agent artifacts when they are available. Do not rewrite, move, or create canonical project-state files.
- Write only a derived visual explainer, normally under summaries/visual_explainers/ in the active Scholar2Agent project. If no project exists, use the user-approved output location.
- Unified Evidence Harness is an external fail-closed validator. Do not modify its configuration, runtime state, trust hashes, or policy from this skill.

## Evidence-first reading

1. Identify the paper and inspect the source content before describing its methods, findings, limitations, or claims. A title, abstract-only record, or uninspected URL is not enough for a detailed explainer.
2. Build a compact reading note from inspected evidence: research question, relevant concepts, study design, data or materials, analytic method, findings, and stated limitations.
3. Put a visible evidence anchor on each material panel. Use a section, page, figure, table, or project claim identifier when known. Mark missing or uncertain elements as unconfirmed instead of completing them from inference.
4. Separate the authors' stated findings from the explainer's interpretation. Do not turn association into causation or a proposed mechanism into an observed result.

## Choose the visual form

Produce a system diagram only when the inspected paper supplies explicit, meaningful relationships among three or more concepts, stages, actors, or variables. Otherwise use a structured visual reading note with no invented arrows.

For a suitable diagram, make direction, feedback, uncertainty, and levels of analysis visible. Use labels that state the relationship in the source; do not draw causal arrows when the source only reports correlation or describes a framework.

## HTML deliverable

Create one self-contained HTML file with no required external scripts, fonts, images, or network requests. It should include:

- the paper identity and the scope of material actually inspected;
- a plain-language research question;
- a conditional concept or system map, or an explicit note explaining why no map is warranted;
- a data-and-method flow;
- findings, limitations, and open questions;
- evidence anchors and uncertainty labels close to the claims they support;
- semantic headings, readable contrast, keyboard-readable text, and text equivalents for every visual relationship.

The page must reflow without page-level horizontal clipping at both a narrow
390 CSS-pixel viewport and a 1440 CSS-pixel desktop viewport. Before treating
the artifact as visually complete, capture a fresh full-page render at both
widths. Record `window.innerWidth`, `document.documentElement.clientWidth`, and
whether `document.documentElement.scrollWidth` exceeds the client width so a
cropped wide layout is not mistaken for a responsive mobile render. Put wide
tables or diagrams in a labeled, keyboard-accessible overflow region only when
they cannot be expressed as a responsive stack.

Use diagrams as an aid to reasoning, not as a substitute for evidence. The artifact is a derived explanation, not a new source of record.
