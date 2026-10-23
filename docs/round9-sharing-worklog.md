# Round 9 worklog: shared route links and friends

Ticket: GH-42 (`JJRPF/loam#42`). The plan is the issue body; this file records what was built, where it deviates, and how it was checked.

## The rules, as built

1. Only planned routes are ever shared, never rides. A share is a snapshot of one saved route (`app/sharing.py::build_snapshot`): name, sport, distance, climb, line, surface strip and mix. Not stored in a share: waypoints (via points), the verbal summary, and the strip's `is_unridden` flag, because all three can say something about the owner's riding history or home.
2. Sharing is per route and explicit. `saved_routes.visibility` is `private` (default; the migration adds the column with that default, so every existing route stays private), `link` or `friends`.
3. Privacy zones: `GET /api/saved-routes/{id}/share/preview` says whether the first or last point is inside one of the owner's zones. By default `POST .../share` drops the leading and trailing points inside a zone (`trim_to_zones`) and recomputes distance and surface mix from what is left; the owner opts out with `trim: false` ("Share the full route"). A route entirely inside the zones cannot be shared (422). Climb figures of a trimmed route are `null`, not scaled.
4. No directory: friends connect only through a one-time invite link (7 days). Friends are addressed by a surrogate `friendships.id`, never a user id.
5. Others see only the owner's sharing name (`users.share_display_name`, <= 40 characters, default "A Loam rider").
6. No leaderboards, badges or feeds.

## Phase 1: data model

`db/migrations/009_shared_routes_friends.sql` (idempotent): `saved_routes.visibility`, `users.share_display_name`, `route_shares`, `friend_invites`, `friendships`, `blocks`. Everything cascades from `users` / `saved_routes`, so `delete_user_account` and deleting a saved route remove shares, friendships, invites and blocks; the legacy re-key (`account_migration.rekey_users`) moves `route_shares.user_id` because it finds every table with a `user_id` column (a legacy account has no friends: sharing postdates it). Tested for both.

**Deviations**
- No `revoked_at` column. Revoking deletes the share row (line, token hash and counters with it), so nothing of a revoked share remains. The plan's `last_viewed_at` and `view_count` are kept (owners see "opened N times"; no viewer is recorded).
- No elevation profile in the snapshot: saved routes keep 2-D lines only (`save_route_to_db` strips elevation), so a profile does not exist to snapshot. The page uses the existing `ElevationProfile` component, which already draws only the strip and stats when there is no elevation.
- The friendship pair is ordered with `CHECK (user_a < user_b COLLATE "C")` and the API sorts by bytes. The first version compared in the database's locale collation and the browser suite caught it: Firebase uids are mixed case, so `Zz..`/`aa..` ordered differently in Python and PostgreSQL. `test_mixed_case_user_ids_can_befriend_each_other` fails on the old behaviour (checked by mutation).

## Phase 2: API

`app/sharing.py`, mounted in `app/main.py`. 24 endpoints:

