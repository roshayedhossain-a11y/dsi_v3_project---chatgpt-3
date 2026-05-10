# DSI V4 Final ICP Job Scraper

This is the stricter replacement for the failed V3/V4 attempt.

It produces **one artifact file only**:

`output/FINAL_USE_THIS_ONLY_YYYY-MM-DD.csv`

No rejected CSV. No needs-verification CSV. No secondary CSV. No source report artifact.

## What changed

- Strict ICP only.
- No `B_USE_IF_NEED_MORE_VOLUME` confusion.
- Unknown headcount is rejected.
- Unknown location is rejected.
- `Remote` alone is rejected.
- `Remote (North America)` is rejected.
- Regional remote roles are rejected.
- WeWorkRemotely is not blindly treated as worldwide.
- Job board rows only pass if company metadata proves DSI ICP.
- 404, 403, and 429 are handled quietly and skipped.
- Sources are validated by whether they return real jobs.
- Artifact upload includes only the final file.

## Strict row requirements

A row appears only if it passes all of these:

- Company headcount bucket is 10 to 50, 51 to 100, or 101 to 200
- Company market is English comfortable first world or global SaaS/product
- Job is a core engineering/developer role
- Job is fresh, 30 days or newer
- Remote worldwide is proven by location or full description
- No country restriction is found
- No work authorization restriction is found
- Not hybrid, not onsite
- Not agency, recruiter, anonymous, or staffing firm
- No duplicate role for the same company
- Score is 80 or higher

## Why the result may still be under 500

500 strict daily rows from free public data is not guaranteed. If the public market does not expose 500 strict matches today, the script will not fake them.

To scale, add more verified 10 to 200 headcount remote-first companies in `sources.yml`.

## How to upload to GitHub

1. Create or open your GitHub repo.
2. Upload these files:
   - `dsi_scraper_v4.py`
   - `sources.yml`
   - `requirements.txt`
   - `.github/workflows/daily_scrape.yml`
3. Go to **Actions**.
4. Run **DSI V4 Final ICP Job Scrape** manually.
5. Download the artifact named `FINAL_USE_THIS_ONLY_<run_id>`.
6. Use only the CSV inside it.

## How to add more real sources

Open `sources.yml` and add companies under `type: company_career`.

Example:

```yaml
- name: Career Discovery Example SaaS
  type: company_career
  enabled: true
  trust_score: 9
  source_type_label: official_company_career_discovery
  company_name: Example SaaS
  company_domain: example.com
  company_website: https://example.com
  career_url: https://example.com/careers
  delay_seconds: 0.4
  company_meta:
    company_name: Example SaaS
    company_domain: example.com
    company_website: https://example.com
    headcount_bucket: 51 to 100
    headcount_estimate: 51 to 100
    hq_country: United States
    company_type: B2B SaaS
    target_market_fit: yes
```

The code will open the career page, discover Greenhouse, Lever, or Ashby links, then collect jobs from the official ATS.

## Run locally

```bash
pip install -r requirements.txt
python dsi_scraper_v4.py --self-test
python dsi_scraper_v4.py
```
