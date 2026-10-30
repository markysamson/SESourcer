"""Run one sourcing pass: read the role, search, parse, score, keep the best."""

from __future__ import annotations

from sesourcer.jd import JobBrief, build_queries, parse_job
from sesourcer.profiles import parse_profile
from sesourcer.score import score_profile
from sesourcer.search import gather

_SOURCE_NOTE = (
    "Details come from public search snippets of LinkedIn profile pages. "
    "This app does not open LinkedIn or try to get around its blocks. "
    "Tenure, location, and company are filled in only when that snippet states them."
)


def run_search(job_text: str, notes: str, limit: int, page_title: str | None = None) -> dict:
    brief = parse_job(job_text, page_title=page_title, notes=notes or "")
    queries = build_queries(brief, limit)
    hits, warnings = gather(queries, limit)
    scored = []
    for hit in hits:
        profile = parse_profile(hit.title, hit.url, hit.snippet)
        if profile is None:
            continue
        scored.append(score_profile(profile, brief))
    scored.sort(key=lambda item: (-item.score, item.profile.name.lower()))
    chosen = scored[:limit]
    limited = any(
        "rate-limit" in warning.lower() or "wait a minute" in warning.lower()
        for warning in warnings
    )
    if len(chosen) < limit and limited:
        warnings.append(
            f"Showing {len(chosen)} of {limit} requested. "
            "The public index stopped returning profile pages before the list was full."
        )
    elif len(chosen) < limit:
        warnings.append(
            f"Found {len(chosen)} public profiles for this search. "
            f"{limit} were requested."
        )
    return {
        "brief": _brief_dict(brief),
        "queries": queries,
        "candidates": [_candidate_dict(item) for item in chosen],
        "requested": limit,
        "returned": len(chosen),
        "pool_size": len(scored),
        "warnings": _unique(warnings),
        "source_note": _SOURCE_NOTE,
    }


def _brief_dict(brief: JobBrief) -> dict:
    return {
        "title": brief.title,
        "seniority": brief.seniority,
        "locations": brief.locations,
        "countries": brief.countries,
        "remote": brief.remote,
        "hybrid": brief.hybrid,
        "must_have": brief.must_have,
        "nice_to_have": brief.nice_to_have,
        "years_experience": brief.years_experience,
        "note_terms": brief.note_terms,
    }


def _candidate_dict(item) -> dict:
    profile = item.profile
    skills = _display_skills(profile.skills, item.matched_skills)
    return {
        "name": profile.name,
        "role": profile.role or "Not stated",
        "location": profile.location or "Not stated",
        "company": profile.company or "Not stated",
        "tenure": profile.tenure or profile.experience or "Not stated",
        "experience": profile.experience,
        "skills": skills,
        "linkedin_url": profile.linkedin_url,
        "score": item.score,
        "band": item.band,
        "rationale": item.rationale,
        "matched_skills": item.matched_skills,
        "missing_skills": item.missing_skills,
        "snippet": profile.snippet,
        "breakdown": item.breakdown,
    }


def _display_skills(profile_skills: list[str], matched: list[str]) -> list[str]:
    ordered: list[str] = []
    for skill in matched + profile_skills:
        if skill not in ordered:
            ordered.append(skill)
    return ordered[:8]


def _unique(warnings: list[str]) -> list[str]:
    seen: list[str] = []
    for warning in warnings:
        if warning and warning not in seen:
            seen.append(warning)
    return seen
