import argparse, json, re, random, csv

SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')

# Strong cues: keep the sentence immediately
STRONG_CUES = [
    "we find", "we show", "we demonstrate", "we observe",
    "our results", "results indicate", "results show", "results demonstrate",
    "outperforms", "state-of-the-art",
]

# Weak cues: keep only if accompanied by result or method evidence
WEAK_CUES = [
    "we propose", "we introduce", "we present",
    "we evaluate", "we compare", "we report", "we establish",
    "achieves", "improves", "reduces",
]

# Metric words that indicate a sentence is reporting a result
METRIC_WORDS = [
    "accuracy", "f1", "bleu", "rouge", "auc", "map", "precision", "recall",
    "perplexity", "latency", "runtime", "throughput", "memory", "speedup",
    "performance", "error rate", "loss",
]

# sections where claims are more likely (v1 heuristic)
GOOD_SECTION_PATTERNS = [
    r"abstract", r"conclu", r"result", r"experiment", r"evaluation", r"discussion", r"finding"
]

def iter_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def sentence_spans(text: str):
    start = 0
    for m in SENT_SPLIT.finditer(text):
        end = m.start()
        sent = text[start:end].strip()
        if sent:
            yield start, end, sent
        start = m.end()
    last = text[start:].strip()
    if last:
        yield start, start + len(text[start:]), last

def is_good_section(name: str) -> bool:
    n = (name or "").lower()
    return any(re.search(pat, n) for pat in GOOD_SECTION_PATTERNS)

def has_result_evidence(s: str) -> bool:
    """Checks for numbers/metrics that signal a result sentence."""
    if re.search(r"\b\d+(\.\d+)?\s*%|\+\s*\d+(\.\d+)?\s*%|\b\d+(\.\d+)?x\b", s):
        return True
    if "statistically significant" in s or re.search(r"\bp\s*[<=>]\s*0\.\d+", s):
        return True
    if any(m in s for m in METRIC_WORDS):
        return True
    return False

def has_method_evidence(sentence: str) -> bool:
    """Checks for concrete method/model mentions (for propose/introduce/present)."""
    if re.search(r"\b(a|an|the)\s+(method|model|framework|approach|system|algorithm)\b", sentence, re.I):
        return True
    if re.search(r"\b(?!We\b)[A-Z][A-Za-z0-9\-]{3,}\b", sentence):
        return True
    if re.search(r"\b(called|named)\b", sentence, re.I):
        return True
    return False

def baseline_B_keep(sentence: str, section_name: str) -> bool:
    if not is_good_section(section_name):
        return False

    s = sentence.lower()

    # drop meta/fluffy openers
    if s.startswith("in this paper") or s.startswith("this paper"):
        return False

    # block "significant role/challenge/problem" background patterns
    if re.search(r"\bsignificant\s+(role|challenge|issue|problem|impact|concern)\b", s):
        return False

    # strong cues → keep immediately
    if any(p in s for p in STRONG_CUES):
        return True

    # weak cues → require extra evidence
    if any(p in s for p in WEAK_CUES):
        if any(p in s for p in ["we propose", "we introduce", "we present"]):
            return has_method_evidence(sentence) or has_result_evidence(s)
        return has_result_evidence(s)

    return False

def split_atomic(sentence: str):
    """Very lightweight 'A and B' split when safe (v1)."""
    s = re.sub(r"\s+", " ", sentence).strip()
    low = s.lower()
    if low.count(" and ") != 1:
        return [s]

    left, right = s.split(" and ", 1)
    left, right = left.strip(), right.strip()

    # avoid short/bad splits
    if len(left) < 25 or len(right) < 25:
        return [s]
    if not re.match(r"^(we|our|the|this|these|those|[A-Z0-9])", right):
        return [s]

    c1 = left if left.endswith((".", "!", "?")) else left + "."
    c2 = right if right.endswith((".", "!", "?")) else right + "."
    return [c1, c2]

