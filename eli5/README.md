# eli5

Explain a topic with a simple, picture-led HTML artifact.

Example invocation: /eli5 how does DNS work

The artifact uses large visual relationships and concise language for someone new to the topic.

## Scholar2Agent paper mode

When the request is to read, summarize, or visually explain an academic paper, eli5 creates a derived, self-contained and accessible HTML explainer. It first grounds every material panel in inspected paper evidence, then adds a system diagram only when the paper contains enough explicit relationships to make one useful.

Scholar2Agent remains the owner of paper evidence and canonical project state. eli5 reads approved project artifacts when available and writes only the derived explainer. Unified Evidence Harness remains an external fail-closed validator; this plugin does not modify Harness state, configuration, or trust hashes.

## Personal-fork modification

This personal fork keeps the upstream plugin name eli5 and the original MIT attribution. Version 1.1.0-personal.1 adds the Scholar2Agent evidence-anchored paper-explainer mode.
