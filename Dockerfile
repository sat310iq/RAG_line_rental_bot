# RAG + LINE webhook API for Cloud Run (listen on 0.0.0.0:$PORT).
# Build context: rental_rag_poc/ root. Ensure data/vector_store exists (run: python scripts/reindex_vector_db.py).
# Registry: use Artifact Registry (gcr.io write deprecated); push/deploy are Step 2.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY data/ ./data/

# Bake SentenceTransformer weights into the image so LINE webhooks do not block on
# Hugging Face download (multi-minute) before Reply API / reply token expiry.
ENV HF_HOME=/app/.cache/huggingface
RUN mkdir -p /app/.cache/huggingface && python -c \
  "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# App resolves paths from cwd; Chroma/BM25 live under data/vector_store when bundled.
EXPOSE 8080

CMD uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}
