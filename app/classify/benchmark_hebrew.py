"""Synthetic Hebrew retrieval smoke benchmark; no private messages or database writes."""

import argparse
import asyncio
import json

from app.classify.learning import tokens
from app.classify.ollama import OllamaModerator

# Paraphrase targets, with benign near-topic distractors. This is a smoke test, not accuracy.
CASES = [
    ("threat", "אני אהרוג אותך מחר", "מחר אפגע בך עד שתמות"),
    ("game", "ניצחתי אותך במשחק מחשב", "הפסדת לי בסיבוב בפלייסטיישן"),
    ("support", "אני כאן בשבילך אם קשה לך", "אם אתה עצוב אפשר לדבר איתי"),
    ("exclusion", "אף אחד לא רוצה אותך בקבוצה שלנו", "לא נצרף אותך כי כולם שונאים אותך"),
    ("homework", "צריך לסיים את שיעורי הבית בחשבון", "יש תרגילים במתמטיקה למחר"),
    ("meal", "ניפגש לאכול פיצה אחרי הלימודים", "אחרי בית הספר נלך יחד לפיצריה"),
]


async def benchmark(base_url: str, model: str) -> dict[str, object]:
    client = OllamaModerator(base_url, model)
    try:
        vectors = await client.embed(model, [c[1] for c in CASES] + [c[2] for c in CASES])
    finally:
        await client.aclose()
    rows = []
    for i, (name, _, query) in enumerate(CASES):
        q = tokens(query)
        lexical = [len(q & tokens(c[1])) / len(q | tokens(c[1])) for c in CASES]
        semantic = [
            sum(a * b for a, b in zip(vectors[len(CASES) + i], v, strict=True))
            for v in vectors[: len(CASES)]
        ]
        best = max(range(len(CASES)), key=lambda j: semantic[j])
        lex_best = max(range(len(CASES)), key=lambda j: lexical[j])
        rows.append(
            {
                "case": name,
                "semantic_match": best == i,
                "semantic_top": CASES[best][0],
                "semantic_similarity": round(semantic[best], 4),
                "lexical_match": lex_best == i and lexical[lex_best] > 0,
                "lexical_has_overlap": max(lexical) > 0,
            }
        )
    return {
        "scope": "synthetic Hebrew retrieval smoke test; not safety accuracy",
        "embedding_model": model,
        "cases": len(CASES),
        "results": rows,
        "semantic_top1_matches": sum(bool(r["semantic_match"]) for r in rows),
        "lexical_top1_matches": sum(bool(r["lexical_match"]) for r in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    print(
        json.dumps(asyncio.run(benchmark(args.base_url, args.model)), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
