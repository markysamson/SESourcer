from datetime import date

from sesourcer.profiles import parse_profile


TODAY = date(2026, 10, 30)


def test_profile_fields_from_a_typical_snippet():
    profile = parse_profile(
        "Jane Doe - Senior Product Manager at ClearBank | LinkedIn",
        "https://uk.linkedin.com/in/jane-doe?trk=public",
        "Senior Product Manager at ClearBank · Experience: ClearBank · Location: London · "
        "6 years at ClearBank. Payments, SQL, and stakeholder management. "
        "View Jane Doe's profile on LinkedIn.",
        today=TODAY,
    )
    assert profile is not None
    assert profile.name == "Jane Doe"
    assert profile.linkedin_url == "https://www.linkedin.com/in/jane-doe"
    assert profile.company == "ClearBank"
    assert profile.location == "London"
    assert profile.tenure == "6 years"
    assert profile.role == "Senior Product Manager"
    assert "Payments" in profile.skills
    assert "SQL" in profile.skills


def test_name_comes_from_the_snippet_when_the_title_is_only_a_headline():
    profile = parse_profile(
        "Product Manager | Financial Crime | UK FinTech - LinkedIn",
        "https://uk.linkedin.com/in/jonathonwcooper",
        "Product Manager | Financial Crime · Experience: ClearBank · Location: London · "
        "View Jonathon Cooper's profile on LinkedIn.",
        today=TODAY,
    )
    assert profile.name == "Jonathon Cooper"
    assert profile.company == "ClearBank"
    assert profile.location == "London"


def test_all_caps_name_and_credentials_are_cleaned():
    profile = parse_profile(
        "RISHABH KAPOOR, CFA - Lead Product Manager | Open Banking - LinkedIn",
        "https://www.linkedin.com/in/rishabh-kapoor",
        "Lead Product Manager · Location: London",
        today=TODAY,
    )
    assert profile.name == "Rishabh Kapoor"
    assert "CFA" not in profile.name


def test_past_office_and_total_experience_are_not_current_tenure():
    profile = parse_profile(
        "Alex Stone - Senior Product Manager | LinkedIn",
        "https://www.linkedin.com/in/alex-stone",
        "Senior Product Manager | Ex-Bloomberg London. Experience: JPMorgan Chase & Co. "
        "A decade of experience in markets.",
        today=TODAY,
    )
    assert profile.location is None
    assert profile.company == "JPMorgan Chase & Co"
    assert profile.tenure is None
    assert profile.experience == "10 years"


def test_a_person_named_london_is_not_given_that_city():
    profile = parse_profile(
        "Garrett London - Software Engineer | Python - LinkedIn",
        "https://www.linkedin.com/in/garrettlondon",
        "Software Engineer | Python. I build data tools.",
        today=TODAY,
    )
    assert profile.name == "Garrett London"
    assert profile.location is None
    assert profile.company is None


def test_present_role_dates_become_tenure():
    profile = parse_profile(
        "Mina Shah - Backend Engineer at Northwind | LinkedIn",
        "https://www.linkedin.com/in/mina-shah",
        "Backend Engineer · Northwind · Jan 2022 - Present · Location: Berlin · Python, PostgreSQL.",
        today=TODAY,
    )
    assert profile.company == "Northwind"
    assert profile.location == "Berlin"
    assert profile.tenure_years == 4.8
    assert profile.tenure == "4.8 years"


def test_snippet_parses_companies_locations_and_url_names():
    profile = parse_profile(
        "Senior Product Manager - Corporate Payments - LinkedIn",
        "https://www.linkedin.com/in/miteshpatel3005",
        "Senior Product Manager - Corporate Payments · I'm a results‑driven Product Manager with 9+ years "
        "leading digital product initiatives at Barclays and other FTSE‑listed financial services organisations.",
        today=TODAY,
    )
    assert profile.company == "Barclays"
    assert profile.experience == "9 years"
    profile2 = parse_profile(
        "Joe Lin - Senior Product Manager - Payments Platform | LinkedIn",
        "https://www.linkedin.com/in/joemlin",
        "Senior Product Manager - Payments Platform · Product leader with 15 years building payments platforms "
        "at Apple, Fiserv, and Citi, across consumer fintech.",
        today=TODAY,
    )
    assert profile2.name == "Joe Lin"
    assert profile2.company in {"Apple", "Fiserv", "Citi"}
    assert "Payments" in profile2.skills or profile2.role


def test_directory_pages_and_non_profiles_are_dropped():
    assert parse_profile("Top 10 engineers", "https://www.linkedin.com/in/dir", "x") is None
    assert parse_profile("Jane Doe", "https://example.com/jane", "x") is None
