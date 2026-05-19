# BMS Data Classification via RAG

Runnable Streamlit demo for classifying Building Management System (BMS) point names into Brick labels with retrieval-augmented generation.

This repository intentionally does not include the private research/building dataset, generated vector indexes, or private LLM API keys. A tiny synthetic `sample_data/` folder is included only so other users can reproduce the app setup and verify the workflow.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and set DASHSCOPE_API_KEY.

streamlit run bms_rag_demo_app.py
```

On first run, the app downloads the Hugging Face embedding and reranker models, builds a local retrieval gallery, and writes generated index files under `storage/`. The `storage/` directory is ignored by Git.

## Using Your Own Data

Create a local data directory, for example `RAG_Data/`, with this schema:

```text
RAG_Data/
  brick_labels.csv
  <building>_Modified_Prep.csv
```

`brick_labels.csv` must contain:

```csv
label
Chilled_Water_Return_Temperature_Sensor
```

Each `*_Modified_Prep.csv` file must contain:

```csv
Name,Label
aru-001__cwr_temp,Chilled_Water_Return_Temperature_Sensor
```

Then point the app at that local folder:

```bash
BMS_RAG_DATA_DIR=RAG_Data streamlit run bms_rag_demo_app.py
```

or set `BMS_RAG_DATA_DIR=RAG_Data` in `.env`.

## Configuration

The app reads a local `.env` file if present, then falls back to environment variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | none | Required for LLM prediction. |
| `DASHSCOPE_BASE_URL` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | OpenAI-compatible DashScope endpoint. |
| `DASHSCOPE_MODEL` | `qwen-plus` | Chat model used for prediction. |
| `BMS_RAG_DATA_DIR` | `sample_data` | Folder containing local CSV data. |
| `BMS_RAG_STORAGE_DIR` | `storage` | Folder for generated vector indexes. |
| `BMS_RAG_EMBED_MODEL` | `BAAI/bge-large-en-v1.5` | Hugging Face embedding model. |
| `BMS_RAG_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | SentenceTransformers reranker. |

## Privacy Notes

- Do not commit `.env`, private API keys, `RAG_Data/`, or `storage/`.
- The committed `sample_data/` files are synthetic examples, not the private dataset.
- If you build indexes from private data, keep the generated `storage/` folder local.

