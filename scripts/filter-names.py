#!/usr/bin/env python3

import argparse
import unicodedata
import re
from pathlib import Path
from wordfreq import zipf_frequency

# Allow basic Latin letters + common name punctuation.
# For non-Latin scripts, relax this (see note below).
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]*[A-Za-z]$")

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def max_zipf(token: str, langs: list[str]) -> float:
    t = token.lower()
    best = float("-inf")
    for lang in langs:
        z = zipf_frequency(t, lang)
        if z > best:
            best = z
    return best

def is_unambiguous_name(name: str, langs: list[str], zipf_cutoff: float):
    n = normalize(name)

    # basic validity (adjust if you have multi-token names)
    if len(n) < 2 or len(n) > 25:
        return False, float("nan")

    # If you expect non-Latin scripts, remove this regex check (see below).
    if not NAME_RE.match(n):
        return False, float("nan")

    z = max_zipf(n, langs)

    # Strict: remove if it's a common word in ANY language in langs
    if z >= zipf_cutoff:
        return False, z

    return True, z

def main():
    p = argparse.ArgumentParser(description="Filter ambiguous names using word frequency across multiple languages.")
    p.add_argument("input", help="Input file (one name per line)")
    p.add_argument("--langs", default="en",
                   help="Comma-separated wordfreq language codes (default: en). Example: en,de,fr,es,it")
    p.add_argument("--zipf", type=float, default=3.5,
                   help="Zipf cutoff (default: 3.5, lower=stricter)")
    args = p.parse_args()

    langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    if not langs:
        raise SystemExit("No languages provided. Example: --langs en,de,fr")

    input_path = Path(args.input)
    kept_path = input_path.with_suffix(".kept.txt")
    removed_path = input_path.with_suffix(".removed.txt")

    kept = []
    removed = []

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue

            ok, z = is_unambiguous_name(raw, langs, args.zipf)
            if ok:
                kept.append(raw)
            else:
                removed.append((raw, z))

    # De-duplicate kept list
    kept_unique = sorted(set(kept))

    with open(kept_path, "w", encoding="utf-8") as f:
        for n in kept_unique:
            f.write(n + "\n")

    # removed: include score so you can audit; NaN means failed basic validity
    def score_key(x):
        n, z = x
        return -(z if z == z else -100)  # NaN sorts last

    with open(removed_path, "w", encoding="utf-8") as f:
        for n, z in sorted(removed, key=score_key):
            f.write(f"{n}\t{z}\n")

    print("Done.")
    print(f"Languages: {','.join(langs)}")
    print(f"Cutoff: {args.zipf}")
    print(f"Kept: {len(kept_unique)}")
    print(f"Removed: {len(removed)}")
    print("Output:")
    print(f"  {kept_path}")
    print(f"  {removed_path}")

if __name__ == "__main__":
    main()
