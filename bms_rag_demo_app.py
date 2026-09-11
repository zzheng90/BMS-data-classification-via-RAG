from __future__ import annotations
this is not valid python (((
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from openai import OpenAI
from sentence_transformers import CrossEncoder
from llama_index.core import Settings, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.schema import TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# ============================================================
# Configuration
# ============================================================
BASE_DIR = Path(__file__).resolve().parent


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def env_path(name: str, default: Path) -> Path:
    raw = Path(os.getenv(name, str(default))).expanduser()
    if raw.is_absolute():
        return raw
    return (BASE_DIR / raw).resolve()


load_local_env(BASE_DIR / ".env")

DATA_DIR = env_path("BMS_RAG_DATA_DIR", BASE_DIR / "sample_data")
STORAGE_DIR = env_path("BMS_RAG_STORAGE_DIR", BASE_DIR / "storage")
EXAMPLE_INDEX_DIR = STORAGE_DIR / "examples_index"
LABEL_INDEX_DIR = STORAGE_DIR / "labels_index"

LABEL_FILE_NAME = "brick_labels.csv"

DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

EMBED_MODEL_NAME = os.getenv("BMS_RAG_EMBED_MODEL", "BAAI/bge-large-en-v1.5")
RERANKER_MODEL_NAME = os.getenv("BMS_RAG_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
QWEN_MODEL_NAME = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

TOP_K_RETRIEVE = 100
TOP_K_EXAMPLES = 12
TOP_K_LABELS = 50
TOP_K_RECTIFY = 5


def get_example_files() -> list[Path]:
    return sorted(
        p for p in DATA_DIR.glob("*_Modified_Prep.csv")
        if not p.name.startswith("sampled_")
    )


def get_label_file() -> Path:
    return DATA_DIR / LABEL_FILE_NAME


def validate_data_files() -> list[str]:
    errors = []

    if not DATA_DIR.exists():
        errors.append(f"Data directory does not exist: {DATA_DIR}")
        return errors

    if not get_label_file().exists():
        errors.append(f"Missing {LABEL_FILE_NAME} in {DATA_DIR}")

    if not get_example_files():
        errors.append(
            "Missing one or more example CSV files matching "
            "*_Modified_Prep.csv in the data directory"
        )

    return errors


def get_dashscope_api_key() -> str | None:
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key or api_key == "replace_with_your_dashscope_key":
        return None
    return api_key


# ============================================================
# Text normalization
# ============================================================
def normalize_text(text: str) -> str:
    """
    Replace all underscores and non-alphanumeric characters with a space,
    then collapse multiple spaces into one, then lowercase.
    """
    text = str(text)
    text = re.sub(r"[_\W]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


# ============================================================
# External clients / models
# ============================================================
def get_llm_client() -> OpenAI:
    api_key_qwen = get_dashscope_api_key()
    if not api_key_qwen:
        raise RuntimeError(
            "Missing DASHSCOPE_API_KEY environment variable. "
            "Set it before running the app."
        )

    return OpenAI(
        api_key=api_key_qwen,
        base_url=DASHSCOPE_BASE_URL,
    )


@st.cache_resource(show_spinner=False)
def get_reranker() -> CrossEncoder:
    return CrossEncoder(RERANKER_MODEL_NAME, trust_remote_code=True)


def configure_models() -> None:
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    Settings.embed_model = embed_model
    Settings.llm = None


# ============================================================
# Data loading
# ============================================================
def load_example_rows(csv_paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for path in csv_paths:
        df = pd.read_csv(path)
        required = {"Name", "Label"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")

        df = df[["Name", "Label"]].copy()
        df = df.dropna(subset=["Name", "Label"])
        df["source_file"] = path.name
        df["normalized_name"] = df["Name"].astype(str).map(normalize_text)
        df["normalized_label"] = df["Label"].astype(str).map(normalize_text)
        frames.append(df)

    if not frames:
        raise ValueError("No example CSV files found.")

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["normalized_name", "normalized_label"])
    return merged


def load_label_rows(label_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(label_csv)
    if "label" not in df.columns:
        raise ValueError("brick_labels.csv must contain a 'label' column.")

    out = df[["label"]].copy().dropna(subset=["label"])
    out["normalized_label"] = out["label"].astype(str).map(normalize_text)
    out = out.drop_duplicates(subset=["normalized_label"])
    return out


def load_all_predefined_labels() -> list[str]:
    return load_label_rows(get_label_file())["label"].astype(str).tolist()


# ============================================================
# Gallery building
# ============================================================
def build_example_index(example_df: pd.DataFrame) -> VectorStoreIndex:
    nodes = []

    for row in example_df.itertuples(index=False):
        text = (
            f"BMS point name: {row.normalized_name}\n"
            f"Brick label: {row.Label}\n"
            f"Normalized Brick label: {row.normalized_label}"
        )

        metadata = {
            "raw_name": row.Name,
            "normalized_name": row.normalized_name,
            "brick_label": row.Label,
            "normalized_label": row.normalized_label,
            "source_file": row.source_file,
            "node_type": "example",
        }

        nodes.append(TextNode(text=text, metadata=metadata))

    return VectorStoreIndex(nodes)


def build_label_index(label_df: pd.DataFrame) -> VectorStoreIndex:
    nodes = []

    for row in label_df.itertuples(index=False):
        text = (
            f"Brick label: {row.label}\n"
            f"Normalized Brick label: {row.normalized_label}"
        )

        metadata = {
            "brick_label": row.label,
            "normalized_label": row.normalized_label,
            "node_type": "label",
        }

        nodes.append(TextNode(text=text, metadata=metadata))

    return VectorStoreIndex(nodes)


def persist_index(index: VectorStoreIndex, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    index.storage_context.persist(persist_dir=str(out_dir))


def load_persisted_index(index_dir: Path) -> VectorStoreIndex:
    storage_context = StorageContext.from_defaults(persist_dir=str(index_dir))
    return load_index_from_storage(storage_context)


def gallery_exists() -> bool:
    return EXAMPLE_INDEX_DIR.exists() and LABEL_INDEX_DIR.exists()


def build_gallery_once(force_rebuild: bool = False) -> None:
    configure_models()
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    if gallery_exists() and not force_rebuild:
        return

    data_errors = validate_data_files()
    if data_errors:
        raise ValueError("Cannot build retrieval gallery:\n" + "\n".join(data_errors))

    example_files = get_example_files()
    label_file = get_label_file()

    example_df = load_example_rows(example_files)
    label_df = load_label_rows(label_file)

    example_index = build_example_index(example_df)
    label_index = build_label_index(label_df)

    persist_index(example_index, EXAMPLE_INDEX_DIR)
    persist_index(label_index, LABEL_INDEX_DIR)

    stats = {
        # "example_rows": int(len(example_df)),
        # "label_rows": int(len(label_df)),
        # "example_files": [p.name for p in EXAMPLE_FILES],
        # "label_file": LABEL_FILE.name,
        "Brick ontology version": "v1.3",
        "Retriever model": EMBED_MODEL_NAME,
        "Reranker": RERANKER_MODEL_NAME,
        "LLM": QWEN_MODEL_NAME,
        "Rectifier model": EMBED_MODEL_NAME,
        "Data directory": str(DATA_DIR),
    }

    (STORAGE_DIR / "gallery_stats.json").write_text(
        json.dumps(stats, indent=2),
        encoding="utf-8",
    )


# ============================================================
# Retrieval / reranking
# ============================================================
def get_retrievers() -> tuple[Any, Any]:
    configure_models()
    example_index = load_persisted_index(EXAMPLE_INDEX_DIR)
    label_index = load_persisted_index(LABEL_INDEX_DIR)

    example_retriever = example_index.as_retriever(similarity_top_k=TOP_K_RETRIEVE)
    label_retriever = label_index.as_retriever(similarity_top_k=TOP_K_RETRIEVE)

    return example_retriever, label_retriever


def rerank_hits(query: str, hits, top_k: int) -> list[dict[str, Any]]:
    if not hits:
        return []

    reranker = get_reranker()
    pairs = [(query, hit.node.text) for hit in hits]
    scores = reranker.predict(pairs)

    rescored: list[dict[str, Any]] = []
    for hit, score in zip(hits, scores):
        rescored.append(
            {
                "hit": hit,
                "rerank_score": float(score),
            }
        )

    rescored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return rescored[:top_k]


# ============================================================
# Context formatting
# ============================================================
def format_example_context(example_nodes: list[dict[str, Any]]) -> str:
    lines = []

    for i, item in enumerate(example_nodes, start=1):
        hit = item["hit"]
        rerank_score = item["rerank_score"]
        md = hit.node.metadata
        retrieve_score = getattr(hit, "score", None)

        lines.append(
            f"Example {i}: "
            f"raw_name='{md.get('raw_name', '')}', "
            f"normalized_name='{md.get('normalized_name', '')}', "
            f"brick_label='{md.get('brick_label', '')}', "
            f"source_file='{md.get('source_file', '')}', "
            f"retrieve_score='{round(float(retrieve_score), 4) if retrieve_score is not None else 'NA'}', "
            f"rerank_score='{round(float(rerank_score), 4)}'"
        )

    return "\n".join(lines)


def format_label_context(label_nodes: list[dict[str, Any]]) -> str:
    lines = []

    for i, item in enumerate(label_nodes, start=1):
        hit = item["hit"]
        rerank_score = item["rerank_score"]
        md = hit.node.metadata
        retrieve_score = getattr(hit, "score", None)

        lines.append(
            f"Candidate {i}: "
            f"brick_label='{md.get('brick_label', '')}', "
            f"normalized_label='{md.get('normalized_label', '')}', "
            f"retrieve_score='{round(float(retrieve_score), 4) if retrieve_score is not None else 'NA'}', "
            f"rerank_score='{round(float(rerank_score), 4)}'"
        )

    return "\n".join(lines)


# ============================================================
# Rectification
# ============================================================
def rectify_label_if_needed(
    predicted_label: str | None,
    normalized_query: str,
    predefined_labels: list[str],
) -> dict[str, Any]:
    if not predicted_label:
        return {
            "final_label": None,
            "rectified": False,
            "rectification_reason": "No label predicted by the LLM.",
            "rectification_candidates": [],
        }

    if predicted_label in set(predefined_labels):
        return {
            "final_label": predicted_label,
            "rectified": False,
            "rectification_reason": "LLM output already exists in predefined Brick labels.",
            "rectification_candidates": [predicted_label],
        }

    reranker = get_reranker()

    pairs = []
    for label in predefined_labels:
        label_norm = normalize_text(label)
        combined_candidate = f"{label} | {label_norm}"
        pairs.append((normalized_query, combined_candidate))

    scores = reranker.predict(pairs)
    ranked = sorted(zip(predefined_labels, scores), key=lambda x: float(x[1]), reverse=True)
    top_candidates = [label for label, _ in ranked[:TOP_K_RECTIFY]]

    return {
        "final_label": top_candidates[0] if top_candidates else None,
        "rectified": True,
        "rectification_reason": (
            f"LLM predicted a label outside the predefined Brick labels: '{predicted_label}'. "
            "The reranker mapped it to the closest predefined label."
        ),
        "rectification_candidates": top_candidates,
    }


# ============================================================
# LLM prediction
# ============================================================
def llm_predict_brick_label(
    user_input: str,
    normalized_query: str,
    example_nodes: list[dict[str, Any]],
    label_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    client = get_llm_client()

    candidate_labels = []
    seen = set()
    for item in label_nodes:
        hit = item["hit"]
        label = hit.node.metadata.get("brick_label")
        if label and label not in seen:
            candidate_labels.append(label)
            seen.add(label)

    system_prompt = (
        "You are an expert in Brick schema tagging for Building Management System point names. "
        "Use the retrieved and reranked context to choose the single best Brick label. "
        "Return JSON only with keys: predicted_label, rationale, confidence. "
        "Confidence must be a number between 0 and 1. "
        "Prefer a label from the candidate list."
    )

    user_prompt = f"""
User BMS point name (raw): {user_input}
User BMS point name (normalized): {normalized_query}

Candidate Brick labels:
{json.dumps(candidate_labels, indent=2)}

Retrieved and reranked nearest BMS examples:
{format_example_context(example_nodes)}

Retrieved and reranked nearest Brick label candidates:
{format_label_context(label_nodes)}

Instructions:
1. Infer the semantic meaning of the normalized point name.
2. Compare it with the retrieved examples.
3. Choose the single most appropriate Brick label.
4. Prefer an exact output from the candidate Brick labels.
5. Return JSON only.
""".strip()

    response = client.chat.completions.create(
        model=QWEN_MODEL_NAME,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content.strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {
            "predicted_label": content,
            "rationale": "Model did not return valid JSON; raw output preserved.",
            "confidence": None,
        }

    return {
        "raw_response": content,
        "predicted_label": parsed.get("predicted_label"),
        "rationale": parsed.get("rationale"),
        "confidence": parsed.get("confidence"),
    }


def predict_brick_label(user_input: str) -> dict[str, Any]:
    normalized_query = normalize_text(user_input)
    predefined_labels = load_all_predefined_labels()
    example_retriever, label_retriever = get_retrievers()

    example_hits = example_retriever.retrieve(normalized_query)
    label_hits = label_retriever.retrieve(normalized_query)

    example_nodes = rerank_hits(normalized_query, example_hits, TOP_K_EXAMPLES)
    label_nodes = rerank_hits(normalized_query, label_hits, TOP_K_LABELS)

    llm_result = llm_predict_brick_label(
        user_input=user_input,
        normalized_query=normalized_query,
        example_nodes=example_nodes,
        label_nodes=label_nodes,
    )

    rectification = rectify_label_if_needed(
        predicted_label=llm_result["predicted_label"],
        normalized_query=normalized_query,
        predefined_labels=predefined_labels,
    )

    return {
        "input_raw": user_input,
        "input_normalized": normalized_query,
        "predicted_label_raw": llm_result["predicted_label"],
        "predicted_label": rectification["final_label"],
        "rationale": llm_result["rationale"],
        "confidence": llm_result["confidence"],
        "raw_llm_response": llm_result["raw_response"],
        "rectified": rectification["rectified"],
        "rectification_reason": rectification["rectification_reason"],
        "rectification_candidates": rectification["rectification_candidates"],
        "example_hits": example_nodes,
        "label_hits": label_nodes,
    }


# ============================================================
# Streamlit UI
# ============================================================
def sidebar_info(data_errors: list[str] | None = None) -> None:
    st.sidebar.header("Gallery status")
    st.sidebar.write("**Data directory:**", str(DATA_DIR))
    st.sidebar.write("**Storage directory:**", str(STORAGE_DIR))

    stats_path = STORAGE_DIR / "gallery_stats.json"

    if stats_path.exists():
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        st.sidebar.success("Retrieval gallery is available")
        st.sidebar.json(stats)
    else:
        st.sidebar.warning("Gallery has not been built yet")

    api_key_present = bool(get_dashscope_api_key())
    st.sidebar.write("**DashScope API key loaded:**", "Yes" if api_key_present else "No")

    if data_errors:
        st.sidebar.warning("Data files are incomplete")

    if st.sidebar.button("Rebuild gallery", disabled=bool(data_errors)):
        try:
            with st.spinner("Rebuilding retrieval gallery..."):
                build_gallery_once(force_rebuild=True)
        except Exception as exc:
            st.sidebar.error(f"Gallery rebuild failed: {exc}")
        else:
            st.sidebar.success("Gallery rebuilt")
            st.rerun()


def render_data_setup(data_errors: list[str]) -> None:
    st.warning("Demo data files are not ready.")
    for error in data_errors:
        st.write(f"- {error}")

    st.markdown(
        f"""
        Expected data layout:

        ```text
        {DATA_DIR}/
          brick_labels.csv                 # column: label
          <building>_Modified_Prep.csv     # columns: Name, Label
        ```

        The repository includes a small synthetic sample under `sample_data/`.
        To run against your own data, set `BMS_RAG_DATA_DIR` to a local folder
        with the same CSV schema. Private datasets and API keys are intentionally
        not included in the repository.
        """
    )


def render_hits(title: str, hits: list[dict[str, Any]], show_label: bool = True) -> None:
    st.subheader(title)

    if not hits:
        st.info("No retrieved results.")
        return

    for i, item in enumerate(hits, start=1):
        hit = item["hit"]
        rerank_score = item["rerank_score"]
        md = hit.node.metadata
        retrieve_score = getattr(hit, "score", None)

        with st.expander(f"Top {i}"):
            st.write("**Raw name:**", md.get("raw_name", "-"))
            st.write("**Normalized name:**", md.get("normalized_name", "-"))
            if show_label:
                st.write("**Brick label:**", md.get("brick_label", "-"))
            st.write("**Source file:**", md.get("source_file", "-"))
            if retrieve_score is not None:
                st.write("**Similarity score:**", round(float(retrieve_score), 4))
            st.write("**Rerank score:**", round(float(rerank_score), 4))


def main() -> None:
    st.set_page_config(page_title="BMS-RAG Tool Demo", layout="wide")
    st.title("BMS-RAG Tool Demo — deployed by Zhiyu via CI/CD 🚀")
    st.caption(
        "To tag Building Management Systems point instances "
        "with Brick label"
    )

    data_errors = validate_data_files()
    if data_errors:
        sidebar_info(data_errors=data_errors)
        render_data_setup(data_errors)
        st.stop()

    try:
        build_gallery_once(force_rebuild=False)
    except Exception as exc:
        sidebar_info()
        st.error(f"Could not build or load the retrieval gallery: {exc}")
        st.stop()

    sidebar_info()

    # st.markdown(
    #     """
    #     **Preprocessing rule used everywhere**
    #     - Replace all underscores and non-alphanumeric characters with a space
    #     - Collapse multiple spaces into one
    #     - Convert to lowercase for retrieval consistency
    #     """
    # )

    # st.caption(f"Reranker in use: {RERANKER_MODEL_NAME}")

    user_input = st.text_input(
        "Please enter a BMS point instance",
        value="aru-001__cwr_temp",
        help="Example: aru-001__cwr_temp",
    )

    if st.button("Predict Brick label", type="primary"):
        if not get_dashscope_api_key():
            st.error("Set DASHSCOPE_API_KEY before calling the DashScope-compatible LLM.")
            st.stop()

        if not user_input.strip():
            st.error("Enter a BMS point instance before prediction.")
            st.stop()

        try:
            with st.spinner("Retrieving context, reranking, and asking the LLM to predict the Brick label..."):
                result = predict_brick_label(user_input)
        except Exception as exc:
            st.error(f"Prediction failed: {exc}")
            st.stop()

        st.subheader("Prediction")
        st.write("**Raw input:**", result["input_raw"])
        # st.write("**Normalized input:**", result["input_normalized"])
        st.write("**LLM predicted label:**", result["predicted_label_raw"] or "-")
        st.success(f"Final Brick label: {result['predicted_label'] or 'No prediction available'}")

        col1, col2 = st.columns(2)
        with col1:
            st.write("**Confidence:**", result["confidence"])
        with col2:
            st.write("**Rationale:**", result["rationale"] or "-")

        st.write("**Rectified to predefined label:**", "Yes" if result["rectified"] else "No")
        st.write("**Rectification note:**", result["rectification_reason"])
        if result["rectification_candidates"]:
            st.write(
                "**Top rectification candidates:**",
                ", ".join(result["rectification_candidates"]),
            )

        left, right = st.columns(2)
        with left:
            render_hits("Nearest BMS examples", result["example_hits"], show_label=True)
        with right:
            render_hits("Nearest Brick label candidates", result["label_hits"], show_label=True)

        with st.expander("Raw LLM response"):
            st.code(result["raw_llm_response"], language="json")


if __name__ == "__main__":
    main()
