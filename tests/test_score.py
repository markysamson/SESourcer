from sesourcer.jd import parse_job
from sesourcer.profiles import parse_profile
from sesourcer.score import score_profile

BRIEF = """
Senior Product Manager
London

What you'll need
- Payments
- Open banking
- SQL
- Stakeholder management
- Agile

Nice to have
- Fintech
"""


def _score(title, url, snippet, notes=""):
    brief = parse_job(BRIEF, notes=notes)
    profile = parse_profile(title, url, snippet)
    assert profile is not None
    return score_profile(profile, brief)


def test_close_profile_scores_higher_than_a_mismatch():
    strong = _score(
        "Jane Doe - Senior Product Manager at ClearBank | LinkedIn",
        "https://www.linkedin.com/in/jane-doe",
        "Senior Product Manager at ClearBank · Experience: ClearBank · Location: London · "
        "6 years at ClearBank. Payments, open banking, SQL, agile, stakeholder management, fintech.",
    )
    weak = _score(
        "Bob Lee - Junior Java Developer | LinkedIn",
        "https://www.linkedin.com/in/bob-lee",
        "Junior Java Developer · Experience: Some Studio · Location: Mumbai · Java and Android.",
    )
    assert strong.score >= 85
    assert strong.band == "Strong fit"
    assert "Payments" in strong.matched_skills
    assert weak.score < 50
    assert weak.band == "Weak fit"
    assert strong.score > weak.score


def test_wrong_city_cannot_outrank_a_local_match():
    local = _score(
        "Jane Doe - Senior Product Manager at ClearBank | LinkedIn",
        "https://www.linkedin.com/in/jane-doe",
        "Senior Product Manager · Experience: ClearBank · Location: London · Payments, SQL, agile.",
    )
    abroad = _score(
        "Sam Patel - Senior Product Manager | LinkedIn",
        "https://www.linkedin.com/in/sam-patel",
        "Senior Product Manager · Experience: Example Bank · Location: Mumbai · "
        "Payments, open banking, SQL, agile, stakeholder management, fintech.",
    )
    assert local.score > abroad.score
    assert abroad.score <= 64


def test_notes_change_the_score():
    without = _score(
        "Jane Doe - Senior Product Manager at ClearBank | LinkedIn",
        "https://www.linkedin.com/in/jane-doe",
        "Senior Product Manager · Experience: ClearBank · Location: London · Payments, SQL.",
        notes="Monzo",
    )
    with_note = _score(
        "Jane Doe - Senior Product Manager at Monzo | LinkedIn",
        "https://www.linkedin.com/in/jane-doe-2",
        "Senior Product Manager · Experience: Monzo · Location: London · Payments, SQL.",
        notes="Monzo",
    )
    assert with_note.score > without.score
    assert "Monzo" in with_note.rationale
