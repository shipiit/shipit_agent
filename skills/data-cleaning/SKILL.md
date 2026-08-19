---
name: Data Cleaning
description: Turn a messy CSV, spreadsheet or export into something analysable, without silently changing what it says. Use when data has inconsistent formats, missing values, duplicates or bad headers.
tools: [bash, read_file, write_file, glob]
trigger_phrases: ["clean this data", "messy csv", "fix this spreadsheet", "deduplicate"]
version: 1.0.0
---

# Data Cleaning

Cleaning is lossy. Every step discards or alters something, and the danger is not
a step that fails — it is one that succeeds quietly and changes what the data
means. A pipeline that drops 4,000 rows without saying so produces a clean file
and a wrong answer.

So: **look first, count everything, and never modify in place.**

## 1. Look before transforming

Read the first twenty rows and the last twenty. Exports commonly carry a title
row above the header, a totals row below the data, or a second header partway
through where two files were concatenated. A parser pointed at the wrong header
row produces plausible nonsense.

Then, per column: how many rows, how many distinct values, how many empty, and
what the extremes are. Most problems are visible in that one summary.

## 2. Count at every step

Record the row count before and after each operation, and say what changed:

    loaded          12,481 rows
    dropped header       2 rows (repeated header at line 4,102)
    parsed dates    12,479 rows  (37 unparseable → quarantined)
    deduplicated    11,904 rows  (575 exact duplicates on order_id)

If a step removes rows you did not expect, stop. That is the finding, not an
inconvenience.

## 3. Quarantine, do not delete

Rows that fail to parse go to a separate file, not to `/dev/null`. They are the
most informative rows in the dataset — they show where the assumption is wrong,
and they are often the ones the person cares about.

## 4. Handle the usual suspects explicitly

**Dates.** The single largest source of silent corruption. `03/04/2024` is two
different days depending on locale. Establish the format from the source, never
by inference from a sample — a sample of unambiguous dates tells you nothing.

**Numbers as text.** Thousands separators, currency symbols, trailing spaces,
parentheses for negatives, `1.234,56` in European format. Strip deliberately and
count what fails to convert.

**Encoding.** `Ã©` where `é` belongs means UTF-8 was read as Latin-1. Fix at the
read, not with a replacement table.

**Whitespace and case.** `"Acme "`, `"acme"` and `"ACME"` are three customers
until they are not. Normalise for matching, but keep the original for display —
the person recognises their own spelling.

**Missing.** `""`, `NA`, `N/A`, `NULL`, `-`, `0` and `999` may all mean missing,
and `0` may also mean zero. Ask rather than assume; guessing here changes every
average in the result.

## 5. Deduplicate on a stated key

"Remove duplicates" is not a specification. Duplicate *on what* — the id, the
whole row, or a business key? And which copy survives: first, last, or most
complete? Say which you used, and report how many were removed.

## 6. Verify against something you did not compute

A total, a known row count, a spot-check of five rows against the source. A
clean file that reconciles to nothing is a clean file you cannot defend.

## What to report

Input rows, output rows, what each step removed and why, the quarantine file, and
every assumption made — especially the date format and what counted as missing.
The assumptions are the part someone will need to challenge.
