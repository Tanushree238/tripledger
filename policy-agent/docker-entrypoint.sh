#!/bin/sh
# Start the policy agent: fail fast without a key, build the index once, then serve.
set -eu

if [ -z "${EMBEDDING_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "EMBEDDING_API_KEY is required (queries are embedded live). Set it in the .env next to docker-compose.yml." >&2
  exit 1
fi

index_ready() {
  python - <<'PY'
import sys

import chromadb
from rag_pipeline.src.rag.ingest_chroma import CHROMA_DIR, COLLECTION_NAME

try:
    ready = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION_NAME).count() > 0
except Exception:
    ready = False
sys.exit(0 if ready else 1)
PY
}

if ! index_ready; then
  echo "Policy index missing or empty - ingesting corpus (cached embeddings are reused)."
  python -m rag_pipeline.src.rag.ingest_chroma
fi

exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
