#!/usr/bin/env python3
"""Compute confidence calibration metrics from decision quality judgments.

Reads decision_quality_judgments.json (from review_decisions.py) and
computes Expected Calibration Error (ECE) and reliability diagram data.

Usage:
    cd apps/api
    .venv/bin/python -m evaluation.compute_calibration
"""

import json
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "v5"
JUDGMENTS_FILE = OUTPUT_DIR / "decision_quality_judgments.json"


def compute_calibration(judgments: list[dict], n_bins: int = 5) -> dict:
    """Compute Expected Calibration Error and per-bin accuracy."""

    # Map judgments to binary: CORRECT/PARTIAL = 1, WRONG/NOT_A_DECISION = 0
    data = []
    for j in judgments:
        conf = j.get("confidence", 0.9)  # default if missing
        correct = 1 if j["judgment"] in ("CORRECT", "PARTIAL") else 0
        data.append((conf, correct))

    if not data:
        return {"error": "No judgments found"}

    # Create bins
    bin_edges = [i / n_bins for i in range(n_bins + 1)]
    bins = []

    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        in_bin = [(c, a) for c, a in data if lo <= c < hi or (i == n_bins - 1 and c == hi)]

        if in_bin:
            avg_confidence = sum(c for c, _ in in_bin) / len(in_bin)
            avg_accuracy = sum(a for _, a in in_bin) / len(in_bin)
            bins.append({
                "range": f"[{lo:.1f}, {hi:.1f})",
                "count": len(in_bin),
                "avg_confidence": round(avg_confidence, 3),
                "avg_accuracy": round(avg_accuracy, 3),
                "gap": round(abs(avg_accuracy - avg_confidence), 3),
            })
        else:
            bins.append({
                "range": f"[{lo:.1f}, {hi:.1f})",
                "count": 0,
                "avg_confidence": 0,
                "avg_accuracy": 0,
                "gap": 0,
            })

    # ECE = weighted average of |accuracy - confidence| per bin
    total = len(data)
    ece = sum(b["count"] / total * b["gap"] for b in bins if b["count"] > 0)

    # Overall stats
    overall_accuracy = sum(a for _, a in data) / len(data)
    overall_confidence = sum(c for c, _ in data) / len(data)

    return {
        "ece": round(ece, 4),
        "overall_accuracy": round(overall_accuracy, 3),
        "overall_confidence": round(overall_confidence, 3),
        "n_judgments": len(data),
        "n_bins": n_bins,
        "bins": bins,
        "interpretation": (
            "Well calibrated (ECE < 0.05)" if ece < 0.05 else
            "Reasonably calibrated (ECE < 0.10)" if ece < 0.10 else
            "Poorly calibrated (ECE >= 0.10)"
        ),
    }


def main():
    if not JUDGMENTS_FILE.exists():
        print(f"Error: {JUDGMENTS_FILE} not found.")
        print("Run: .venv/bin/python -m evaluation.review_decisions first")
        sys.exit(1)

    with open(JUDGMENTS_FILE) as f:
        judgments = json.load(f)

    print(f"Loaded {len(judgments)} decision quality judgments")

    # Need to enrich with confidence scores from Neo4j
    # For now, check if confidence is already in judgments
    has_confidence = any("confidence" in j for j in judgments)

    if not has_confidence:
        print("Note: Judgments don't have confidence scores yet.")
        print("Will attempt to fetch from Neo4j...")

        import asyncio
        import os
        from neo4j import AsyncGraphDatabase

        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        os.environ.setdefault(key.strip(), value.strip())

        async def enrich():
            driver = AsyncGraphDatabase.driver(
                os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
                auth=(os.environ.get("NEO4J_USER", "neo4j"),
                      os.environ.get("NEO4J_PASSWORD", "password"))
            )
            async with driver.session(database="neo4j") as session:
                for j in judgments:
                    did = j.get("decision_id", "")
                    if did:
                        r = await session.run(
                            "MATCH (d:DecisionTrace {id: $id}) RETURN d.confidence AS c",
                            parameters={"id": did}
                        )
                        rec = await r.single()
                        if rec and rec["c"] is not None:
                            j["confidence"] = float(rec["c"])
            await driver.close()

        try:
            asyncio.run(enrich())
            # Save enriched judgments
            with open(JUDGMENTS_FILE, "w") as f:
                json.dump(judgments, f, indent=2)
            print("Enriched judgments with confidence scores from Neo4j")
        except Exception as e:
            print(f"Could not connect to Neo4j: {e}")
            print("Using default confidence of 0.9 for all decisions")
            for j in judgments:
                j.setdefault("confidence", 0.9)

    # Compute calibration
    result = compute_calibration(judgments)

    print(f"\n=== CONFIDENCE CALIBRATION ===")
    print(f"Judgments: {result['n_judgments']}")
    print(f"Overall accuracy:   {result['overall_accuracy']:.1%}")
    print(f"Overall confidence:  {result['overall_confidence']:.1%}")
    print(f"ECE:                {result['ece']:.4f}")
    print(f"Interpretation:     {result['interpretation']}")

    print(f"\nPer-bin breakdown:")
    print(f"{'Bin':15s} {'Count':>6} {'Avg Conf':>9} {'Accuracy':>9} {'Gap':>6}")
    print("-" * 50)
    for b in result["bins"]:
        print(f"{b['range']:15s} {b['count']:>6} {b['avg_confidence']:>8.3f} {b['avg_accuracy']:>8.3f} {b['gap']:>6.3f}")

    # Save
    output_path = OUTPUT_DIR / "calibration_results.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
