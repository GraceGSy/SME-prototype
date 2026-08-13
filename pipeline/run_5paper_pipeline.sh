#!/bin/bash
# One-off driver for running the full pipeline (steps 1-10 + the current
# epoch-refinement track) against the 5-paper set that excludes the Gentner
# 2010 paper, with all output redirected to a fresh directory via
# SME_OUTPUT_DIR so the existing 3-paper output/sections/ run is untouched.
set -euo pipefail
cd "$(dirname "$0")"

export SME_OUTPUT_DIR="$(pwd)/output/sections_5papers"
export SME_N_EPOCHS=3

echo "=== Output dir: $SME_OUTPUT_DIR ==="
mkdir -p "$SME_OUTPUT_DIR"

echo; echo "### Step 1: extract_sections.py ###"
python3 extract_sections.py \
  "../papers/abstractexplorer.pdf" \
  "../papers/corpusstudio.pdf" \
  "../papers/examplore_chi18.pdf" \
  "../papers/mesotext.pdf" \
  "../papers/paralib_uist22.pdf"

echo; echo "### Step 2: attach_section_text.py ###"
python3 attach_section_text.py

echo; echo "### Step 3: extract_fine_grained.py ###"
python3 extract_fine_grained.py

echo; echo "### Step 4: match_tags.py ###"
python3 match_tags.py

echo; echo "### Step 5: prune_bidirectional.py ###"
python3 prune_bidirectional.py

echo; echo "### Step 6: group_matches.py ###"
python3 group_matches.py

echo; echo "### Step 7: summarize_groups.py ###"
python3 summarize_groups.py

echo; echo "### Step 8: refine_paragraph_groups.py ###"
python3 refine_paragraph_groups.py

echo; echo "### Step 9: compute_ranking_matrices.py ###"
python3 compute_ranking_matrices.py

echo; echo "### Step 10: compute_group_balance.py ###"
python3 compute_group_balance.py

echo; echo "### Epoch refinement: refine_with_epoch_matrix1_reassign.py (3 epochs) ###"
python3 refine_with_epoch_matrix1_reassign.py

echo; echo "### Epoch balance: compute_epoch_group_balance.py ###"
python3 compute_epoch_group_balance.py epoch_matrix1_reassign_refinement

echo; echo "=== DONE: full 5-paper pipeline written to $SME_OUTPUT_DIR ==="
