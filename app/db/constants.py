"""Schema constants that must change only through an explicit migration."""

from __future__ import annotations

# EmbeddingGemma's full output dimension. Changing this value requires a
# database migration and regeneration of every derived embedding.
EMBEDDING_DIMENSIONS = 768
