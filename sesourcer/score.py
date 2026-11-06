"""Score how well a public profile fits the role that was asked for."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sesourcer.jd import JobBrief
from sesourcer.lexicon import (
    COUNTRY_ALIASES,
    COUNTRY_DISPLAY,
    ROLE_STOP,
    SENIORITY_RANK,
    SENIORITY_WORDS,
    TOKEN_SYNONYMS,
    canonical_country,
    contains_term,
    country_of_city,
)
from sesourcer.profiles import Profile

_ROLE_WEIGHT = 30
_MUST_WEIGHT = 27
_NICE_WEIGHT = 8
_LOCATION_WEIGHT = 15
_SENIORITY_WEIGHT = 12
_NOTES_WEIGHT = 8


@dataclass
class ScoredProfile:
    profile: Profile
    score: int
    band: str
    rationale: str
    matched_skills: list[str]
    missing_skills: list[str]
    breakdown: dict[str, int]


def score_profile(profile: Profile, brief: JobBrief) -> ScoredProfile:
    role_ratio = _role_ratio(brief, profile.role, profile.headline)
    matched, missing, skill_ratio = _skill_ratio(profile, brief)
    location_ratio, location_note = _location_ratio(profile, brief)
    seniority_ratio, seniority_note = _seniority_ratio(profile, brief)
    notes_ratio, notes_note = _notes_ratio(profile, brief)

    must_weight = _MUST_WEIGHT if brief.nice_to_have else _MUST_WEIGHT + _NICE_WEIGHT
    nice_weight = _NICE_WEIGHT if brief.nice_to_have else 0
    # skill_ratio already blends must and nice. Split the points in the same proportion.
    if brief.must_have or brief.nice_to_have:
        skill_points = _points(must_weight + nice_weight, skill_ratio)
    else:
        skill_points = _points(must_weight + nice_weight, 0.6)

    breakdown = {
        "role": _points(_ROLE_WEIGHT, role_ratio),
        "skills": skill_points,
        "location": _points(_LOCATION_WEIGHT, location_ratio),
        "seniority": _points(_SENIORITY_WEIGHT, seniority_ratio),
        "notes": _points(_NOTES_WEIGHT, notes_ratio),
    }
    total = min(100, sum(breakdown.values()))
    capped = total
    strict_place = _location_strict(brief)
    if strict_place and location_ratio < 1.0:
        capped = min(total, 42)
    elif brief.locations and profile.location and not brief.remote and not strict_place:
        if location_ratio <= 0.2:
            capped = min(total, 64)
        elif location_ratio < 0.7:
            capped = min(total, 79)
    if capped < total:
        breakdown["location"] = max(0, breakdown["location"] - (total - capped))
        total = capped
    rationale = _rationale(
        profile,
        brief,
        role_ratio,
        matched,
        missing,
        location_note,
        seniority_note,
        notes_note,
    )
    return ScoredProfile(
        profile=profile,
        score=total,
        band=_band(total),
        rationale=rationale,
        matched_skills=matched,
        missing_skills=missing,
        breakdown=breakdown,
    )


def _points(weight: int, ratio: float) -> int:
    ratio = max(0.0, min(1.0, ratio))
    return int(round(weight * ratio))


def _band(score: int) -> str:
    if score >= 85:
        return "Strong fit"
    if score >= 70:
        return "Good fit"
    if score >= 50:
        return "Partial fit"
    return "Weak fit"


# "manager" and "lead" describe the job, not only the level, so they stay in the title.
_LEVEL_ONLY = SENIORITY_WORDS - {"manager", "lead"}


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", text.lower())
    tokens = set()
    for token in raw:
        if token in ROLE_STOP or token in _LEVEL_ONLY:
            continue
        tokens.add(TOKEN_SYNONYMS.get(token, token))
    return tokens


def _role_ratio(brief: JobBrief, role: str, headline: str) -> float:
    wanted_phrase = (brief.function or brief.title).strip().lower()
    blob = f"{role} {headline}".lower()
    if wanted_phrase and wanted_phrase in blob:
        return 0.95
    wanted_tokens = _tokens(brief.title)
    core = _role_core_tokens(brief)
    if core:
        wanted_tokens |= core
    if not wanted_tokens:
        return 0.45
    observed = _tokens(f"{role} {headline}")
    if not observed:
        return 0.18
    overlap = wanted_tokens & observed
    token_ratio = len(overlap) / len(wanted_tokens)
    if core:
        core_overlap = core & observed
        core_ratio = len(core_overlap) / len(core)
        blended = 0.72 * core_ratio + 0.28 * token_ratio
    else:
        blended = token_ratio
    return max(0.0, min(1.0, blended))


def _role_core_tokens(brief: JobBrief) -> set[str]:
    if not brief.function:
        return set()
    raw = brief.function.lower()
    parts = re.split(r"[\s/]+", raw)
    return {TOKEN_SYNONYMS.get(p, p) for p in parts if p and p not in ROLE_STOP and p not in _LEVEL_ONLY}


def _skill_ratio(profile: Profile, brief: JobBrief) -> tuple[list[str], list[str], float]:
    blob = f"{profile.headline} {profile.snippet} {' '.join(profile.skills)}"
    must = brief.must_have
    nice = brief.nice_to_have
    matched_must = [skill for skill in must if contains_term(blob, skill)]
    missing_must = [skill for skill in must if skill not in matched_must]
    matched_nice = [skill for skill in nice if contains_term(blob, skill)]
    matched = matched_must + [skill for skill in matched_nice if skill not in matched_must]
    if not must and not nice:
        return matched, [], 0.6
    must_ratio = (len(matched_must) / len(must)) if must else 1.0
    nice_ratio = (len(matched_nice) / len(nice)) if nice else 1.0
    must_weight = 0.78 if nice else 1.0
    nice_weight = 0.22 if nice else 0.0
    return matched, missing_must, must_ratio * must_weight + nice_ratio * nice_weight


def _location_ratio(profile: Profile, brief: JobBrief) -> tuple[float, str]:
    wanted_countries = _wanted_countries(brief)
    strict = _location_strict(brief)

    if not brief.locations and not wanted_countries and not brief.remote:
        return 1.0, "The role does not name a place."

    if not profile.location:
        if strict and wanted_countries:
            return (
                0.08,
                "Location is not in the public snippet. This role is tied to a specific country, so that gap counts heavily.",
            )
        if brief.remote:
            return 0.7, "Location is not in the public snippet. The role allows remote work."
        return 0.45, "Location is not in the public snippet."

    profile_place = profile.location.lower()
    profile_country = country_of_city(profile.location) or _country_from_text(profile.location)

    if profile_place == "remote":
        if strict and wanted_countries:
            return (
                0.12,
                "Profile only says remote with no country. This role expects people in "
                f"{_country_phrase(wanted_countries)}.",
            )
        if brief.remote or brief.hybrid:
            return 0.85, "Profile says remote, which fits this role."
        return 0.35, "Profile says remote and the role names an office."

    wanted_cities = [city.lower() for city in brief.locations]
    if profile_place in wanted_cities:
        return 1.0, f"Location matches {profile.location}."

    if wanted_countries:
        if profile_country and profile_country in wanted_countries:
            # Country-level role (e.g. "Netherlands"): any city in that country is a full match.
            city_named = bool(
                brief.locations
                and wanted_cities
                and not any(c.lower() in _country_alias_keys() for c in brief.locations)
            )
            if city_named and profile_place in wanted_cities:
                return 1.0, f"Location matches {profile.location}."
            if city_named and profile_place not in wanted_cities:
                return (
                    1.0,
                    f"{profile.location} is in {_country_phrase({profile_country})} as required "
                    f"(city in the posting was indicative, not exclusive).",
                )
            return 1.0, f"Location is in {_country_phrase({profile_country})} as required."

        if profile_country and profile_country not in wanted_countries:
            return (
                0.0,
                f"Location is {profile.location} — outside {_country_phrase(wanted_countries)}.",
            )
        return (
            0.15,
            f"Could not confirm {profile.location} is in {_country_phrase(wanted_countries)} from the snippet.",
        )

    if any(country.lower() == profile_place for country in brief.countries):
        return 0.7, f"Location matches {profile.location}."
    if brief.remote:
        return 0.7, f"Location is {profile.location}. The role is remote, so this is still possible."
    return 0.12, f"Location is {profile.location}, which does not match the role."


def _wanted_countries(brief: JobBrief) -> set[str]:
    out = {c.lower() for c in brief.countries}
    for city in brief.locations:
        country = country_of_city(city)
        if country:
            out.add(country)
    return out


def _location_strict(brief: JobBrief) -> bool:
    """True when the posting names a country (or only a country) so we gate cross-border matches."""
    return bool(_wanted_countries(brief))


def _country_from_text(text: str) -> str | None:
    lowered = text.lower()
    for key in sorted(COUNTRY_ALIASES, key=len, reverse=True):
        if contains_term(lowered, key):
            canonical = canonical_country(key)
            if canonical:
                return canonical.lower()
    return None


def _country_phrase(countries: set[str]) -> str:
    if not countries:
        return "the target region"
    display = {COUNTRY_DISPLAY.get(c, c.title()) for c in countries}
    return ", ".join(sorted(display))


def _country_alias_keys() -> set[str]:
    return {key.lower() for key in COUNTRY_ALIASES}


def _seniority_ratio(profile: Profile, brief: JobBrief) -> tuple[float, str]:
    observed = _rank_in(profile.role) 
    if observed is None:
        observed = _rank_in(profile.headline)
    wanted = brief.seniority_rank
    note = "Seniority is not stated on the profile."
    ratio = 0.65
    if wanted is None:
        ratio = 1.0
        note = "The role does not name a level."
    elif observed is None:
        ratio = 0.62
        note = "Seniority is not stated on the profile."
    else:
        gap = observed - wanted
        if gap >= 0:
            ratio = 1.0
            note = "Seniority meets the role."
            if gap >= 3:
                note = "Seniority is above the role, and still able to do it."
        elif gap == -1:
            ratio = 0.7
            note = "Seniority is one step below the role."
        else:
            ratio = 0.25
            note = "Seniority is below the role."
    if brief.years_experience and profile.experience_years is not None:
        if profile.experience_years + 0.2 < brief.years_experience:
            ratio = min(ratio, 0.45)
            note = (
                f"Experience mentioned ({_years_phrase(profile.experience_years)}) "
                f"is under the {brief.years_experience}+ years asked for."
            )
        elif wanted is not None and observed is not None and observed >= wanted:
            note = (
                f"Seniority meets the role, with {_years_phrase(profile.experience_years)} mentioned."
            )
    return ratio, note


def _rank_in(text: str) -> int | None:
    for word in (
        "chief",
        "vp",
        "director",
        "head",
        "principal",
        "staff",
        "lead",
        "senior",
        "sr",
        "associate",
        "junior",
        "jr",
        "intern",
        "trainee",
    ):
        if contains_term(text, word):
            canonical = "senior" if word == "sr" else "junior" if word == "jr" else word
            return SENIORITY_RANK[canonical]
    return None


def _notes_ratio(profile: Profile, brief: JobBrief) -> tuple[float, str]:
    if not brief.note_terms:
        return 1.0, ""
    blob = f"{profile.headline} {profile.snippet} {profile.company or ''} {profile.role}"
    matched = [term for term in brief.note_terms if contains_term(blob, term)]
    missing = [term for term in brief.note_terms if term not in matched]
    ratio = len(matched) / len(brief.note_terms)
    if missing and not matched:
        note = "Notes not seen in the snippet: " + ", ".join(missing[:4]) + "."
    elif missing:
        note = "Notes partly matched. Missing: " + ", ".join(missing[:4]) + "."
    else:
        note = "Notes match: " + ", ".join(matched[:4]) + "."
    return ratio, note


def _rationale(
    profile: Profile,
    brief: JobBrief,
    role_ratio: float,
    matched: list[str],
    missing: list[str],
    location_note: str,
    seniority_note: str,
    notes_note: str,
) -> str:
    if role_ratio >= 0.85:
        title_bit = f"Title matches {brief.title}."
    elif role_ratio >= 0.5:
        title_bit = f"Related title ({profile.role}) for a {brief.title} search."
    else:
        title_bit = f"Title is a weak match for {brief.title}."
    bits = [title_bit]
    if profile.company:
        bits.append(f"Currently at {profile.company}.")
    if profile.tenure:
        bits.append(f"Tenure shown: {profile.tenure}.")
    if matched:
        bits.append("Skills in the snippet: " + ", ".join(matched[:6]) + ".")
    elif brief.must_have:
        bits.append("None of the required skills are mentioned in the public snippet.")
    if missing:
        bits.append("Not mentioned: " + ", ".join(missing[:5]) + ".")
    bits.append(location_note)
    bits.append(seniority_note)
    if notes_note:
        bits.append(notes_note)
    return " ".join(bit.strip() for bit in bits if bit)


def _years_phrase(years: float) -> str:
    rounded = int(round(years))
    if abs(years - rounded) < 0.15:
        return "1 year" if rounded == 1 else f"{rounded} years"
    return f"{years:.1f} years"
