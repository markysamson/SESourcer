"""HTTP API and the recruiter page."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sesourcer.fetch import FetchError, fetch_job_text
from sesourcer.pipeline import run_search
from sesourcer.search import SearchError

_STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="SESourcer", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


class SearchIn(BaseModel):
    job_url: str | None = None
    job_text: str | None = None
    notes: str | None = None
    limit: int = Field(default=20, ge=1, le=50)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.post("/api/search")
def search(body: SearchIn) -> dict:
    job_text = (body.job_text or "").strip()
    job_url = (body.job_url or "").strip()
    notes = (body.notes or "").strip()
    if not job_text and not job_url:
        raise HTTPException(status_code=400, detail="Paste a job description or provide a link to one.")
    if len(job_text) > 50000:
        raise HTTPException(status_code=400, detail="The job description is too long.")
    if len(notes) > 5000:
        raise HTTPException(status_code=400, detail="The notes are too long.")

    warnings: list[str] = []
    page_title = None
    if job_text:
        text = job_text
        if job_url:
            warnings.append("Using the pasted description. The link was not fetched.")
    else:
        try:
            page_title, text = fetch_job_text(job_url)
        except FetchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if len(text) < 80:
            warnings.append(
                "The page returned very little text. Paste the job description if the shortlist looks off."
            )

    try:
        result = run_search(text, notes, body.limit, page_title=page_title)
    except SearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result["warnings"] = warnings + result["warnings"]
    return result
