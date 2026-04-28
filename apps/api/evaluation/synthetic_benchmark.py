"""Generate synthetic benchmark data for entity resolution evaluation.

Reads canonical mappings from the ontology module and generates surface form
variants for each canonical entity name, including lowercase, uppercase,
abbreviations, version-qualified forms, misspellings, and suffix variations.

Usage:
    python -m evaluation.synthetic_benchmark [--output PATH] [--seed SEED]
"""

import argparse
import csv
import os
import random
import re
import sys
from pathlib import Path

# Allow imports from the parent apps/api directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.ontology import CANONICAL_NAMES


# ---------------------------------------------------------------------------
# Well-known abbreviations for common technology names
# ---------------------------------------------------------------------------
KNOWN_ABBREVIATIONS: dict[str, list[str]] = {
    "PostgreSQL": ["PG", "PSQL", "Postgres"],
    "MongoDB": ["Mongo"],
    "JavaScript": ["JS"],
    "TypeScript": ["TS"],
    "Python": ["Py"],
    "Kubernetes": ["K8s", "Kube"],
    "Docker Compose": ["dc", "compose"],
    "Elasticsearch": ["ES", "Elastic"],
    "React": ["ReactJS"],
    "Vue.js": ["Vue"],
    "Angular": ["ng", "AngularJS"],
    "Next.js": ["Next"],
    "GraphQL": ["GQL"],
    "WebSocket": ["WS"],
    "Amazon Web Services": ["AWS"],
    "Google Cloud Platform": ["GCP"],
    "Tailwind CSS": ["TW", "Tailwind"],
    "Material UI": ["MUI"],
    "Redux Toolkit": ["RTK"],
    "GitHub Actions": ["GHA"],
    "OpenTelemetry": ["OTel"],
    "Infrastructure as Code": ["IaC"],
    "Domain-Driven Design": ["DDD"],
    "Event-Driven Architecture": ["EDA"],
    "Continuous Integration": ["CI"],
    "Apache Kafka": ["Kafka"],
    "Ruby on Rails": ["Rails", "RoR"],
    "Django REST Framework": ["DRF"],
    "Express.js": ["Express"],
    "Spring Boot": ["SB"],
    "Hugging Face": ["HF"],
    "TensorFlow": ["TF"],
    "PyTorch": ["Torch"],
    "scikit-learn": ["sklearn"],
    "Amazon SQS": ["SQS"],
    "Amazon SNS": ["SNS"],
    "Amazon EKS": ["EKS"],
    "Google GKE": ["GKE"],
    "Azure AKS": ["AKS"],
    "Amazon Cognito": ["Cognito"],
    "Weights & Biases": ["W&B", "wandb"],
    "Twelve-Factor App": ["12-factor"],
    "C++": ["CPP"],
    "C#": ["CSharp"],
    ".NET": ["dotnet"],
    "REST API": ["REST", "RESTful"],
    "OAuth 2.0": ["OAuth2"],
    "OpenID Connect": ["OIDC"],
    "CI/CD": ["CICD"],
    "ELK Stack": ["ELK"],
    "AWS CDK": ["CDK"],
    "Entity Framework": ["EF"],
    "Entity Framework Core": ["EF Core"],
    "React Testing Library": ["RTL"],
    "CSS Modules": ["CSS Mod"],
    "styled-components": ["SC"],
}

# Technology suffixes that may be added or removed
TECH_SUFFIXES = [".js", ".py", ".rs", "JS", "Lang"]

# Common version qualifiers
VERSION_QUALIFIERS = [
    " 3.x", " 2.0", " v4", " v2", " 5.0", " 1.x",
    " 3", " 4", " 2", " v3", " v5",
]


def _generate_abbreviation(name: str) -> str | None:
    """Generate a programmatic abbreviation by taking first letters of words."""
    words = re.split(r"[\s\-./]+", name)
    if len(words) < 2:
        return None
    abbrev = "".join(w[0].upper() for w in words if w)
    # Only return if it is meaningfully shorter
    if len(abbrev) >= len(name) - 1:
        return None
    return abbrev


