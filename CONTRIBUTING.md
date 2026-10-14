# Contributing

Loam is a small project run by one person. Bug reports and trail-data corrections are the most useful contributions; pull requests are welcome for focused fixes.

- **Bugs and trail problems:** open an issue (templates provided), or use "Report bad route" in the app. Issues are public, so keep personal details out.
- **Code:** open an issue first for anything bigger than a small fix, so we can agree on the approach. Keep pull requests to one change.
- **Run it:** the README has the setup. `PYTHONPATH=. pytest -q` runs the API tests (they need the local PostGIS and GraphHopper containers) and `npm run test:browser` in `frontend/` runs the browser suite.
- **Style:** follow the code around your change. Plain, short comments that say why. User-facing text in sentence case.
- **Privacy rules are not negotiable:** no fabricated data, nothing that publishes an individual rider's data below the 3-rider rule, no tracking, and never commit ride files, coordinates of homes, tokens or `.env` files.
- **License:** by contributing you agree your changes are licensed under the AGPL-3.0-or-later, like the rest of the project.
