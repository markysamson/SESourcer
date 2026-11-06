# SESourcer

SESourcer reads a job description and builds a scored shortlist of people whose public LinkedIn profile pages already appear in web search results.

Give it a job link or pasted text, optional notes, and how many people you want (default 20, maximum 50). For each person it shows the name, role, location, current company, tenure at that company, relevant skills, a profile link, and a 0–100 fit score.

## How search works

LinkedIn blocks automated reads of its site. This app does not log in, open profile pages, solve checks, or rotate proxies to get around that. It searches public web indexes (DuckDuckGo, then Bing if DuckDuckGo rate-limits the request) for `linkedin.com/in` pages those indexes have already listed, and it reads the title and snippet on the result page.

Tenure, location, and company are filled in only when that snippet states them. Otherwise the shortlist says **Not stated**. Scores use the same text, so a thin snippet scores lower on skills it never mentions.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m sesourcer
```

Open http://127.0.0.1:8000

## API

`POST /api/search`

```json
{
  "job_url": "https://example.com/jobs/123",
  "job_text": "",
  "notes": "Prefer people who have worked at a UK bank.",
  "limit": 20
}
```

Provide `job_text`, `job_url`, or both. When both are set, the pasted text is used. `limit` defaults to 20.

Job links must be public `http` or `https` pages. Private addresses and LinkedIn URLs are refused; paste the description instead.

## Tests

```bash
python -m pytest
```