- Owner: `GET|POST|DELETE /api/saved-routes/{id}/share(/preview)`, `GET /api/me/shares`, `GET|PUT /api/me/profile`.
- Public (no auth, `SHARE_VIEW` limit, `X-Robots-Tag: noindex`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`): `GET /api/shared/{token}` and `.../export/gpx|fit`. Unknown, malformed, revoked and deleted answer the same 404.
- Friends: invites (`POST|GET /api/friends/invites`, `DELETE .../{id}`, `GET .../{token}`, `POST .../{token}/accept`), `GET /api/friends`, `DELETE /api/friends/{id}`, `POST /api/friends/{id}/block`, `DELETE /api/friends/blocks/{id}`, `GET /api/friends/routes`, `GET /api/friends/routes/{id}` (+ `/export/gpx|fit`).
- Copy to my routes: `POST /api/shared/{token}/copy`, `POST /api/friends/routes/{id}/copy`.
- `GET /api/privacy/export` now includes a `sharing` object (the user's own shares, counts and dates of friendships, invites and blocks; no other person's id, no token).

Other changes
- `GET /api/export/gpx|fit/{route_id}` (saved route by id) had no auth at all, so anyone with a route id could download it. Now owner-only (the app never called it; `test_stage2_mvp` updated).
- Tokens: `secrets.token_urlsafe(32)` (256 bits); the database stores only the sha256 hex. Lookup is by hash, so there is no string comparison against a secret. `redact_tokens` plus a logging filter on `uvicorn.access/error` replace the token in `/api/shared/<token>`, `/api/friends/invites/<token>` and the SPA paths with `<token>`; installed at import in `app/main.py`.
- Limits: `RATE_LIMIT_SHARE_VIEW` (120/600 s per IP) and `RATE_LIMIT_SHARE_CREATE` (30/3600 s per user); at most 20 open invites per user.
- Blocking is two-way: a block (either direction) ends the friendship, hides routes, and makes invites between the two answer like unknown ones.

## Phase 3: frontend

- `/r/<token>`: `SharedRoutePage` (read-only map, surface strip and stats, GPX / FIT / Send to Garmin Connect, Copy to my routes with an inline sign-in card, Plan a route from here, "shared by", "This route was shared with you" frame, friendly "This link no longer works" page). Signed out works. `main.tsx` picks it by path before `App` mounts, so the planner, geolocation and route search never start on a shared page.
- `/friends/invite/<token>`: sign in, then Accept or Decline.
- Saved panel: a Share button per route (`ShareRouteModal`: Link / Friends / Private, the privacy-zone notice with the "share the full route" opt-in, copy link, stop sharing), a "Shared by link / with friends" label, and a "Shared with me" section.
- You panel: `FriendsSection` (sharing name, invite link, open invites, friends with Remove and Block, blocked with Unblock, routes you are sharing with Stop sharing).
- `firebase.json`: `/r/**` and `/friends/invite/**` get `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex, nofollow` and `Cache-Control: no-store`. The existing catch-all rewrite already sends both paths to `index.html` (the service worker's navigate fallback too). No new CSP origin, no new script.
- Social preview: `index.html` is the only page crawlers see, so `/r/<token>` unfurls with the generic Loam card (static OG tags, `social-card-1200x630.png`); there is no per-route map image or coordinate anywhere in the tags.

## Phase 4: legal and docs

Privacy policy: new "Sharing routes and friends" section (#sharing), the collected-data list, logs, deletion and export lines; Terms: a "Sharing routes" clause. Both effective October 14, 2026. **The owner reviews this text before merge.** README: a "Share a route" feature and a Privacy bullet.

Claims behind the new text:

| Claim | Where it is true |
|---|---|
| Only routes are shared; rides, zones, email, user id never | `app/sharing.py::share_payload`, `friend_route_summary` (explicit field lists); `tests/test_round9_sharing.py` (forbidden-key walk, owner id and email not in any public or friend response) |
| Every route is private until shared | `db/migrations/009_shared_routes_friends.sql::saved_routes.visibility` default; `test_existing_and_new_routes_stay_private` |
| Zone parts are left out by default; full route is an opt-in | `app/sharing.py::build_snapshot`, `trim_to_zones`; `test_default_trim_leaves_nothing_inside_the_zone`, `test_opt_out_stores_the_full_route` |
| A share is a snapshot; deleting the route removes it | `route_shares.route_id ... ON DELETE CASCADE`; `test_unknown_revoked_and_deleted_look_identical` |
| Stopping deletes the copy and the code and the link dies at once | `app/sharing.py::_revoke`; `test_link_share_public_view_export_revoke` |
| Links are long random codes, only a hash is stored, not logged | `app/sharing.py::new_token`, `hash_token`, `redact_tokens`; `test_only_hashes_are_stored_and_tokens_are_not_logged`, `test_access_log_redaction` |
| Search engines are asked not to index | `app/sharing.py::PUBLIC_HEADERS`; `firebase.json` (`/r/**`); `SharedRoutePage` robots meta |
| Friends only through a one-time, 7-day invite; no lookup | `app/sharing.py::create_invite`, `accept_invite`, `INVITE_DAYS`; `test_invite_rules` |
| Block ends the friendship and stops invites | `app/sharing.py::block_friend`, `_usable_invite`; `test_invite_rules`, the authorization matrix |
| Counts only, no viewer record | `route_shares.view_count`, `last_viewed_at`; `_link_share` |
| Deleting the account removes it all; export includes it | `ON DELETE CASCADE`; `test_account_deletion_removes_everything_shared`, `test_data_export_includes_sharing_without_other_people_or_tokens` |

## Phase 5: tests

`tests/test_round9_sharing.py` (24 tests): the authorization matrix (every new endpoint x owner, friend, signed-in stranger, blocked user, admin, signed out; route states private / link / friends / revoked / deleted; IDOR on route ids, share ids, friendship ids, invite ids and swapped tokens; reused, expired, own and blocked invites), leak tests (forbidden-key walk, zone trimming, opt-out, migration default), token tests (>= 256 bits, hash-only row, caplog, redaction filter), rate limits (429 with `Retry-After`), the route-table test (every non-public endpoint depends on `get_current_user`, the three public ones are an explicit allowlist, the saved-route exports are owner-only), account deletion and legacy re-key, privacy export, the mixed-case regression, and a check that the legal pages describe sharing.

`tests/browser/sharing.spec.ts` (10 tests, Auth emulator, two users, a synthetic route at the Bear Brook parking area): share by link, open in a fresh signed-out context, GPX download, revoke and see the dead link; an unknown token; the privacy-zone notice; invite, accept, the friend sees the route, unfriend, it is gone, block and unblock; axe on the shared page, the dead-link page, the invite page, Saved > Shared with me, You > friends and the share dialog; 360 / 390 / 412 px with no overlap, no sideways scroll and 44 px targets; every test also fails on console errors, failed requests or CSP violations.

Run from a worktree without `node_modules` at the repo root: `cd frontend && NODE_PATH=$PWD/node_modules node_modules/.bin/playwright test -c ../tests/browser/playwright.config.ts` (the config imports `@playwright/test` from `tests/browser`).

## Phase 6: release (owner)

Not deployed. When you say go:

1. Pi: `scripts/backup_db.sh`, check the dump is non-empty, `git pull`, `python -m scripts.migrate` (applies `009`), restart `loam-api`.
2. Hosting only: `scripts/deploy-web.sh` (`firebase deploy --only hosting`, never rules or functions).
3. Smoke: sign in on loam.thepfisters.com, save a throwaway route, share it by link, open the link in a private window, download the GPX, stop sharing, reload to see "This link no longer works".

Known limit: Firebase Hosting and Tailscale see the link as part of the page address (the privacy text says so); Loam's own server log redacts it.
