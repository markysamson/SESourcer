"""Read a job description the way a recruiter skims it: title, level, place, skills."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sesourcer.lexicon import (
    ALTERNATE_TITLES,
    CITY_ALIASES,
    CITY_COUNTRY,
    FUNCTIONS,
    NOTE_STOP,
    SENIORITY_RANK,
    canonical_city,
    canonical_country,
    contains_term,
    find_skills,
)

_MUST_HEADINGS = {
    "requirements",
    "required",
    "required qualifications",
    "requirements and qualifications",
    "what you'll need",
    "what you’ll need",
    "what you will need",
    "what we're looking for",
    "what we’re looking for",
    "what we are looking for",
    "qualifications",
    "skills",
    "must have",
    "must-have",
    "about the role",
    "the role",
    "your experience",
    "minimum qualifications",
    "basic qualifications",
}

_NICE_HEADINGS = {
    "nice to have",
    "nice-to-have",
    "preferred",
    "preferred qualifications",
    "bonus",
    "bonus points",
    "plus",
    "good to have",
    "nice to haves",
}

_IGNORE_HEADINGS = {
    "about us",
    "about the company",
    "who we are",
    "benefits",
    "perks",
    "what we offer",
    "how to apply",
    "equal opportunity",
    "our values",
    "why join",
    "why us",
    "compensation",
    "salary",
}

_RESPONSIBILITY_HEADINGS = {
    "responsibilities",
    "what you'll do",
    "what you’ll do",
    "what you will do",
    "the work",
    "in this role",
}

_TITLE_LABEL = re.compile(
    r"^(?:job title|role|position|title)\s*[:\-–]\s*(.+)$",
    re.IGNORECASE,
)
_YEARS = re.compile(r"(\d+)\s*\+?\s*(?:years|yrs)\b", re.IGNORECASE)
_BULLET = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
_LEAD_IN = re.compile(
    r"^(?:strong|proven|excellent|solid|hands[- ]on|deep|good|demonstrable|demonstrated)\s+",
    re.IGNORECASE,
)
_EXPERIENCE_LEAD = re.compile(
    r"^(?:experience (?:with|in|of)|proficient in|knowledge of|skilled in|familiar with|"
    r"expertise in|background in|understanding of)\s+",
    re.IGNORECASE,
)
_FILLER = {"with", "using", "across", "including", "for", "within", "into", "over", "via", "through"}


@dataclass
class JobBrief:
    title: str
    function: str | None
    seniority: str | None
    seniority_rank: int | None
    locations: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    remote: bool = False
    hybrid: bool = False
    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    years_experience: int | None = None
    alternate_titles: list[str] = field(default_factory=list)
    note_terms: list[str] = field(default_factory=list)
    title_source: str = "description"


def parse_job(text: str, page_title: str | None = None, notes: str = "") -> JobBrief:
    body = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    sections = _split_sections(body)
    title, source = _extract_title(sections["preamble"], body, page_title)
    function = _function_in(title)
    seniority = _seniority_word(title) or _seniority_word(sections["preamble"][:400])
    locations, countries = _locations(sections["preamble"] or body[:1500])
    remote, hybrid = _workplace(sections["preamble"] or body[:1500])
    must_source = sections["must"] or sections["preamble"] or sections["responsibilities"]
    nice_source = sections["nice"]
    if not sections["must"] and sections["responsibilities"] and sections["preamble"]:
        must_source = sections["preamble"] + "\n" + sections["responsibilities"]
    must = _skills_from(must_source, title, function)
    nice = [skill for skill in _skills_from(nice_source, title, function) if skill not in must]
    if len(must) > 8:
        overflow = must[8:]
        must = must[:8]
        for skill in overflow:
            if skill not in nice:
                nice.append(skill)
    years = _years(sections["must"] or must_source)
    alternates = list(ALTERNATE_TITLES.get(function or "", ()))
    return JobBrief(
        title=title,
        function=function,
        seniority=seniority,
        seniority_rank=SENIORITY_RANK.get(seniority) if seniority else None,
        locations=locations,
        countries=countries,
        remote=remote,
        hybrid=hybrid,
        must_have=must,
        nice_to_have=nice[:6],
        years_experience=years,
        alternate_titles=alternates,
        note_terms=note_terms(notes),
        title_source=source,
    )


def note_terms(notes: str) -> list[str]:
    """Phrases from the recruiter's extra notes that should influence search and score."""
    if not notes or not notes.strip():
        return []
    found: list[str] = []

    def add(term: str) -> None:
        cleaned = " ".join(term.split()).strip(" .,:;\"'")
        if len(cleaned) < 3 or cleaned.lower() in NOTE_STOP:
            return
        if any(cleaned.lower() == item.lower() for item in found):
            return
        found.append(cleaned)

    for phrase in re.findall(r'"([^"]{2,60})"', notes):
        add(phrase)
    for phrase in re.findall(r"\b(?:at|from|ex-)\s+([A-Z][\w&.'’-]+(?:\s+[A-Z][\w&.'’-]+){0,3})", notes):
        add(phrase)
    for skill in find_skills(notes):
        add(skill)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{3,}", notes):
        if word.lower() in NOTE_STOP:
            continue
        add(word)
        if len(found) >= 8:
            break
    return found[:8]


