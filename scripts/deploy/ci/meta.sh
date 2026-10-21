#!/usr/bin/env bash
# Print the base64 JSON <meta> the gate takes, from the environment: PR_TITLE PR_URL REF AUTHOR ACTOR RUN_URL
# (any may be empty). Exits non-zero when the result would exceed the gate's 4096-character limit.
set -euo pipefail
meta="$(jq -nc --arg pr_title "${PR_TITLE:-}" --arg pr_url "${PR_URL:-}" --arg ref "${REF:-}" \
    --arg author "${AUTHOR:-}" --arg actor "${ACTOR:-}" --arg run_url "${RUN_URL:-}" \
    '{pr_title:$pr_title,pr_url:$pr_url,ref:$ref,author:$author,actor:$actor,run_url:$run_url} | with_entries(select(.value != ""))' \
    | base64 -w0)"
[ "${#meta}" -le 4096 ] || { echo "::error::deploy metadata is too long" >&2; exit 1; }
printf '%s' "${meta}"
