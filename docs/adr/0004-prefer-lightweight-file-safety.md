# Prefer lightweight file safety

Keepygaga uses one process lock, opaque page versions, full-batch preflight, and per-file atomic replacement instead of a cross-file crash-recovery journal. Core memory is a small trusted local Markdown tree, so protecting normal Agent and human edit conflicts is worth the cost, while database-grade recovery for adversarial local races would make the implementation larger than the product surface it protects.