def build_queries(brief: JobBrief, limit: int) -> list[str]:
    """Queries tuned for public indexes (unquoted terms; seniority is scored, not searched)."""
    role = _index_role(brief)
    place = brief.locations[0] if brief.locations else (brief.countries[0] if brief.countries else "")
    if brief.remote and not brief.locations:
        place = "Remote"
    skills = _index_skills(_query_skills(brief))
    queries: list[str] = []

    def add(*parts: str) -> None:
        query = " ".join(part for part in parts if part and part.strip())
        query = " ".join(query.split())
        if query.count(" ") >= 2 and query not in queries:
            queries.append(query)

    # Public indexes work best with role + one skill + place (not several skills at once).
    for skill in skills[:4]:
        add("site:linkedin.com/in", role, skill, place)
    add("site:linkedin.com/in", role, place)
    for alternate in brief.alternate_titles[:2]:
        for skill in skills[:2] or [""]:
            add("site:linkedin.com/in", alternate, skill, place)
    if brief.note_terms:
        add("site:linkedin.com/in", role, brief.note_terms[0], place)
    if brief.seniority and brief.function:
        add("site:linkedin.com/in", f"{brief.seniority} {brief.function}", skills[0] if skills else "", place)

    return queries[: _query_budget(limit)]


def build_rescue_queries(brief: JobBrief) -> list[str]:
    """Broader queries when stricter ones return nothing."""
    role = _index_role(brief)
    place = brief.locations[0] if brief.locations else ""
    skills = _index_skills(brief.must_have)
    queries: list[str] = []
    for skill in skills[:3]:
        query = " ".join(p for p in ("site:linkedin.com/in", role, skill, place) if p)
        if query.count(" ") >= 2 and query not in queries:
            queries.append(query)
    for parts in (
        ("site:linkedin.com/in", role, "Python", place),
        ("site:linkedin.com/in", role, "SQL", place),
        ("site:linkedin.com/in", "software engineer", "Python", place),
    ):
        query = " ".join(p for p in parts if p)
        if query not in queries and query.count(" ") >= 2:
            queries.append(query)
    return queries[:4]


_INDEX_SKILL_PRIORITY = (
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "sql",
    "postgresql",
    "aws",
    "kubernetes",
    "docker",
    "node.js",
    "golang",
    "rust",
    "payments",
    "fintech",
)


def _index_skills(skills: list[str]) -> list[str]:
    """Order skills for search queries (indexes tolerate some tokens better than others)."""
    if not skills:
        return []

    def rank(skill: str) -> tuple[int, int]:
        lowered = skill.lower()
        try:
            priority = _INDEX_SKILL_PRIORITY.index(lowered)
        except ValueError:
            priority = len(_INDEX_SKILL_PRIORITY)
        return (priority, len(skill.split()))

    return sorted(skills, key=rank)


_GENERIC_QUERY_SKILLS = {
    "stakeholder management",
    "agile",
    "scrum",
    "kanban",
    "roadmapping",
    "product management",
    "project management",
    "jira",
    "excel",
    "communication",
    "leadership",
    "teamwork",
}


def _search_title(brief: JobBrief) -> str:
    """A title people actually put on a profile, without the extra clause after a comma."""
    if brief.function:
        title = brief.function
        if brief.seniority and brief.seniority not in title:
            title = f"{brief.seniority} {title}"
        return title
    return brief.title.split(",")[0].strip()


