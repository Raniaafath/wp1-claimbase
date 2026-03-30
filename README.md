# WP1 — ClaimBase: Scientific Claim Extraction Pilot

This folder contains the code and data for the **WP1 pilot study**:
extracting scientific claims from arXiv papers using the unarXive dataset.

The goal is to build a **baseline claim extraction pipeline** and evaluate it on a small gold sample through manual annotation, as a foundation for the larger WP1 dataset.

---

## Quick Start

### Option A — Heuristic pipeline (no API key needed)

```bash
cd ~/wp1-claimbase
source .venv/bin/activate

python wp1_extract_unarxive.py \
  --input sample.jsonl \
  --mode BC \
  --cs_only \
  --max_papers 49 \
  --out_csv claims_BC.csv \
  --label_csv label_BC.csv
```

### Option B — LLM pipeline (recommended)

```bash
cd ~/wp1-claimbase
source .venv/bin/activate
set -a && source .env && set +a   # loads OPENAI_API_KEY and OPENAI_BASE_URL

python wp1_extract_llm.py \
  --input sample.jsonl \
  --cs_only \
  --max_papers 21 \
  --out_csv claims_llm.csv \
  --label_csv label_llm.csv
```

Then open `label_llm.csv` (or `label_BC.csv`) in Excel / Google Sheets and fill in `is_claim`, `is_atomic`, `receipt_ok`.

---

## Setup & Requirements

**Python version:** 3.8 or higher

### Heuristic script (`wp1_extract_unarxive.py`)
No external dependencies — uses only the Python standard library.

```bash
cd ~/wp1-claimbase
python3 -m venv .venv
source .venv/bin/activate
```

### LLM script (`wp1_extract_llm.py`)
Requires the `openai` package and API credentials.

```bash
source .venv/bin/activate
pip install openai
```

Create a `.env` file in the project root:
```
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://llm.scads.ai/v1
```

The `.env` file is listed in `.gitignore` and will not be committed.

---

## Folder Contents

```
wp1-claimbase/
├── wp1_extract_unarxive.py       # Heuristic extraction script (Modes A/B/BC)
├── wp1_extract_llm.py            # LLM-based extraction script
├── sample.jsonl                  # Input: 49 papers from unarXive (one paper per line)
├── .env                          # API credentials (git-ignored)
│
├── claims_A.csv                  # Heuristic claims — Mode A  (356 rows, CS-only)
├── claims_B.csv                  # Heuristic claims — Mode B  (81 rows, CS-only)
├── claims_BC.csv                 # Heuristic claims — Mode BC (90 rows, CS-only)
├── claims_llm.csv                # LLM claims — Llama-3.3-70B (145 rows, CS-only)
│
├── label_A.csv                   # Manual labeling sheet — Mode A
├── label_B.csv                   # Manual labeling sheet — Mode B
├── label_BC.csv                  # Manual labeling sheet — Mode BC
├── label_llm.csv                 # Manual labeling sheet — LLM pipeline
│
├── unarXive_data_sample/         # Original downloaded sample folder
│   └── arXiv_src_2212_086.jsonl  # Source file (49 papers, Dec 2022 arXiv)
└── unarXive_data_sample.tar.gz   # Original archive
```

---

## Input Data

