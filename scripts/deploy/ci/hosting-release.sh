#!/usr/bin/env bash
# Firebase Hosting release history through the REST API, for rolling a site back to the version that was live before
# a deploy. Needs an OAuth access token in FIREBASE_ACCESS_TOKEN (google-github-actions/auth, token_format: access_token).
#
#   hosting-release.sh current <site>                the version name now live: sites/<site>/versions/<id>
#   hosting-release.sh rollback <site> <version>     make that version the live release again
#
# Hosting only: this never touches Firestore, Functions or Storage.
set -euo pipefail

API="${LOAM_HOSTING_API:-https://firebasehosting.googleapis.com/v1beta1}"
die() { echo "::error::$*" >&2; exit 1; }
[ -n "${FIREBASE_ACCESS_TOKEN:-}" ] || die "FIREBASE_ACCESS_TOKEN is not set"
site_re='^[a-z0-9-]{1,30}$'
version_re='^sites/[a-z0-9-]{1,30}/versions/[A-Za-z0-9]{1,40}$'
auth=(-H "Authorization: Bearer ${FIREBASE_ACCESS_TOKEN}")

case "${1:-}" in
    current)
        [[ "${2:-}" =~ $site_re ]] || die "usage: hosting-release.sh current <site>"
        curl -fsS "${auth[@]}" "${API}/sites/$2/releases?pageSize=1" | jq -r '.releases[0].version.name // empty'
        ;;
    rollback)
        [[ "${2:-}" =~ $site_re && "${3:-}" =~ $version_re ]] || die "usage: hosting-release.sh rollback <site> <sites/SITE/versions/ID>"
        [ "${3#sites/}" != "${3}" ] && [ "$(cut -d/ -f2 <<<"$3")" = "$2" ] || die "version $3 belongs to another site"
        curl -fsS -X POST "${auth[@]}" -H 'Content-Length: 0' "${API}/sites/$2/releases?versionName=$(jq -rn --arg v "$3" '$v | @uri')" >/dev/null
        echo "rolled $2 back to $3"
        ;;
    *) die "usage: hosting-release.sh current|rollback ..." ;;
esac