def _index_role(brief: JobBrief) -> str:
    """Role phrase for search indexes — function only, no seniority prefix."""
    if brief.function:
        return brief.function
    title = brief.title.split(",")[0].strip()
    if brief.seniority:
        title = re.sub(rf"^{re.escape(brief.seniority)}\s+", "", title, flags=re.I)
    return title.strip() or brief.title.split(",")[0].strip()


def _query_skills(brief: JobBrief) -> list[str]:
    specific = [skill for skill in brief.must_have if skill.lower() not in _GENERIC_QUERY_SKILLS]
    generic = [skill for skill in brief.must_have if skill.lower() in _GENERIC_QUERY_SKILLS]

    def rank(skill: str) -> tuple[int, int]:
        in_title = 0 if skill.lower() in brief.title.lower() else 1
        return (in_title, brief.must_have.index(skill))

    specific.sort(key=rank)
    return (specific + generic)[:4]


def _query_budget(limit: int) -> int:
    if limit >= 15:
        return 6
    if limit >= 8:
        return 4
    return 3


def _split_sections(text: str) -> dict[str, str]:
    buckets = {"preamble": [], "must": [], "nice": [], "responsibilities": [], "ignore": []}
    current = "preamble"
    for line in text.splitlines():
        kind = _heading_kind(line)
        if kind:
            current = kind
            continue
        buckets[current].append(line)
    return {key: "\n".join(value).strip() for key, value in buckets.items()}


def _heading_kind(line: str) -> str | None:
    raw = line.strip()
    if not raw or len(raw) > 60:
        return None
    if raw.endswith("."):
        return None
    key = raw.rstrip(":").strip().lower()
    key = re.sub(r"\s+", " ", key)
    if key in _MUST_HEADINGS:
        return "must"
    if key in _NICE_HEADINGS:
        return "nice"
    if key in _IGNORE_HEADINGS:
        return "ignore"
    if key in _RESPONSIBILITY_HEADINGS:
        return "responsibilities"
    return None


def _extract_title(preamble: str, body: str, page_title: str | None) -> tuple[str, str]:
    for line in _lines(preamble or body):
        match = _TITLE_LABEL.match(line)
        if match and _looks_like_title(match.group(1)):
            return _tidy_title(match.group(1)), "label"
    for line in _lines(preamble or body)[:8]:
        if _looks_like_title(line) and not _looks_like_location_line(line):
            return _tidy_title(line), "description"
    cleaned_page = _clean_page_title(page_title or "")
    if cleaned_page and _looks_like_title(cleaned_page):
        return cleaned_page, "page title"
    first = next(iter(_lines(body)), "")
    if first:
        return _tidy_title(first)[:90], "first line"
    return "Untitled role", "fallback"


def _clean_page_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.split(r"\s+[|\-–—]\s+", title)[0].strip()
    return title


def _tidy_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -|")
    title = re.sub(r"\s*[|\-–—]\s*(?:hybrid|remote|full[- ]time|part[- ]time)\s*$", "", title, flags=re.I)
    return title[:90].strip()


def _looks_like_title(line: str) -> bool:
    if not line or len(line) > 90 or len(line) < 4:
        return False
    if line.endswith("."):
        return False
    lowered = line.lower()
    if lowered.startswith(("http://", "https://", "about ", "we are ", "we're ", "join ")):
        return False
    return _function_in(line) is not None or _seniority_word(line) is not None and any(
        noun in lowered for noun in ("engineer", "manager", "designer", "analyst", "lead", "director")
    )


def _looks_like_location_line(line: str) -> bool:
    lowered = line.lower()
    if "remote" in lowered and len(line) < 40:
        return True
    cities, countries = _locations(line)
    words = line.replace(",", " ").split()
    return bool(cities or countries) and len(words) <= 6


def _function_in(title: str) -> str | None:
    lowered = title.lower()
    for function in FUNCTIONS:
        if contains_term(lowered, function):
            return function
    return None


