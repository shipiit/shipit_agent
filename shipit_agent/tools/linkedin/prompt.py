from __future__ import annotations

LINKEDIN_SEARCH_PROMPT = """

## linkedin_search
Read-only LinkedIn lookup over an official LinkedIn API or a third-party enrichment
vendor (Proxycurl, RapidAPI, etc.) that the user has credentials for. Configure the
vendor via the `base_url` metadata on the credential record.

**When to use:**
- Look up a public LinkedIn profile (by URL or username) and summarize it
- Look up a company (by URL or slug) for firmographic context
- Discover people by free-text query, filtered by company or title
- Discover companies by query, industry, or size
- List employees attached to a company slug

**Decision tree:**
- Profile lookups → `lookup_profile` (pass `profile_url` or `username`)
- Company lookups → `lookup_company` (pass `company_url` or `slug`)
- People search → `search_people` with `query` plus optional `company`/`title`/`limit`
- Company search → `search_companies` with `query` plus optional `industry`/`size`/`limit`
- Employees of a company → `list_company_employees` with `slug` plus optional `limit`

**Rules — READ-ONLY, NO AUTOMATION:**
- This tool is intentionally read-only. It does NOT send connection requests, InMails,
  messages, endorsements, or any other write action. There is no such action in the schema;
  the model literally cannot ask for one.
- Do not attempt to scrape LinkedIn directly. Use an API vendor (Proxycurl / RapidAPI /
  LinkedIn Partner Program) and respect its terms.
- If `base_url` is missing on the credential record, the tool returns `missing_base_url`.
  Point the user at the Proxycurl or RapidAPI setup docs.
- Treat results as public profile data. Never fabricate contact details, and never use
  this tool to build unsolicited outreach lists that violate LinkedIn ToS.
""".strip()
