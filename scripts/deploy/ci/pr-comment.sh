#!/usr/bin/env bash
# Create or update the one staging comment on a pull request (found by its hidden marker).
#
#   pr-comment.sh deployed|reset|left-alone
#
# Environment: GH_TOKEN, GITHUB_REPOSITORY, PR, and for `deployed`: SHA, RUN_URL, STAGING_URL.
set -euo pipefail

marker='<!-- loam-staging -->'
case "${1:-}" in
    deployed)
        # shellcheck disable=SC2016  # the backticks and the jq program are literal
        commits="$(gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR}/commits" --paginate \
            --jq '.[] | "- `" + .sha[0:7] + "` " + (.commit.message | split("\n")[0])')"
        # shellcheck disable=SC2016
        body="$(printf '%s\n**Staging:** %s (sign in with your Google account to see the PR banner)\n\nDeployed `%s` · [workflow run](%s)\n\nCommits on this PR:\n\n%s\n' \
            "${marker}" "${STAGING_URL}" "${SHA:0:7}" "${RUN_URL}" "${commits}")" ;;
    reset) body="$(printf '%s\nStaging moved back to main after this PR closed.\n' "${marker}")" ;;
    left-alone) body="$(printf '%s\nStaging was showing something else, so it was left alone.\n' "${marker}")" ;;
    *) echo "usage: pr-comment.sh deployed|reset|left-alone" >&2; exit 2 ;;
esac

id="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${PR}/comments" --paginate \
    --jq "[.[] | select(.body | startswith(\"${marker}\"))][0].id // empty")"
if [ -n "${id}" ]; then
    gh api -X PATCH "repos/${GITHUB_REPOSITORY}/issues/comments/${id}" -f body="${body}" >/dev/null
else
    gh api -X POST "repos/${GITHUB_REPOSITORY}/issues/${PR}/comments" -f body="${body}" >/dev/null
fi