def _seniority_word(text: str) -> str | None:
    for word in (
        "intern",
        "trainee",
        "junior",
        "jr",
        "associate",
        "senior",
        "sr",
        "staff",
        "principal",
        "lead",
        "director",
        "head",
        "vp",
        "chief",
    ):
        if contains_term(text, word):
            if word == "sr":
                return "senior"
            if word == "jr":
                return "junior"
            return word
    return None


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _locations(text: str) -> tuple[list[str], list[str]]:
    cities: list[str] = []
    countries: list[str] = []

    def add_city(raw: str) -> None:
        city = canonical_city(raw)
        if city and city not in cities:
            cities.append(city)

    def add_country(raw: str) -> None:
        country = canonical_country(raw)
        if country and country not in countries:
            countries.append(country)

    labeled = re.search(
        r"(?:location|based in|office)\s*[:\-]\s*([^\n]{2,80})",
        text,
        re.IGNORECASE,
    )
    if labeled:
        _scan_place(labeled.group(1), add_city, add_country, short_aliases=True)
    # The opening lines are where postings put the office. Later paragraphs
    # mention customers and other offices that are not the job's location.
    for line in text.splitlines()[:12]:
        _scan_place(line, add_city, add_country, short_aliases=len(line) <= 48)
    return cities[:2], countries[:1]


def _scan_place(text: str, add_city, add_country, short_aliases: bool) -> None:
    lowered = text.lower()
    for key in sorted(list(CITY_COUNTRY) + list(CITY_ALIASES), key=len, reverse=True):
        if contains_term(lowered, key):
            city = canonical_city(key)
            if city:
                add_city(city)
    for key in ("united kingdom", "united states", "great britain", "u.k.", "u.s.", "the netherlands", "netherlands"):
        if contains_term(lowered, key):
            add_country(key)
    if short_aliases:
        for key in ("uk", "usa", "uae"):
            if contains_term(lowered, key):
                add_country(key)


def _workplace(text: str) -> tuple[bool, bool]:
    header = "\n".join(text.splitlines()[:20])
    remote = bool(re.search(r"\bremote\b|\bwork from home\b|\bwork from anywhere\b", header, re.I))
    hybrid = bool(re.search(r"\bhybrid\b", header, re.I))
    return remote, hybrid


def _years(text: str) -> int | None:
    match = _YEARS.search(text)
    if not match:
        return None
    years = int(match.group(1))
    if years > 40:
        return None
    return years


def _skills_from(text: str, title: str, function: str | None) -> list[str]:
    if not text:
        return []
    found: list[str] = []

    def add(term: str) -> None:
        cleaned = " ".join(term.split()).strip(" .;:")
        cleaned = cleaned.strip("\"'")
        if not cleaned or len(cleaned) > 40:
            return
        if cleaned.lower() in NOTE_STOP:
            return
        if function and cleaned.lower() == function:
            return
        if _is_function_skill(cleaned, function):
            return
        if title and cleaned.lower() in title.lower() and len(cleaned.split()) >= 2:
            return
        if any(cleaned.lower() == item.lower() for item in found):
            return
        found.append(cleaned)

    for skill in find_skills(text):
        add(skill)
    for line in text.splitlines():
        if not _BULLET.match(line):
            continue
        phrase = _BULLET.sub("", line).strip()
        if _YEARS.search(phrase) and len(phrase.split()) <= 8:
            continue
        phrase = _EXPERIENCE_LEAD.sub("", phrase)
        phrase = _LEAD_IN.sub("", phrase)
        pieces = re.split(r",|\band\b|\bor\b", phrase)
        for piece in pieces:
            piece = piece.strip(" -")
            piece = re.sub(
                r"\s+(?:experience|skills|background|knowledge|exposure)$",
                "",
                piece,
                flags=re.IGNORECASE,
            )
            embedded = find_skills(piece)
            if embedded:
                for skill in embedded:
                    add(skill)
                continue
            words = piece.split()
            if not words or len(words) > 3:
                continue
            if words[0].lower() in {"a", "an", "the", "to", "our", "their"}:
                continue
            if any(word.lower() in _FILLER or word.lower() in {"institution", "environment", "team", "teams"} for word in words):
                continue
            add(piece)
    return found


def _is_function_skill(term: str, function: str | None) -> bool:
    if not function:
        return False
    lowered = term.lower()
    if lowered == function:
        return True
    head = function.split()[0]
    return lowered in {f"{head} management", f"{head} development", f"{head} design"}
