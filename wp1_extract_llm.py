#!/usr/bin/env python3
"""
LLM-based claim extraction from unarXive papers.

Uses an OpenAI-compatible API (default: SCADS endpoint).
Each paper's abstract + relevant sections are sent to the LLM,
which returns a JSON list of scientific claims.

Usage:
    python wp1_extract_llm.py \
        --input sample.jsonl \
        --api_key sk-... \
        --cs_only \
        --max_papers 21 \
        --out_csv claims_llm.csv \
        --label_csv label_llm.csv
"""

import argparse, json, os, re, random, csv, time
from openai import OpenAI

GOOD_SECTION_PATTERNS = [
    r"abstract", r"conclu", r"result", r"experiment",
    r"evaluation", r"discussion", r"finding",
]

SYSTEM_PROMPT = """\
You are a scientific claim extractor. Your task is to identify and extract \
scientific claims from academic paper text.

A **scientific claim** is a sentence (or part of a sentence) that asserts a \
finding, result, contribution, or measurable property that can in principle be \
verified or challenged by other researchers.

Examples of claims:
- "Our model outperforms all baselines by 3.2% on BLEU."
- "The proposed method reduces inference time by 40%."
- "We show that transfer learning significantly improves low-resource performance."

NOT claims (skip these):
- "In this section, we describe the experimental setup."
- "Related work on neural machine translation is discussed in Section 2."
- "Table 1 shows the results."

Return ONLY a valid JSON array — no explanation, no markdown code block.
Each element must have exactly these three string fields:
  "section"          : section name where the claim appears
  "claim_text"       : the atomic claim (one single assertion)
  "receipt_sentence" : the original full sentence the claim was taken from

If one sentence contains two distinct claims joined by "and", create two \
separate entries.  If no claims are found, return [].
"""


def iter_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def is_good_section(name):
    n = (name or "").lower()
    return any(re.search(pat, n) for pat in GOOD_SECTION_PATTERNS)


def is_cs_paper(paper):
    cats = paper.get("metadata", {}).get("categories", "") or ""
    return "cs." in cats.lower()


def build_paper_text(paper, max_chars):
    """Collect abstract + good sections, truncated to max_chars total."""
    parts = []

    abs_obj = paper.get("abstract")
    if isinstance(abs_obj, dict) and abs_obj.get("text"):
        parts.append(("[SECTION: Abstract]\n" + abs_obj["text"].strip(), "Abstract"))

    body = paper.get("body_text") or []
    for para in body:
        if not isinstance(para, dict):
            continue
        sec = para.get("section") or "Body"
        txt = (para.get("text") or "").strip()
        if txt and is_good_section(sec):
            parts.append((f"[SECTION: {sec}]\n{txt}", sec))

    combined = "\n\n".join(text for text, _ in parts)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n...[truncated]"
    return combined


def extract_claims_llm(client, paper_id, text, model):
    """Send paper text to LLM; return list of claim dicts."""
    user_msg = (
        f"Extract all scientific claims from the following paper text "
        f"(paper_id: {paper_id}):\n\n{text}"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # Find first JSON array in the response
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            return json.loads(m.group())

        print(f"  WARNING: no JSON array found for {paper_id}. Raw: {raw[:300]}")
        return []

    except Exception as exc:
        print(f"  ERROR for {paper_id}: {exc}")
        return []


def main():
    ap = argparse.ArgumentParser(
        description="LLM-based claim extraction from unarXive JSONL files."
    )
    ap.add_argument("--input",    required=True, help="Path to .jsonl input file")
    ap.add_argument("--api_key",  default=None,
                    help="API key (default: $OPENAI_API_KEY env var)")
    ap.add_argument("--base_url", default=None,
                    help="Base URL (default: $OPENAI_BASE_URL or https://llm.scads.ai/v1)")
    ap.add_argument("--model",    default="meta-llama/Llama-3.3-70B-Instruct",
                    help="Model ID to use")
    ap.add_argument("--max_papers", type=int, default=49)
    ap.add_argument("--max_chars",  type=int, default=8000,
                    help="Max characters of paper text sent per API call")
    ap.add_argument("--out_csv",   default="claims_llm.csv")
    ap.add_argument("--label_csv", default="label_llm.csv")
    ap.add_argument("--label_n",   type=int, default=120)
    ap.add_argument("--cs_only",   action="store_true",
                    help="Only process papers with at least one cs.* category")
    ap.add_argument("--delay",     type=float, default=0.5,
                    help="Seconds to wait between API calls (rate-limit safety)")
    args = ap.parse_args()

    api_key  = args.api_key  or os.environ.get("OPENAI_API_KEY")
    base_url = args.base_url or os.environ.get("OPENAI_BASE_URL", "https://llm.scads.ai/v1")
    client = OpenAI(api_key=api_key, base_url=base_url)

    FIELDS = [
        "paper_id", "section", "para_idx", "sent_start", "sent_end",
        "claim_text", "receipt_sentence",
    ]

    extracted = []
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

        print(f"[{papers}] {paper_id} ...", end=" ", flush=True)

        text = build_paper_text(paper, args.max_chars)
        if not text.strip():
            print("no text — skipped")
            continue

        claims = extract_claims_llm(client, paper_id, text, args.model)
        print(f"{len(claims)} claims")

        for c in claims:
            if not isinstance(c, dict):
                continue
            claim_text = (c.get("claim_text") or "").strip()
            receipt    = (c.get("receipt_sentence") or claim_text).strip()
            section    = (c.get("section") or "Unknown").strip()
            if len(claim_text) < 10:
                continue
            extracted.append({
                "paper_id":         paper_id,
                "section":          section,
                "para_idx":         -1,
                "sent_start":       -1,
                "sent_end":         -1,
                "claim_text":       claim_text,
                "receipt_sentence": receipt,
            })

        if args.delay > 0:
            time.sleep(args.delay)

    # Write full extraction output
    with open(args.out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in extracted:
            w.writerow(r)

    # Write label sample
    random.shuffle(extracted)
    sample = extracted[: min(args.label_n, len(extracted))]
    with open(args.label_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=FIELDS + ["is_claim", "is_atomic", "receipt_ok", "notes"]
        )
        w.writeheader()
        for r in sample:
            w.writerow({**r, "is_claim": "", "is_atomic": "", "receipt_ok": "", "notes": ""})

    print("\n=== SUMMARY ===")
    print("model:", args.model)
    print("cs_only:", args.cs_only)
    if args.cs_only:
        print("skipped (non-CS):", skipped_non_cs)
    print("papers processed:", papers)
    print("claims extracted:", len(extracted))
    print("wrote:", args.out_csv)
    print(f"label sample: {args.label_csv} (N= {len(sample)} )")


if __name__ == "__main__":
    main()
