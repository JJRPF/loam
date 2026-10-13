"""Round 8 (GH-38) phase 6: the legal pages exist, say what the plan requires, and the claims audit points at real code."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEGAL = ROOT / "frontend" / "public" / "legal"


def _text(rel):
    return (LEGAL / rel).read_text()


def test_pages_exist_and_have_effective_date_and_summary():
    for rel in ("index.html", "privacy/index.html", "terms/index.html", "attributions/index.html"):
        html = _text(rel)
        assert "<title>" in html and "<h1>" in html
        if rel != "index.html":
            assert re.search(r"Effective [A-Z][a-z]+ \d{1,2}, 20\d\d", html), rel
            assert 'class="summary"' in html, rel


def test_privacy_policy_covers_the_required_topics():
    t = _text("privacy/index.html")
    for needle in (
        "Justin Pfister", "New Hampshire", "jjrpfister at gmail dot com", "0.2 mile", "privacy zones",
        "3 different people", "creator's own rides", "public issue on GitHub", "0.5 mile",
        "Google Firebase", "CARTO", "Photon", "National Weather Service", "Overpass", "Tailscale",
        "no ads", "/api/privacy/export", "/api/privacy/account", "7 days", "13 and older",
    ):
        assert needle in t or needle.lower() in t.lower(), needle
    assert "GDPR" not in t and "CCPA" not in t  # no compliance claims


def test_terms_cover_the_required_topics():
    t = _text("terms/index.html")
    for needle in ("closed, private, unsafe", "your own risk", "navigation or emergency", "license",
                   "scrape", "rate limits", "ODbL", "AGPL", "no warranty", "liable", "New Hampshire", "13 years"):
        assert needle.lower() in t.lower(), needle


def test_attributions_list_the_required_sources():
    t = _text("attributions/index.html")
    for needle in ("OpenStreetMap", "ODbL", "CARTO", "3DEP", "PAD-US", "OpenTrailMap", "Overpass", "Photon",
                   "api.weather.gov", "GraphHopper", "MapLibre", "Firebase", "Open Font License", "third-party.txt"):
        assert needle in t, needle
    third = _text("attributions/third-party.txt")
    assert "== Web app" in third and "== Server" in third and "maplibre-gl" in third and "fastapi" in third


def test_every_page_links_source_code_and_the_other_pages():
    for rel in ("index.html", "privacy/index.html", "terms/index.html", "attributions/index.html"):
        t = _text(rel)
        for href in ("/legal/privacy/", "/legal/terms/", "/legal/attributions/", "https://github.com/JJRPF/loam"):
            assert f'href="{href}"' in t, (rel, href)


def test_license_is_agpl_and_declared():
    lic = (ROOT / "LICENSE").read_text()
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in lic and "Version 3, 19 November 2007" in lic
    assert '"license": "AGPL-3.0-or-later"' in (ROOT / "frontend" / "package.json").read_text()


def test_claims_audit_references_real_code():
    doc = (ROOT / "docs" / "round8-legal-claims.md").read_text()
    refs = re.findall(r"`([\w./-]+\.(?:py|sql|ts|tsx|sh|html|yml|json|md))(?:::([\w]+))?`", doc)
    assert len(refs) > 40
    for path, symbol in refs:
        f = ROOT / path
        assert f.exists(), f"{path} is cited by the legal claims but missing"
        if symbol:
            assert symbol in f.read_text(), f"{path} has no {symbol}"
