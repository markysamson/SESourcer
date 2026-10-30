"""Turn a public search hit for a LinkedIn profile into structured fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import unquote, urlparse

from sesourcer.clean import decode_text
from sesourcer.lexicon import (
    CITY_ALIASES,
    CITY_COUNTRY,
    CREDENTIALS,
    DEPARTMENTS,
    INDUSTRY_WORDS,
    SKILL_DISPLAY,
    canonical_city,
    contains_term,
    find_skills,
)

_PROFILE = re.compile(
    r"linkedin\.com/in/([^/?#]+)",
    re.IGNORECASE,
)
_BLOCKED_SLUGS = {"dir", "pub", "jobs", "company", "school", "in", "posts"}
_CREDENTIAL = re.compile(
    r",?\s+(?:" + "|".join(re.escape(item) for item in CREDENTIALS) + r")\b\.?",
    re.IGNORECASE,
)
_VIEW_NAME = re.compile(
    r"View\s+(.{2,80}?)['’]s profile",
    re.IGNORECASE,
)
_EXPERIENCE_CO = re.compile(
    r"(?:Experience|工作经历)\s*[:：]\s*([^·|•\n.]+)",
    re.IGNORECASE,
)
_EXPERIENCE_AT = re.compile(
    r"\bexperience(?:\s+\w+){0,6}\s+at\s+([A-Z][\w&.'’+-]+(?:\s*(?:,|and)\s+[A-Z][\w&.'’+-]+){0,4})",
    re.IGNORECASE,
)
_ROLE_AT = re.compile(
    r"\b(?:Senior|Staff|Principal|Lead|Head|Junior|Associate)?\s*"
    r"(?:Product Manager|Software Engineer|Engineer|Designer|Analyst|Director|Manager)"
    r"[^·|•\n]{0,40}?\s+at\s+([A-Z][\w&.'’+-]+(?:\s+[A-Z0-9][\w&.'’+-]*){0,3})",
    re.IGNORECASE,
)
_LOCATION = re.compile(
    r"(?:Location|地点)\s*[:：]\s*([^·|•\n]+)",
    re.IGNORECASE,
)
_BASED = re.compile(
    r"\bbased in\s+([A-Z][A-Za-z .'-]{2,40})",
)
_AT_COMPANY = re.compile(
    r"\bat\s+([A-Z][\w&.'’+-]*(?:\s+[A-Z0-9][\w&.'’+-]*){0,5})"
)
_AT_SIGN = re.compile(
    r"@\s*([A-Z][\w&.'’+-]*(?:\s+[A-Z0-9][\w&.'’+-]*){0,4})"
)
_FOUNDER = re.compile(
    r"\b(?:Co-Founder|Cofounder|Founder|CEO|CTO|COO)\s+(?:at|of|@)?\s*"
    r"([A-Z][\w&.'’+-]*(?:\s+[A-Z0-9][\w&.'’+-]*){0,4})"
)
_YEARS_AT = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)\s+at\s+([A-Z][\w&.'’+-]*(?:\s+[A-Z0-9][\w&.'’+-]*){0,4})",
    re.IGNORECASE,
)
_AT_FOR_YEARS = re.compile(
    r"\bat\s+([A-Z][\w&.'’+-]*(?:\s+[A-Z0-9][\w&.'’+-]*){0,4})\s+for\s+(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)",
    re.IGNORECASE,
)
_DECADE = re.compile(r"\b(?:over\s+)?a decade of experience\b|\bover a decade\b", re.IGNORECASE)
_EXPLICIT_YEARS = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)(?:\s+of)?\s+(?:experience|exp\b)",
    re.IGNORECASE,
)
_YEARS_LEADING = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)\b(?:\s+(?:of|in|leading|building|working|with|across|specializing))?",
    re.IGNORECASE,
)
_LAST_YEARS = re.compile(
    r"\b(?:within|over|across)\s+the\s+last\s+(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)",
    re.IGNORECASE,
)
_DATE_RANGE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(20\d{2})"
    r"\s*[-–—to]+\s*(Present|Current|Now|20\d{2})",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_ROLE_NOUN = re.compile(
    r"\b(engineer|developer|manager|designer|analyst|scientist|recruiter|director|"
    r"lead|founder|officer|consultant|specialist|architect|partner|executive|"
    r"researcher|writer|nurse|accountant|lawyer|owner|head)\b",
    re.IGNORECASE,
)
_NOT_COMPANY_START = {
    "building",
    "creating",
    "leading",
    "helping",
    "delivering",
    "working",
    "focused",
    "focusing",
    "passionate",
    "experienced",
    "i",
    "we",
    "the",
    "a",
    "an",
    "view",
    "linkedin",
    "certified",
    "remote",
    "hybrid",
}


@dataclass
class Profile:
    name: str
    role: str
    location: str | None
    company: str | None
    tenure: str | None
    tenure_years: float | None
    experience: str | None
    experience_years: float | None
    skills: list[str]
    linkedin_url: str
    snippet: str
    headline: str


def canonical_profile_url(url: str) -> str | None:
    if not url:
        return None
    cleaned = decode_text(url)
    match = _PROFILE.search(cleaned)
    if not match:
        return None
    slug = unquote(match.group(1)).strip("/")
    slug = slug.split("/")[0]
    if not re.fullmatch(r"[\w.\-]{3,100}", slug, flags=re.UNICODE):
        return None
    if slug.lower() in _BLOCKED_SLUGS:
        return None
    from urllib.parse import quote

    return "https://www.linkedin.com/in/" + quote(slug, safe="-_.")


def parse_profile(title: str, url: str, snippet: str, today: date | None = None) -> Profile | None:
    profile_url = canonical_profile_url(url)
    if not profile_url:
        return None
    title = decode_text(title)
    snippet = decode_text(snippet)
    if _looks_like_directory(title):
        return None
    headline = _strip_linkedin_suffix(title)
    name = _pick_name(headline, snippet, profile_url)
    if not name:
        return None
    rest = _remove_name(headline, name)
    company = _company(rest, snippet)
    role = _role(rest, company)
    location = _location(snippet, name, headline)
    tenure_years, tenure_company = _company_tenure(snippet, today or date.today())
    if tenure_company and not company:
        company = tenure_company
    experience_years = _experience_years(snippet)
    if tenure_years is None and company:
        tenure_years = _tenure_at_company(snippet, company)
    skills = _skills(rest, snippet)
    return Profile(
        name=name,
        role=role or "Not stated",
        location=location,
        company=company,
        tenure=_format_years(tenure_years),
        tenure_years=tenure_years,
        experience=_format_years(experience_years),
        experience_years=experience_years,
        skills=skills,
        linkedin_url=profile_url,
        snippet=snippet[:700],
        headline=headline[:240],
    )


def _looks_like_directory(title: str) -> bool:
    return bool(
        re.search(r"\b\d+\+?\s+(?:people|profiles|professionals)\b", title, re.I)
        or re.match(r"\s*(?:top\s+\d+|best\s+)", title, re.I)
    )


def _strip_linkedin_suffix(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\s*[|\-–—]\s*LinkedIn.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+on LinkedIn$", "", title, flags=re.IGNORECASE)
    return title.strip(" -|")


def _pick_name(headline: str, snippet: str, profile_url: str) -> str | None:
    from_snippet = _name_from_snippet(snippet)
    from_title = _name_from_title(headline)
    from_url = _name_from_url(profile_url)
    for candidate in (from_snippet, from_title, from_url):
        if candidate and not _looks_like_username(candidate):
            return candidate
    return from_snippet or from_title or from_url


def _looks_like_username(name: str) -> bool:
    if not name:
        return True
    parts = name.split()
    if len(parts) == 1 and (re.search(r"\d", name) or len(name) > 16):
        return True
    if re.fullmatch(r"[a-z0-9._-]+", name.replace(" ", ""), flags=re.I):
        return True
    return False


def _name_from_title(headline: str) -> str | None:
    parts = re.split(r"\s+[-–—]\s+", headline, maxsplit=1)
    if len(parts) == 1:
        parts = re.split(r"\s+\|\s+", headline, maxsplit=1)
    if len(parts) < 2:
        return None
    candidate = _tidy_name(parts[0])
    if not candidate or _ROLE_NOUN.search(candidate):
        return None
    if len(candidate.split()) > 5:
        return None
    return candidate


def _name_from_snippet(snippet: str) -> str | None:
    match = _VIEW_NAME.search(snippet)
    if not match:
        return None
    name = _tidy_name(match.group(1))
    if not name or _ROLE_NOUN.search(name):
        return None
    return name


def _name_from_url(url: str) -> str | None:
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"-[0-9a-f]{5,}$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"-\d+$", "", slug)
    parts = [part for part in slug.split("-") if part and not part.isdigit()]
    if parts and re.fullmatch(r"[a-f0-9]{4,}", parts[-1]):
        parts = parts[:-1]
    if not 1 <= len(parts) <= 4:
        return None
    if len(parts) == 1 and len(parts[0]) > 18:
        return None
    return " ".join(part[:1].upper() + part[1:] for part in parts if part)


def _tidy_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" -|,")
    previous = None
    while previous != name:
        previous = name
        name = _CREDENTIAL.sub("", name).strip(" ,")
    if len(name) > 3 and name.isupper():
        name = name.title()
    return name


def _remove_name(headline: str, name: str) -> str:
    if headline.lower().startswith(name.lower()):
        rest = headline[len(name):]
        return re.sub(r"^[\s\-–—|:]+", "", rest).strip()
    return headline


def _company(headline: str, snippet: str) -> str | None:
    match = _EXPERIENCE_CO.search(snippet)
    if match:
        company = _clean_company(match.group(1))
        if company:
            return company
    match = _EXPERIENCE_AT.search(snippet)
    if match:
        company = _first_company(match.group(1))
        if company:
            return company
    for text in (headline, snippet):
        match = _ROLE_AT.search(text)
        if match:
            company = _clean_company(match.group(1))
            if company:
                return company
        for pattern in (_AT_SIGN, _FOUNDER, _AT_COMPANY):
            found = pattern.search(text)
            if not found:
                continue
            company = _clean_company(found.group(1))
            if company:
                return company
        match = re.search(
            r"\b(?:building|work(?:ing)?|led|leading)\b[^.]{0,80}?\bat\s+"
            r"([A-Z][\w&.'’+-]+(?:\s*(?:,|and)\s+[A-Z][\w&.'’+-]+){0,3})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            company = _first_company(match.group(1))
            if company:
                return company
    return None


def _first_company(raw: str) -> str | None:
    chunk = raw.split(",")[0]
    chunk = re.split(r"\s+and\s+", chunk, maxsplit=1)[0]
    return _clean_company(chunk.strip())


def _clean_company(raw: str) -> str | None:
    company = " ".join(raw.split()).strip(" .|,-–—")
    company = re.sub(r"\s+(?:and|in|for|with)$", "", company, flags=re.IGNORECASE)
    if not company or len(company) > 60 or len(company) < 2:
        return None
    first = company.split()[0].lower().strip(".,")
    if first in _NOT_COMPANY_START:
        return None
    if company.lower() in SKILL_DISPLAY or company.lower() in INDUSTRY_WORDS:
        return None
    if canonical_city(company):
        return None
    words = [word.strip(".,").lower() for word in company.split()]
    if len(words) == 1 and words[0] in DEPARTMENTS:
        return None
    if all(word in SKILL_DISPLAY or word in INDUSTRY_WORDS for word in words):
        return None
    if not re.search(r"[A-Za-z]", company):
        return None
    return company


def _role(headline_rest: str, company: str | None) -> str:
    text = headline_rest
    if company:
        text = re.sub(rf"\s+at\s+{re.escape(company)}\b", "", text, flags=re.IGNORECASE)
        text = re.sub(rf"\s*@\s*{re.escape(company)}\b", "", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{re.escape(company)}\b", "", text)
    segments = [segment.strip(" -|") for segment in re.split(r"\s+[|]\s+", text)]
    segments = [segment for segment in segments if segment and segment.lower() != "linkedin"]
    role_segments = [segment for segment in segments if _ROLE_NOUN.search(segment)]
    chosen = role_segments or segments
    role = " · ".join(chosen[:2])
    role = re.sub(r"\s+", " ", role).strip(" ·-")
    return role[:110]


def _location(snippet: str, name: str, headline: str = "") -> str | None:
    without_name = snippet.replace(name, " ")
    match = _LOCATION.search(without_name)
    if match:
        return _place_phrase(match.group(1))
    based = _BASED.search(without_name)
    if based:
        return _place_phrase(based.group(1))
    greater = re.search(r"\bGreater\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)", without_name)
    if greater:
        city = canonical_city(greater.group(1))
        if city:
            return city
    lowered = without_name.lower()
    for key in sorted(list(CITY_COUNTRY) + list(CITY_ALIASES), key=len, reverse=True):
        if not contains_term(lowered, key):
            continue
        city = canonical_city(key)
        if city and not _city_in_school_phrase(without_name, key):
            if not _city_is_person_or_past_office(f"{headline} {without_name}", name, key):
                return city
    return None


def _city_is_person_or_past_office(headline: str, name: str, city_key: str) -> bool:
    city = canonical_city(city_key) or city_key
    if re.search(rf"\b{re.escape(name.split()[-1])}\s+{re.escape(city)}\b", headline, re.I):
        return True
    if re.search(rf"\bEx-\w+\s+{re.escape(city)}\b", without := f"{headline} {name}", re.I):
        return True
    if len(name.split()) >= 2 and name.split()[-1].lower() == city.lower():
        return True
    return False


def _city_in_school_phrase(text: str, city_key: str) -> bool:
    pattern = re.compile(
        rf"\b{re.escape(city_key)}\s+(?:school|university|college|institute|area)\b",
        re.IGNORECASE,
    )
    return pattern.search(text.lower()) is not None


def _tenure_at_company(snippet: str, company: str) -> float | None:
    escaped = re.escape(company)
    match = re.search(
        rf"\b(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)\b[^.]{{0,120}}?\b{escaped}\b",
        snippet,
        flags=re.IGNORECASE,
    )
    if match:
        return float(match.group(1))
    match = re.search(
        rf"\b{escaped}\b[^.]{{0,120}}?\b(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)\b",
        snippet,
        flags=re.IGNORECASE,
    )
    if match:
        return float(match.group(1))
    return None


def _place_phrase(raw: str) -> str | None:
    raw = raw.strip(" .")
    # "London, England, United Kingdom" -> London. "London Area, United Kingdom" -> London.
    head = raw.split(",")[0].strip()
    head = re.sub(r"\s+Area$", "", head, flags=re.IGNORECASE)
    city = canonical_city(head)
    if city:
        return city
    if head and len(head) <= 40 and not head.lower().startswith("view "):
        return head
    return None


def _company_tenure(snippet: str, today: date) -> tuple[float | None, str | None]:
    match = _YEARS_AT.search(snippet)
    if match and _clean_company(match.group(2)):
        return float(match.group(1)), _clean_company(match.group(2))
    match = _AT_FOR_YEARS.search(snippet)
    if match and _clean_company(match.group(1)):
        return float(match.group(2)), _clean_company(match.group(1))
    range_match = _DATE_RANGE.search(snippet)
    if range_match:
        years = _span_years(range_match.group(1), int(range_match.group(2)), range_match.group(3), today)
        window = snippet[max(0, range_match.start() - 50): range_match.start()]
        company_match = re.search(r"([A-Z][\w&.'’+-]*(?:\s+[A-Z0-9][\w&.'’+-]*){0,3})\s*[·•|\-–—]*\s*$", window)
        company = _clean_company(company_match.group(1)) if company_match else None
        if company and years is not None:
            return years, company
    return None, None


def _span_years(month_name: str, start_year: int, end: str, today: date) -> float | None:
    month = _MONTHS.get(month_name[:3].lower())
    if not month:
        return None
    if end.lower() in {"present", "current", "now"}:
        end_year, end_month = today.year, today.month
    else:
        end_year, end_month = int(end), month
    years = (end_year - start_year) + (end_month - month) / 12
    if years < 0 or years > 50:
        return None
    return round(years, 1)


def _experience_years(snippet: str) -> float | None:
    if _DECADE.search(snippet):
        return 10.0
    for pattern in (_EXPLICIT_YEARS, _LAST_YEARS, _YEARS_LEADING):
        match = pattern.search(snippet)
        if match:
            years = float(match.group(1))
            if 0 < years <= 50:
                return years
    return None


def _skills(headline: str, snippet: str) -> list[str]:
    return find_skills(f"{headline} {snippet}")


def _format_years(years: float | None) -> str | None:
    if years is None:
        return None
    if years < 0.15:
        return "Less than a year"
    rounded = round(years)
    if abs(years - rounded) < 0.15:
        return "1 year" if rounded == 1 else f"{rounded} years"
    return f"{years:.1f} years"


def slug_of(url: str) -> str | None:
    canonical = canonical_profile_url(url)
    if not canonical:
        return None
    return urlparse(canonical).path.rstrip("/").split("/")[-1].lower()