def _swap_adjacent(s: str, rng: random.Random) -> str:
    """Swap two adjacent characters in the string."""
    if len(s) < 3:
        return s
    idx = rng.randint(1, len(s) - 2)
    chars = list(s)
    chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
    return "".join(chars)


def _drop_letter(s: str, rng: random.Random) -> str:
    """Drop a random interior letter."""
    if len(s) < 4:
        return s
    idx = rng.randint(1, len(s) - 2)
    return s[:idx] + s[idx + 1 :]


def _double_letter(s: str, rng: random.Random) -> str:
    """Double a random interior letter."""
    if len(s) < 3:
        return s
    idx = rng.randint(1, len(s) - 2)
    return s[:idx] + s[idx] + s[idx:]


def generate_variants(canonical: str, rng: random.Random) -> list[tuple[str, str]]:
    """Generate (variant, variant_type) pairs for a canonical name."""
    variants: list[tuple[str, str]] = []

    # 1. Lowercase
    variants.append((canonical.lower(), "lowercase"))

    # 2. UPPERCASE
    variants.append((canonical.upper(), "uppercase"))

    # 3. Abbreviations — known or generated
    known = KNOWN_ABBREVIATIONS.get(canonical, [])
    for abbr in known:
        variants.append((abbr, "abbreviation"))
    generated_abbr = _generate_abbreviation(canonical)
    if generated_abbr and generated_abbr not in known:
        variants.append((generated_abbr, "abbreviation"))

    # 4. Version-qualified
    qualifier = rng.choice(VERSION_QUALIFIERS)
    variants.append((canonical + qualifier, "version_qualified"))

    # 5. Common misspellings (3 types)
    variants.append((_swap_adjacent(canonical, rng), "misspelling_swap"))
    variants.append((_drop_letter(canonical, rng), "misspelling_drop"))
    variants.append((_double_letter(canonical, rng), "misspelling_double"))

    # 6. Suffix variations — add or strip .js / .py / JS etc.
    base_name = canonical
    has_suffix = False
    for suffix in TECH_SUFFIXES:
        if canonical.endswith(suffix):
            base_name = canonical[: -len(suffix)]
            has_suffix = True
            break
    if has_suffix:
        # Strip the suffix
        variants.append((base_name, "suffix_removed"))
    else:
        # Add a plausible suffix
        suffix = rng.choice(TECH_SUFFIXES[:3])  # .js, .py, .rs
        variants.append((canonical + suffix, "suffix_added"))

    return variants


def build_benchmark(seed: int = 42) -> list[dict]:
    """Build the full synthetic benchmark dataset.

    Returns a list of dicts with keys: variant, canonical, variant_type, split.
    The canonical names are split 80/20 into train/test using a seeded shuffle.
    """
    rng = random.Random(seed)

    # Deduplicate canonical names (CANONICAL_NAMES maps many aliases -> canonical)
    unique_canonicals = sorted(set(CANONICAL_NAMES.values()))

    # Shuffle and split 80/20
    shuffled = list(unique_canonicals)
    rng.shuffle(shuffled)
    split_idx = int(len(shuffled) * 0.8)
    train_set = set(shuffled[:split_idx])
    # test_set is the remainder

    rows: list[dict] = []
    for canonical in unique_canonicals:
        split = "train" if canonical in train_set else "test"
        for variant, variant_type in generate_variants(canonical, rng):
            rows.append(
                {
                    "variant": variant,
                    "canonical": canonical,
                    "variant_type": variant_type,
                    "split": split,
                }
            )

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic benchmark for entity resolution evaluation."
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(
            Path(__file__).resolve().parent / "data" / "synthetic_benchmark.csv"
        ),
        help="Output CSV path (default: evaluation/data/synthetic_benchmark.csv)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = build_benchmark(seed=args.seed)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["variant", "canonical", "variant_type", "split"]
        )
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    canonicals = set(r["canonical"] for r in rows)
    train_count = sum(1 for r in rows if r["split"] == "train")
    test_count = sum(1 for r in rows if r["split"] == "test")
    print(f"Generated {len(rows)} variants for {len(canonicals)} canonical entities")
    print(f"  Train: {train_count}  |  Test: {test_count}")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
