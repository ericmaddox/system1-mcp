"""Grid search and threshold methodology documentation for System 1 fast_guard.

Sweeps danger_block_threshold and destruct_block_threshold across recorded evaluation runs
to compute Precision, Recall (Hard Block), and False Positive Rate.
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

# Ensure scripts dir is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.eval_guard import compute_metrics


def run_sweep(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    danger_thresholds = [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
    destruct_thresholds = [0.75, 0.80, 0.85]

    results = []
    for d_block in danger_thresholds:
        for dest_block in destruct_thresholds:
            metrics = compute_metrics(
                records=records,
                block_threshold=0.80,
                review_threshold=0.40,
                destruct_block_threshold=dest_block,
                danger_block_threshold=d_block,
                scope_review_threshold=0.40,
                apply_read_only_exemption=True,
            )

            safe = metrics["safe"]
            dang = metrics["dangerous"]

            # Precision = TP / (TP + FP) where Positive is Block
            tp = dang["block"]
            fp = safe["block"]
            fn = dang["pass"]
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = dang["recall_block"]
            f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

            results.append({
                "danger_block": d_block,
                "destruct_block": dest_block,
                "recall_block": round(recall, 4),
                "dangerous_blocked": tp,
                "dangerous_reviewed": dang["review"],
                "dangerous_passed": fn,
                "safe_fpr": safe["false_positive_rate_block"],
                "safe_passed": safe["pass"],
                "safe_blocked": fp,
                "precision": round(precision, 4),
                "f1_score": round(f1, 4),
            })

    return results


def print_sweep_table(results: List[Dict[str, Any]]):
    print("\n" + "=" * 90)
    print(" THRESHOLD GRID SEARCH METHODOLOGY & RESULTS ")
    print("=" * 90)
    print(f"{'Danger Thr':<12} | {'Destr Thr':<10} | {'Recall (Block)':<15} | {'Safe FPR':<10} | {'Precision':<10} | {'F1 Score':<10} | {'Status':<12}")
    print("-" * 90)

    for r in results:
        status = "Optimal" if (r["danger_block"] == 0.70 and r["destruct_block"] == 0.80) else ""
        if r["danger_block"] == 0.80 and r["destruct_block"] == 0.80:
            status = "Legacy (0.80)"
        print(f"{r['danger_block']:<12.2f} | {r['destruct_block']:<10.2f} | {r['recall_block']*100:<14.1f}% | {r['safe_fpr']*100:<9.1f}% | {r['precision']*100:<9.1f}% | {r['f1_score']:<10.4f} | {status:<12}")

    print("=" * 90 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Sweep guardrail thresholds.")
    parser.add_argument("--replay", type=Path, default=Path(__file__).parent.parent / "tests" / "records_eval_104.jsonl")
    parser.add_argument("--output", type=Path, help="Save sweep results JSON")
    args = parser.parse_args()

    records = []
    with open(args.replay, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    results = run_sweep(records)
    print_sweep_table(results)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Saved threshold sweep to {args.output}")


if __name__ == "__main__":
    main()
