#!/usr/bin/env bash
# provenum model benchmark on maddog: Qwen2.5 / Qwen3 / Llama, both anchoring modes, 315 gold items.
# Runs in tmux session provenum-bench; results to /mnt/STORAGE3/alobo/provenum-bench/bench_results.csv.
set -u
B=/mnt/STORAGE3/alobo/provenum-bench
OLLAMA=/mnt/STORAGE3/alobo/tools/ollama/bin/ollama
export OLLAMA_HOST=127.0.0.1:11500
mkdir -p "$B"
LOG="$B/bench.log"
echo "$(date -Is) started" | tee -a "$LOG"

# Code: provenum branch with the benchmark, and DockPrepBench main for the paper and tables.
if [ -d "$B/provenum" ]; then git -C "$B/provenum" fetch -q origin && git -C "$B/provenum" checkout -q -B feat/ollama-anchor origin/feat/ollama-anchor
else git clone -q -b feat/ollama-anchor https://github.com/David-Alobo/provenum.git "$B/provenum"; fi
D=/mnt/STORAGE3/alobo/DockPrepBench
if [ -n "$(git -C "$D" status --porcelain --untracked-files=no)" ]; then
  echo "$(date -Is) STOP: $D has local changes; not touching it" | tee -a "$LOG"; exit 1
fi
git -C "$D" fetch -q origin main && git -C "$D" checkout -q main && git -C "$D" merge -q --ff-only origin/main
echo "$(date -Is) code ready: provenum $(git -C "$B/provenum" rev-parse --short HEAD), DockPrepBench $(git -C "$D" rev-parse --short HEAD)" | tee -a "$LOG"

MODELS="qwen2.5:7b-instruct qwen2.5:14b-instruct qwen2.5:32b-instruct qwen3:8b qwen3:14b qwen3:32b llama3.1:8b-instruct-q4_K_M llama3.3:70b-instruct-q4_K_M"
for m in $MODELS; do
  "$OLLAMA" pull "$m" >/dev/null 2>&1 && echo "$(date -Is) pulled $m" | tee -a "$LOG" || echo "$(date -Is) FAILED to pull $m" | tee -a "$LOG"
done
df -h /mnt/STORAGE3 | tail -1 | tee -a "$LOG"

cd "$D"
PY="uv run --no-project --python 3.12 python"
PYTHONPATH="$B/provenum/src:$B/provenum/examples" $PY "$B/provenum/examples/bench_models.py" paper/sections/results.tex \
  --spec paper/numbers.toml --tables paper/tables --host http://127.0.0.1:11500 \
  --notes "$B/provenum/examples/dockprepbench_notes.txt" --none "pH 7.4" "2.857 times" \
  --models $MODELS --out "$B/bench_results.csv" 2>&1 | tee -a "$LOG"
echo "$(date -Is) finished" | tee -a "$LOG"
