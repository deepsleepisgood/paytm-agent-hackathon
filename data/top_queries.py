"""
Top customer queries from the Hugging Face payment-app complaints dataset.

Setup:
    pip install datasets pandas

Run:
    python top_queries.py

Outputs (same folder):
    top_categories.csv        category counts, all reviews vs Paytm-only
    category_examples.csv     5 example queries per category (Paytm-only)
"""

import re
from collections import Counter

import pandas as pd
from datasets import load_dataset

# Sentiment-only labels, not real queries/problems.
NOT_A_QUERY = {"Good App", "Bad App"}

STOP = set("""
a an the i my me we you your it its is are was were be been to of in on for and or
but not no with this that have has had do did does app paytm please very so am
at by from as can cant will get got any all also even just one they them their
""".split())


def main():
    print("Downloading dataset (first run takes a minute)...")
    ds = load_dataset("Amanaccessassist/sample", split="train")
    df = ds.to_pandas()[["input", "output"]].rename(
        columns={"input": "text", "output": "category"}
    )
    df["text"] = df["text"].astype(str)
    df["is_paytm"] = df["text"].str.contains(r"pay\s?tm", case=False, regex=True)

    total, paytm_total = len(df), int(df["is_paytm"].sum())
    print(f"\nRows: {total:,}   Mentioning Paytm: {paytm_total:,}")

    all_counts = df["category"].value_counts()
    paytm_counts = df.loc[df["is_paytm"], "category"].value_counts()
    table = pd.DataFrame({
        "all_reviews": all_counts,
        "all_pct": (all_counts / total * 100).round(1),
        "paytm_only": paytm_counts,
        "paytm_pct": (paytm_counts / max(paytm_total, 1) * 100).round(1),
    }).fillna(0).sort_values("paytm_only", ascending=False)
    table["is_real_query"] = ~table.index.isin(NOT_A_QUERY)
    table.to_csv("top_categories.csv")

    print("\n=== TOP QUERY CATEGORIES (Paytm-only, excluding Good/Bad App) ===")
    q = table[table["is_real_query"]]
    print(q[["paytm_only", "paytm_pct", "all_reviews"]].head(15).to_string())

    # Most common words inside each top category = what people actually ask about.
    print("\n=== WHAT PEOPLE SAY IN THE TOP 8 CATEGORIES (Paytm-only) ===")
    examples = []
    paytm = df[df["is_paytm"]]
    for cat in q.head(8).index:
        texts = paytm.loc[paytm["category"] == cat, "text"]
        words = Counter(
            w for t in texts for w in re.findall(r"[a-z]{3,}", t.lower())
            if w not in STOP
        )
        print(f"\n[{cat}]  top words: {', '.join(w for w, _ in words.most_common(10))}")
        # Medium-length examples are the most readable.
        sample = texts[texts.str.len().between(60, 220)].sample(
            min(5, len(texts)), random_state=1
        ) if len(texts) else []
        for t in sample:
            print(f"  - {t}")
            examples.append({"category": cat, "example": t})

    pd.DataFrame(examples).to_csv("category_examples.csv", index=False)
    print("\nSaved top_categories.csv and category_examples.csv")


if __name__ == "__main__":
    main()
