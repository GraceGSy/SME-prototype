#!/bin/bash
# Scratch runner for the references-excluded hybrid pipeline run. Loads the
# API key from SME/.env (handles the "KEY = value" spacing) and points
# SME_OUTPUT_DIR at the paragraph-filtered sections_skills_hybrid_core/
# folder, then execs whatever script is passed as an argument.
set -euo pipefail
cd "$(dirname "$0")"

export ANTHROPIC_API_KEY="$(python3 -c "
import re
content = open('../.env').read()
m = re.search(r'^ANTHROPIC_API_KEY\s*=\s*(.+)\$', content, re.MULTILINE)
print(m.group(1).strip().strip('\"').strip(\"'\"))
")"
export SME_OUTPUT_DIR="$(pwd)/output/sections_skills_hybrid_core"
export SME_N_EPOCHS=3

exec python3 "$@"
