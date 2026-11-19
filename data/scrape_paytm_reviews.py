"""
Scrape Paytm Google Play reviews (consumer app + Paytm for Business) into CSV.

Setup:
    pip install google-play-scraper pandas

Run:
    python scrape_paytm_reviews.py              # default 20,000 reviews per app
    python scrape_paytm_reviews.py --count 5000 # quicker test

Output:
    paytm_reviews.csv  (one row per review, both apps combined)
"""

import argparse
import time

import pandas as pd
from google_play_scraper import Sort, reviews

APPS = {
    "net.one97.paytm": "Paytm (consumer)",
    "com.paytm.business": "Paytm for Business (merchant)",
}

# Simple keyword tags so you can filter complaint types quickly.
# Order matters: the first match becomes the primary tag.
TAGS = {
    "refund": ["refund", "money back", "not returned", "reversal", "revers"],
    "failed_txn": ["failed", "deducted", "debited", "pending", "stuck", "not received", "not credited"],
    "settlement": ["settlement", "settle", "payout"],
    "kyc_login": ["kyc", "otp", "login", "log in", "verify", "aadhar", "aadhaar", "blocked"],
    "loan_credit": ["loan", "emi", "postpaid", "credit"],
    "soundbox_device": ["soundbox", "sound box", "pos", "device", "machine"],
    "cashback_offer": ["cashback", "cash back", "offer", "reward", "coupon", "voucher"],
    "customer_support": ["customer care", "customer service", "support", "no response", "not responding", "helpline"],
    "app_bug": ["crash", "slow", "bug", "not opening", "hang", "update", "server"],
}


def tag_review(text: str) -> str:
    t = (text or "").lower()
    for tag, words in TAGS.items():
        if any(w in t for w in words):
            return tag
    return "other"


# Settings to try in order; Google Play sometimes returns nothing for one combo.
ATTEMPTS = [
    ("NEWEST", "en", "in"),
    ("MOST_RELEVANT", "en", "in"),
    ("NEWEST", "en", "us"),
    ("NEWEST", "hi", "in"),
]


def scrape_with(app_id, target, sort_name, lang, country, batch=200):
    rows, token, errors = [], None, 0
    while len(rows) < target:
        try:
            result, token = reviews(
                app_id,
                lang=lang,
                country=country,
                sort=getattr(Sort, sort_name),
                count=min(batch, target - len(rows)),
                continuation_token=token,
            )
        except Exception as e:
            errors += 1
            print(f"    error ({type(e).__name__}): {e}")
            if errors >= 3:
                break
            time.sleep(10)
            continue
        if not result:
            break
        rows.extend(result)
        print(f"  {app_id}: {len(rows)} reviews")
        if token is None:
            break
        time.sleep(1)  # be polite to the server
    return rows


def scrape_app(app_id: str, target: int) -> list[dict]:
    for sort_name, lang, country in ATTEMPTS:
        print(f"  trying sort={sort_name}, lang={lang}, country={country}")
        rows = scrape_with(app_id, target, sort_name, lang, country)
        if rows:
            return rows
        print("    got 0 reviews")
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20000, help="reviews per app")
    parser.add_argument("--out", default="paytm_reviews.csv")
    args = parser.parse_args()

    frames = []
    for app_id, app_name in APPS.items():
        print(f"Scraping {app_name}...")
        data = scrape_app(app_id, args.count)
        df = pd.DataFrame(data)
        if df.empty:
            continue
        df["app_id"] = app_id
        df["app_name"] = app_name
        frames.append(df)

    if not frames:
        print(
            "\nNo reviews were returned for any app.\n"
            "Check two things:\n"
            "  1. Can you reach Google Play?  curl -sI https://play.google.com | head -1\n"
            "  2. Does the library work at all?\n"
            "     python -c \"from google_play_scraper import app; print(app('net.one97.paytm')['title'])\"\n"
            "If (1) works but (2) fails, Google changed its page format: run\n"
            "  pip install -U google-play-scraper\n"
            "and try again."
        )
        raise SystemExit(1)

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset="reviewId")
    df = df.rename(columns={
        "content": "review_text",
        "score": "rating",
        "at": "review_date",
        "replyContent": "paytm_reply",
        "repliedAt": "reply_date",
        "thumbsUpCount": "thumbs_up",
        "appVersion": "app_version",
    })
    df["complaint_tag"] = df["review_text"].apply(tag_review)
    df["has_paytm_reply"] = df["paytm_reply"].notna()

    # Drop usernames/profile images: not needed and keeps the data less personal.
    keep = [
        "reviewId", "app_name", "review_date", "rating", "review_text",
        "complaint_tag", "thumbs_up", "app_version",
        "paytm_reply", "reply_date", "has_paytm_reply",
    ]
    df = df[[c for c in keep if c in df.columns]].sort_values("review_date")
    df.to_csv(args.out, index=False)

    print(f"\nSaved {len(df):,} reviews to {args.out}")
    print("\nComplaint tags:")
    print(df["complaint_tag"].value_counts().to_string())
    print(f"\nDate range: {df['review_date'].min()} to {df['review_date'].max()}")


if __name__ == "__main__":
    main()