**Source:** [unarXive](https://github.com/IllDepence/unarXive) — a dataset of structured arXiv papers in JSONL format.  
**Sample file:** `arXiv_src_2212_086.jsonl` — 49 papers from December 2022 (`arXiv:2212.*`).  
**Format:** One JSON object per line. Each paper has:
- `paper_id` — arXiv ID (e.g. `2212.11867`)
- `abstract` — dict with a `text` field
- `body_text` — list of paragraphs, each with `section` and `text` fields

---

## How the Pipeline Works

The script processes each paper through five stages:

```
JSONL file
    │
    ▼
[1] Parse paper
    │  Extract abstract (dict → text) and body_text (list of paragraphs)
    │  Each paragraph has: section name + text content
    │
    ▼
[2] Section filter  (Modes B and BC only)
    │  Keep only paragraphs whose section name matches one of:
    │  abstract, conclu*, result*, experiment*, evaluation*, discussion*, finding*
    │
    ▼
[3] Sentence splitting
    │  Split paragraph text on sentence boundaries (. ! ? followed by whitespace)
    │  Discard sentences shorter than 15 characters
    │
    ▼
[4] Sentence filter  (Modes B and BC only)
    │  Discard: generic openers ("In this paper…", "This paper…")
    │  Discard: background "significant role/challenge/problem" patterns
    │  Keep if STRONG CUE present → accept immediately
    │  Keep if WEAK CUE present AND result/method evidence found → accept
    │  Otherwise discard
    │
    ▼
[5] Atomic split  (Mode BC only)
    │  If sentence contains exactly one " and ", try splitting into two sub-claims
    │  Only split if both halves are ≥25 chars and right half starts with a subject
    │
    ▼
Output: claims_*.csv  +  label_*.csv (random sample, up to 120 rows)
```

### Strong cues (v2) — accept immediately

```
"we find"           "we show"              "we demonstrate"     "we observe"
"our results"       "results indicate"     "results show"       "results demonstrate"
"outperforms"       "state-of-the-art"
```

### Weak cues (v2) — accept only with result or method evidence

```
"we propose"    "we introduce"    "we present"
"we evaluate"   "we compare"      "we report"    "we establish"
"achieves"      "improves"        "reduces"
```

### Result evidence (triggers weak cues)
- A percentage or multiplier: `92.3%`, `+5%`, `3x`
- Statistical significance: `statistically significant`, `p < 0.05`
- A metric word: `accuracy`, `F1`, `BLEU`, `ROUGE`, `AUC`, `precision`, `recall`,
  `perplexity`, `latency`, `runtime`, `throughput`, `memory`, `speedup`, `loss`

### Method evidence (triggers `we propose / introduce / present`)
- Phrase `"a/an/the method/model/framework/approach/system/algorithm"`
- A named system (capitalised word ≥4 chars, e.g. `EuclidNet`, `RoBERTa`)
- The word `called` or `named`

### Explicit blockers
- Sentences starting with `"In this paper"` or `"This paper"` → discarded
- Pattern `"significant role/challenge/issue/problem/impact/concern"` → discarded

---

## LLM Extraction Script — `wp1_extract_llm.py`

Sends each paper's abstract and relevant sections to an LLM via an OpenAI-compatible API.
The model is instructed to return a JSON array of scientific claims.

| Argument | Default | Description |
|---|---|---|
| `--input` | *(required)* | Path to the `.jsonl` input file |
| `--api_key` | `$OPENAI_API_KEY` | API key (falls back to env var) |
| `--base_url` | `$OPENAI_BASE_URL` / `https://llm.scads.ai/v1` | Endpoint base URL |
| `--model` | `meta-llama/Llama-3.3-70B-Instruct` | Model ID |
| `--cs_only` | off | Only process papers with a `cs.*` category |
| `--max_papers` | `49` | Maximum number of papers to process |
| `--max_chars` | `8000` | Max characters of paper text sent per API call |
| `--out_csv` | `claims_llm.csv` | Full extraction output |
| `--label_csv` | `label_llm.csv` | Random sample for manual labeling |
| `--label_n` | `120` | Number of rows in the labeling sample |
| `--delay` | `0.5` | Seconds to wait between API calls |

**Available models** (SCADS endpoint):

| Model ID | Notes |
|---|---|
| `meta-llama/Llama-3.3-70B-Instruct` | Default — strong general-purpose |
| `deepseek-ai/DeepSeek-V3.2` | High-capability alternative |
| `meta-llama/Llama-4-Scout-17B-16E-Instruct` | Llama 4 family |
| `meta-llama/Llama-3.1-8B-Instruct` | Faster / lighter option |

---

## Heuristic Extraction Script — Arguments

**File:** `wp1_extract_unarxive.py`

| Argument | Default | Description |
|---|---|---|
| `--input` | *(required)* | Path to the `.jsonl` input file |
| `--mode` | `BC` | Extraction mode: `A`, `B`, or `BC` (see below) |
| `--cs_only` | off | If set, skip papers that have no `cs.*` category |
| `--max_papers` | `49` | Maximum number of papers to process |
| `--out_csv` | `claims_out.csv` | Output file with all extracted claims |
| `--label_csv` | `label_sample.csv` | Output file with random sample for manual labeling |
| `--label_n` | `120` | Number of rows in the labeling sample |

---

## Extraction Modes

### Mode A — Abstract + Conclusion, all sentences
- Keeps **every sentence** found in the Abstract or Conclusion sections.
- High recall, low precision (many non-claim sentences included).
- **Pilot result (CS-only):** 356 claims from 21 papers.

### Mode B — Strong/weak cue filter + section filter
- Only scans "good" sections: Abstract, Conclusion, Results, Experiments, Evaluation, Discussion, Findings.
- Applies the **strong/weak cue architecture** (see above):
  - **Strong cues** → keep immediately
  - **Weak cues** → keep only with result evidence (metrics, %) or method evidence (named model/framework)
  - **Blockers** → drop generic openers and background "significant role/challenge" patterns
- **Pilot result (CS-only):** 81 claims from 21 papers (~68% precision estimated).

### Mode BC — Mode B + atomic split
- Everything in Mode B, plus:
- Sentences containing exactly one `" and "` are split into two atomic sub-claims when both halves are ≥25 characters and the right half starts with a recognisable subject (we/our/the/this/A–Z/0–9).
- **Pilot result (CS-only):** 90 claims from 21 papers (+9 from splitting).

---

## Output Files

### `claims_*.csv` — Full extraction output

| Column | Description |
|---|---|
| `paper_id` | arXiv paper ID |
| `section` | Section name the sentence came from |
| `para_idx` | Paragraph index within the paper body (-1 = abstract) |
| `sent_start` | Character offset of sentence start within the paragraph |
| `sent_end` | Character offset of sentence end |
| `claim_text` | The extracted candidate claim (may be a split sub-sentence) |
| `receipt_sentence` | The original full sentence the claim came from |

### `label_*.csv` — Manual labeling worksheets

Same columns as above, plus four **empty columns you fill in**:

| Column | What to write |
|---|---|
| `is_claim` | `yes` / `no` — is this genuinely a scientific claim? |
| `is_atomic` | `yes` / `no` — does it express exactly one single claim? |
| `receipt_ok` | `yes` / `no` — does `claim_text` match `receipt_sentence` faithfully? |
| `notes` | Any free-text comments |

Open the label file in **Excel or Google Sheets** and annotate row by row.

**After labeling, calculate precision:**
```
Precision = (rows where is_claim = yes) / (total rows labeled)
```

---

## Labeling Guidelines

Use these definitions when filling in the label columns.

### `is_claim` — Is this a scientific claim?

A **claim** is a sentence that asserts a finding, result, contribution, or property that can in principle be verified or challenged.

| Label | Example |
|---|---|
| `yes` | "We show that our model outperforms all baselines by 3.2% on BLEU." |
| `yes` | "The proposed method reduces inference time by 40%." |
| `yes` | "Our results indicate that transfer learning significantly improves low-resource performance." |
| `no`  | "In this section, we describe the experimental setup." |
| `no`  | "Related work on neural machine translation is discussed in Section 2." |
| `no`  | "Table 1 shows the results." *(just pointing to a table, no assertion)* |

### `is_atomic` — Does it express exactly one claim?

| Label | Example |
|---|---|
| `yes` | "Our model achieves state-of-the-art on three benchmarks." |
| `no`  | "We propose a new architecture and show it generalises well across languages." *(two claims)* |

### `receipt_ok` — Does `claim_text` match `receipt_sentence` faithfully?

Check that the text was not corrupted by the extraction (truncated, garbled, or wrong sentence boundary).

| Label | Meaning |
|---|---|
| `yes` | `claim_text` is a clean sub-sentence or full copy of `receipt_sentence` |
| `no`  | Text is garbled, truncated mid-word, or belongs to a different sentence |

### Notes on formula placeholders

unarXive replaces all mathematical expressions with tokens like `{{formula:abc123...}}`.  
This is expected — do **not** mark a row as `receipt_ok = no` just because of formula tokens.  
Only mark `no` if the natural language text itself is broken.

---

## Known Limitations (v2)

| Issue | Impact | Fix in v3 |
|---|---|---|
| Formula placeholders `{{formula:...}}` | Claims from papers with inline math look noisy | Normalise or strip formula tokens before extraction |
| Simple regex sentence splitter | Splits on abbreviations (e.g. "Fig. 1") or decimal numbers | Use a proper sentence tokeniser (e.g. `nltk.sent_tokenize`) |
| Atomic split produces fragments | Some split halves are incomplete clauses | Raise minimum split half length from 25 to 40 chars |
| Atomic split only handles one `" and "` | Multi-clause sentences not fully decomposed | Extend with conjunction heuristics or a dependency parser |
| No deduplication | Near-identical sentences across papers counted separately | Add fuzzy dedup step |
| Heuristic only — no ML model | Misses claims that don't match known cue patterns | Train a sentence classifier on the labeled gold sample |
| CS-only filter is coarse | Papers with `cs.*` + heavy math (e.g. `cs.LO`, `cs.NA`) still produce noisy claims | Add sub-category filter or formula-density check |

---

## Pilot Run Summary

All runs use `--cs_only` (21 CS papers out of 49 total; 28 math/physics papers skipped).

### Heuristic pipeline

| Mode | Papers | Sentences scanned | Claims extracted | Est. precision |
|------|--------|-------------------|-----------------|----------------|
| A    | 21 CS  | 358               | 356             | low (all kept) |
| B    | 21 CS  | 7,253             | 81              | ~68%           |
| BC   | 21 CS  | 7,253             | 90              | ~68%           |

**Key insights:**
- Mode A keeps nearly every sentence in Abstract + Conclusion — high recall, low precision.
- Mode B scans the full paper body (7,253 sentences) but keeps only 81 via the strong/weak cue filter — much higher precision.
- Mode BC adds 9 extra claims from the atomic `" and "` split.
- Estimated precision of ~68% is based on automated categorisation; manual labeling of `label_BC.csv` will give the exact number.

### LLM pipeline

| Model | Papers | Claims extracted | Notes |
|-------|--------|-----------------|-------|
| Llama-3.3-70B-Instruct | 21 CS | 145 | 1 paper failed JSON parse |

The LLM extracted **~60% more claims** than Mode BC (145 vs 90). Precision to be determined by annotating `label_llm.csv`.

### Evolution of precision across heuristic versions

| Version | Corpus | Claims (BC) | Est. precision |
|---------|--------|-------------|----------------|
| v1 — simple cue list | 49 mixed | 583 | ~30% |
| v2 — CS-only filter | 21 CS | 195 | ~42% |
| v3 — improved cues | 21 CS | 182 | ~49% |
| **v4 — strong/weak architecture** | **21 CS** | **90** | **~68%** |
| **LLM — Llama-3.3-70B** | **21 CS** | **145** | **TBD (annotate label_llm.csv)** |

---

## Full Reproduction Recipe

To reproduce everything from the raw archive:

```bash
cd ~/wp1-claimbase
source .venv/bin/activate

# Extract the archive (already done — skip if sample.jsonl exists)
tar -xzf unarXive_data_sample.tar.gz
cp unarXive_data_sample/arXiv_src_2212_086.jsonl sample.jsonl

# Verify: should print 49
wc -l sample.jsonl

# Run all three modes (CS papers only)
python wp1_extract_unarxive.py --input sample.jsonl --mode A  --cs_only --max_papers 49 --out_csv claims_A.csv  --label_csv label_A.csv
python wp1_extract_unarxive.py --input sample.jsonl --mode B  --cs_only --max_papers 49 --out_csv claims_B.csv  --label_csv label_B.csv
python wp1_extract_unarxive.py --input sample.jsonl --mode BC --cs_only --max_papers 49 --out_csv claims_BC.csv --label_csv label_BC.csv
```

Expected output (mode BC):
```
=== SUMMARY ===
mode: BC
cs_only: True
skipped (non-CS): 28
papers processed (N): 21
sentences seen: 7253
claims extracted: 90
wrote: claims_BC.csv
label sample: label_BC.csv (N= 90 )
```

---

## Next Steps

1. **Annotate LLM output** — Open `label_llm.csv`, label rows for `is_claim`, `is_atomic`, `receipt_ok`.
2. **Compare precision** — Heuristic BC ~68% (estimated) vs LLM TBD; use labeled samples for exact numbers.
3. **Fix LLM JSON parse error** — Paper `2212.11764` failed due to a bad escape in the model's JSON output; add a sanitisation step or retry with a stricter prompt.
4. **Try other models** — Re-run with `deepseek-ai/DeepSeek-V3.2` or `Llama-4-Scout-17B` and compare claim counts and quality.
5. **Add missing schema fields** — `claim_id`, `extraction_run_id`, `extractor`, `config_hash`, `timestamp`, `claim_type` (as per supervisor schema requirements).
6. **Scale up to CS.AI / CS.CL** — Filter to a larger set of papers from relevant sub-categories before scaling further.
7. **Fix atomic split fragments** — Raise minimum split half length to 40 chars to eliminate dangling clauses (heuristic pipeline).

---

## Reference

- **unarXive dataset:** Saier, T. & Färber, M. (2023). *unarXive 2022: All arXiv Publications Pre-Processed for NLP, Including Structured Full-Text and Disconnected Citations.* [GitHub](https://github.com/IllDepence/unarXive)
- **Sample file:** `arXiv_src_2212_086.jsonl` — batch 086 of December 2022 arXiv submissions.