def get_sections(paper: dict):
    """
    unarXive sample format:
    - abstract is dict with 'text'
    - body_text is list of dicts with 'section' and 'text'
    """
    out = []

    abs_obj = paper.get("abstract")
    if isinstance(abs_obj, dict) and abs_obj.get("text"):
        out.append(("Abstract", abs_obj["text"], -1))

    body = paper.get("body_text") or []
    for i, para in enumerate(body):
        if not isinstance(para, dict):
            continue
        sec = para.get("section") or "Body"
        txt = para.get("text") or ""
        if txt.strip():
            out.append((sec, txt, i))

    return out

def is_cs_paper(paper: dict) -> bool:
    cats = paper.get("metadata", {}).get("categories", "") or ""
    return "cs." in cats.lower()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--mode", choices=["A","B","BC"], default="BC")
    ap.add_argument("--max_papers", type=int, default=49)
    ap.add_argument("--out_csv", default="claims_out.csv")
    ap.add_argument("--label_csv", default="label_sample.csv")
    ap.add_argument("--label_n", type=int, default=120)
    ap.add_argument("--cs_only", action="store_true",
                    help="Only process papers that have at least one cs.* category")
    args = ap.parse_args()

    extracted = []
    total_sentences = 0
    papers = 0
    skipped_non_cs = 0

    for paper in iter_jsonl(args.input):
        if papers >= args.max_papers:
            break

        if args.cs_only and not is_cs_paper(paper):
            skipped_non_cs += 1
            continue

        paper_id = paper.get("paper_id") or paper.get("metadata", {}).get("id")
        if not paper_id:
            continue
        papers += 1

        for sec_name, text, para_idx in get_sections(paper):
            # Mode A: keep all sentences in Abstract + Conclusion
            if args.mode == "A":
                keep_section = (sec_name.lower() == "abstract") or ("conclu" in sec_name.lower())
                if not keep_section:
                    continue

            for s_start, s_end, sent in sentence_spans(text):
                total_sentences += 1
                sent_norm = re.sub(r"\s+", " ", sent).strip()
                if len(sent_norm) < 15:
                    continue

                if args.mode in ["B","BC"] and not baseline_B_keep(sent_norm, sec_name):
                    continue

                claim_texts = [sent_norm]
                if args.mode == "BC":
                    claim_texts = split_atomic(sent_norm)

                for ct in claim_texts:
                    ct = re.sub(r"\s+", " ", ct).strip()
                    if len(ct) < 15:
                        continue
                    extracted.append({
                        "paper_id": paper_id,
                        "section": sec_name,
                        "para_idx": para_idx,
                        "sent_start": s_start,
                        "sent_end": s_end,
                        "claim_text": ct,
                        "receipt_sentence": sent_norm
                    })

    # Save all extracted claims
    with open(args.out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "paper_id","section","para_idx","sent_start","sent_end","claim_text","receipt_sentence"
        ])
        w.writeheader()
        for r in extracted:
            w.writerow(r)

    # Save a random sample for manual labeling (gold sample)
    random.shuffle(extracted)
    sample = extracted[: min(args.label_n, len(extracted))]

    with open(args.label_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "paper_id","section","para_idx","sent_start","sent_end","claim_text","receipt_sentence",
            "is_claim","is_atomic","receipt_ok","notes"
        ])
        w.writeheader()
        for r in sample:
            w.writerow({**r, "is_claim":"", "is_atomic":"", "receipt_ok":"", "notes":""})

    print("=== SUMMARY ===")
    print("mode:", args.mode)
    print("cs_only:", args.cs_only)
    if args.cs_only:
        print("skipped (non-CS):", skipped_non_cs)
    print("papers processed (N):", papers)
    print("sentences seen:", total_sentences)
    print("claims extracted:", len(extracted))
    print("wrote:", args.out_csv)
    print("label sample:", args.label_csv, "(N=", len(sample), ")")

if __name__ == "__main__":
    main()
