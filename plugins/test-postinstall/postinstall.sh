#!/usr/bin/env bash
set -euo pipefail

plugin_dir="$(cd "$(dirname "$0")" && pwd)"
out_file="$plugin_dir/postinstall-test-info.txt"
run_id="${RANDOM}${RANDOM}"
host_name="$(hostname 2>/dev/null || echo unknown)"
now_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$out_file" <<EOF
postinstall test plugin
run_id=$run_id
time_utc=$now_utc
hostname=$host_name
pid=$$
script=$0
cwd=$PWD
EOF

echo "Wrote test info to $out_file"
