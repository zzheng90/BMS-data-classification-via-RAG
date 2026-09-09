# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# BMS-RAG demo — container image
#
# Design notes for the CI/CD lesson:
#   * python:3.11-slim keeps the base small.
#   * CPU-only torch is installed from the PyTorch CPU index so we do NOT pull
#     ~1GB of CUDA libraries we can't use on a t3.small.
#   * The embedding + reranker models are downloaded at BUILD time and baked
#     into the image. They are cached under the runtime user's HOME so a fresh
#     container needs no network and pods start in seconds.
#   * Small models are used by default (see BMS_RAG_*_MODEL) so the app fits in
#     ~1.5GB RAM. Override via env/ConfigMap for higher quality on a bigger node.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Create the unprivileged runtime user up front so model caches can be baked
# into its HOME.
RUN useradd --create-home --uid 10001 appuser

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python dependencies ---------------------------------------------------
# CPU-only torch first; sentence-transformers will then reuse it.
RUN pip install --no-cache-dir "torch" --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Bake in the ML models ----------------------------------------------------
# Lightweight defaults so the image runs on a small node without a GPU.
# HF_HOME  -> sentence-transformers / transformers cache (the reranker)
# LLAMA_INDEX_CACHE_DIR -> llama-index HuggingFaceEmbedding cache (the embedder)
ENV BMS_RAG_EMBED_MODEL=BAAI/bge-small-en-v1.5 \
    BMS_RAG_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2 \
    HF_HOME=/home/appuser/.cache/huggingface \
    LLAMA_INDEX_CACHE_DIR=/home/appuser/.cache/llama_index

COPY . .
RUN chown -R appuser /app

# Numeric UID so Kubernetes `runAsNonRoot` can verify it.
USER 10001

RUN python -c "import os; \
from llama_index.embeddings.huggingface import HuggingFaceEmbedding; \
from sentence_transformers import CrossEncoder; \
HuggingFaceEmbedding(model_name=os.environ['BMS_RAG_EMBED_MODEL']).get_text_embedding('warm up'); \
CrossEncoder(os.environ['BMS_RAG_RERANKER_MODEL'], trust_remote_code=True).predict([('a', 'b')]); \
print('models cached under', os.path.expanduser('~/.cache'))"

# --- Application -----------------------------------------------------------
ENV STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "bms_rag_demo_app.py"]
