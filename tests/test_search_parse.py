from pathlib import Path
from urllib.parse import urlparse

from sesourcer.search import fetch_bing, fetch_duckduckgo, parse_bing_rss, parse_duckduckgo_html

FIXTURE = Path(__file__).parent / "fixtures" / "ddg.html"


def test_duckduckgo_fixture_keeps_profile_urls_only():
    hits = parse_duckduckgo_html(FIXTURE.read_text(encoding="utf-8"))
    assert [hit.url for hit in hits] == [
        "https://www.linkedin.com/in/jane-doe",
        "https://www.linkedin.com/in/bob-lee-99aa11",
    ]
    assert "ClearBank" in hits[0].snippet
    assert "London" in hits[0].snippet
    assert hits[0].title.startswith("Jane Doe")


def test_bing_rss_ignores_non_profile_links():
    xml = """
    <rss><channel>
      <item>
        <title>Jane Doe - Engineer | LinkedIn</title>
        <link>https://uk.linkedin.com/in/jane-doe?trk=public</link>
        <description>Engineer · Location: London</description>
      </item>
      <item>
        <title>Backend Development</title>
        <link>https://example.com/backend</link>
        <description>Not a person</description>
      </item>
    </channel></rss>
    """
    hits = parse_bing_rss(xml)
    assert len(hits) == 1
    assert hits[0].url == "https://www.linkedin.com/in/jane-doe"


def test_bing_empty_rss_does_not_raise(monkeypatch):
    def fake_get(url, accept="text/html"):
        if "format=rss" in url:
            return """<rss><channel><item><title>Example</title><link>https://example.com/x</link><description>x</description></item></channel></rss>"""
        return "<html><body><li class=\"b_algo\"><h2><a>Test</a></h2></li></body></html>"

    monkeypatch.setattr("sesourcer.search._get", fake_get)
    monkeypatch.setenv("SESOURCER_NO_CACHE", "1")
    assert fetch_bing("site:linkedin.com/in example query") == []


def test_duckduckgo_fetch_never_calls_linkedin(monkeypatch):
    requested = []

    def fake_get(url, accept="text/html"):
        requested.append(url)
        return FIXTURE.read_text(encoding="utf-8")

    monkeypatch.setattr("sesourcer.search._get", fake_get)
    monkeypatch.setenv("SESOURCER_NO_CACHE", "1")
    hits = fetch_duckduckgo('site:linkedin.com/in "product manager" London')
    assert hits
    assert requested
    assert all(urlparse(url).hostname != "www.linkedin.com" for url in requested)
    assert all("linkedin.com" not in (urlparse(url).hostname or "") for url in requested)
