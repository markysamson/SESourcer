from sesourcer.jd import build_queries, note_terms, parse_job

BRIEF = """
Senior Product Manager, Payments
London, United Kingdom (hybrid)

We are hiring a Senior Product Manager to own the payments experience.

What you'll need
- 6+ years in product management
- Payments or open banking experience
- Stakeholder management with engineering and compliance
- Agile roadmapping
- SQL

Nice to have
- Experimentation and A/B testing

About us
We use Excel for planning and like dogs.
"""


def test_brief_reads_title_place_level_and_skills():
    brief = parse_job(BRIEF, notes="Prefer people who have worked at Monzo.")
    assert brief.title == "Senior Product Manager, Payments"
    assert brief.seniority == "senior"
    assert brief.locations == ["London"]
    assert "United Kingdom" in brief.countries
    assert brief.hybrid is True
    assert brief.years_experience == 6
    assert "Payments" in brief.must_have
    assert "Open banking" in brief.must_have
    assert "SQL" in brief.must_have
    assert "Stakeholder management" in brief.must_have
    assert "Product management" not in brief.must_have
    assert "Excel" not in brief.must_have
    assert "Excel" not in brief.nice_to_have
    assert "B testing" not in brief.nice_to_have
    assert "e-money institution" not in brief.nice_to_have
    assert "A/B testing" in brief.nice_to_have or "Experimentation" in brief.nice_to_have
    assert "Monzo" in brief.note_terms


def test_queries_search_public_profile_pages_and_respect_the_limit():
    brief = parse_job(BRIEF)
    queries = build_queries(brief, limit=20)
    assert 3 <= len(queries) <= 6
    assert all(query.startswith("site:linkedin.com/in") for query in queries)
    assert any("London" in query for query in queries)
    assert any("product manager" in query for query in queries)
    assert any("Payments" in query or "Open banking" in query for query in queries)
    assert all('"' not in query for query in queries)
    assert all("Senior Product Manager, Payments" not in query for query in queries)
    assert len(build_queries(brief, limit=1)) >= 3


def test_note_terms_keep_useful_words():
    assert "bank" in [term.lower() for term in note_terms("Prefer people who have worked at a UK bank.")]
