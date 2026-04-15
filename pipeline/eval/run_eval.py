"""
RAGAS evaluation for Saudi Health Hub RAG pipeline.

Requires:
  pip install ragas datasets

Usage (from pipeline/ directory):
  .venv/Scripts/python.exe eval/run_eval.py
  .venv/Scripts/python.exe eval/run_eval.py --limit 5
  .venv/Scripts/python.exe eval/run_eval.py --entity MOH --language en
  .venv/Scripts/python.exe eval/run_eval.py --output results/v2.json

  # Save RAG outputs to cache (skip backend calls on future runs):
  .venv/Scripts/python.exe eval/run_eval.py --cache eval/cache/50q.json

  # Re-score from cache (zero backend cost):
  .venv/Scripts/python.exe eval/run_eval.py --cache eval/cache/50q.json --output results/v3.json

  # Refresh cache even if it exists:
  .venv/Scripts/python.exe eval/run_eval.py --cache eval/cache/50q.json --refresh-cache
"""
import argparse
import io
import json
import sys
from datetime import datetime, timezone

# Fix Arabic output on Windows consoles (cp1252 can't encode Arabic)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

import httpx

EVAL_DIR = Path(__file__).parent
BACKEND_URL = "http://localhost:8000"
EVAL_ENDPOINT = f"{BACKEND_URL}/api/chat/eval"
DATASET_PATH = EVAL_DIR / "golden_dataset.json"
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def load_dataset(
    language: str | None,
    entity: str | None,
    limit: int | None,
    question_indices: list[int] | None = None,
) -> list[dict]:
    with open(DATASET_PATH, encoding="utf-8") as f:
        samples = json.load(f)
    if question_indices:
        # 1-based indices as displayed in eval reports
        samples = [s for i, s in enumerate(samples, 1) if i in question_indices]
        return samples
    if language:
        samples = [s for s in samples if s.get("language") == language]
    if entity:
        samples = [s for s in samples if s.get("entity", "").upper() == entity.upper()]
    if limit:
        samples = samples[:limit]
    return samples


def collect_rag_outputs(samples: list[dict]) -> list[dict]:
    rows = []
    with httpx.Client(timeout=120) as client:
        for i, sample in enumerate(samples, 1):
            print(f"  [{i}/{len(samples)}] {sample['question'][:70]}...")
            try:
                payload = {"query": sample["question"]}
                if sample.get("entity"):
                    payload["entity_filter"] = sample["entity"]
                resp = client.post(EVAL_ENDPOINT, json=payload)
                resp.raise_for_status()
                data = resp.json()
                rows.append({
                    "question": sample["question"],
                    "answer": data["answer"],
                    "contexts": data["contexts"],
                    "ground_truth": sample["ground_truth"],
                })
            except Exception as e:
                print(f"    ERROR: {e}")
                # Include with empty answer/contexts so RAGAS can still score
                rows.append({
                    "question": sample["question"],
                    "answer": "",
                    "contexts": [],
                    "ground_truth": sample["ground_truth"],
                })
    return rows


def run_ragas(rows: list[dict], judge_model: str = "claude-haiku-4-5-20251001") -> dict:
    try:
        from datasets import Dataset
        from ragas import evaluate, RunConfig
        from ragas.metrics import Faithfulness, ContextPrecision, ContextRecall  # noqa: F401 — collections API requires OpenAI; legacy path works with Anthropic via LangChain
        from ragas.llms import LangchainLLMWrapper
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        print(f"\nMissing dependency: {e}")
        print("Run: pip install ragas datasets langchain-anthropic")
        sys.exit(1)

    import os
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")

    print(f"  Judge model: {judge_model}")
    judge_llm = LangchainLLMWrapper(ChatAnthropic(
        model=judge_model,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    ))

    metrics = [
        Faithfulness(llm=judge_llm),
        ContextPrecision(llm=judge_llm),
        ContextRecall(llm=judge_llm),
    ]

    run_config = RunConfig(
        timeout=180,
        max_retries=3,
        max_wait=60,
        max_workers=1,    # serialize to avoid Anthropic 429 rate limits
    )

    dataset = Dataset.from_list(rows)
    results = evaluate(dataset, metrics=metrics, run_config=run_config)
    return results


def print_results(results) -> None:
    print("\n" + "=" * 50)
    print("RAGAS Evaluation Results")
    print("=" * 50)
    targets = {
        "faithfulness": 0.85,
        "context_precision": 0.75,
        "context_recall": 0.70,
    }
    df = results.to_pandas()
    for metric, target in targets.items():
        if metric in df.columns:
            score = df[metric].mean()
            status = "✓" if score >= target else "✗"
            print(f"  {status} {metric:<22} {score:.3f}  (target: >{target})")
    print("=" * 50)


def save_results(results, rows: list[dict], output_path: Path) -> None:
    df = results.to_pandas()
    summary = {metric: float(df[metric].mean()) for metric in df.columns if df[metric].dtype == "float64"}
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_questions": len(rows),
        "summary": summary,
        "per_question": df.to_dict(orient="records"),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation")
    parser.add_argument("--language", choices=["ar", "en"], help="Filter by language")
    parser.add_argument("--entity", choices=["MOH", "GASTAT"], help="Filter by entity")
    parser.add_argument("--limit", type=int, help="Limit number of questions")
    parser.add_argument("--questions", type=str, help="Comma-separated 1-based question indices, e.g. 13,14,30,33")
    parser.add_argument("--output", type=str, help="Output file path (relative to eval/results/)")
    parser.add_argument("--cache", type=str, help="Path to cache file for RAG outputs (relative to pipeline/)")
    parser.add_argument("--refresh-cache", action="store_true", help="Re-collect from backend even if cache exists")
    parser.add_argument("--judge", type=str, default="claude-haiku-4-5-20251001",
                        help="Anthropic model to use as RAGAS judge (default: claude-haiku-4-5-20251001)")
    args = parser.parse_args()

    _output = args.output or f"eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    output_path = Path(_output) if Path(_output).is_absolute() else RESULTS_DIR / Path(_output).name

    cache_path = (EVAL_DIR.parent / args.cache) if args.cache else None

    # --- Load from cache or collect fresh ---
    if cache_path and cache_path.exists() and not args.refresh_cache:
        print(f"Loading RAG outputs from cache: {cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            rows = json.load(f)
        print(f"  {len(rows)} rows loaded (skipping backend calls)")
    else:
        print("Loading golden dataset...")
        q_indices = [int(x) for x in args.questions.split(",")] if args.questions else None
        samples = load_dataset(args.language, args.entity, args.limit, question_indices=q_indices)
        print(f"  {len(samples)} questions loaded")

        print("\nCollecting RAG outputs from backend...")
        rows = collect_rag_outputs(samples)

        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, ensure_ascii=False)
            print(f"  RAG outputs cached to {cache_path}")

    print(f"\nRunning RAGAS on {len(rows)} question-answer pairs...")
    results = run_ragas(rows, judge_model=args.judge)

    print_results(results)
    save_results(results, rows, output_path)


if __name__ == "__main__":
    main()
