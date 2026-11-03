import json
import os
from datetime import date, timedelta
from pathlib import Path

GROWTH_PLAN = Path("exposure_output") / "valuted-news-growth-plan.md"

def write_status(status, message, **extra):
    out = Path("exposure_output")
    out.mkdir(exist_ok=True)
    payload = {"status": status, "message": message, **extra}
    (out / "google-performance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with GROWTH_PLAN.open("a", encoding="utf-8") as handle:
        handle.write("\n\n## Google Search Console — organic search only\n")
        handle.write(f"- Status: {status}\n- {message}\n")
        for key, value in extra.items():
            handle.write(f"- {key}: {value}\n")

def main():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    site = os.environ.get("GSC_SITE_URL", "").strip()
    missing = [name for name, value in (
        ("GOOGLE_SERVICE_ACCOUNT_JSON", raw), ("GSC_SITE_URL", site)
    ) if not value]
    if missing:
        write_status(
            "not_connected",
            "Search Console was not queried because its connection settings are missing.",
            missing_configuration=", ".join(missing),
            setup="Add GOOGLE_SERVICE_ACCOUNT_JSON as a repository secret and GSC_SITE_URL as a repository variable. Grant the service-account email read-only access to this site's Search Console property. No visitor analytics or tracking code is used."
        )
        print("Google Search Console is not connected; setup status generated.")
        return

    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(raw)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    end_day = date.today() - timedelta(days=3)
    start_day = end_day - timedelta(days=27)
    gsc = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
    def query(dimension):
        response = gsc.searchanalytics().query(
            siteUrl=site,
            body={"startDate": start_day.isoformat(), "endDate": end_day.isoformat(),
                  "dimensions": [dimension], "rowLimit": 1000, "type": "web"}
        ).execute()
        return response.get("rows", [])
    page_rows, query_rows = query("page"), query("query")
    pages = [{"page": r.get("keys", [""])[0], "clicks": r.get("clicks", 0),
              "impressions": r.get("impressions", 0), "ctr": r.get("ctr", 0),
              "average_position": r.get("position", 0)} for r in page_rows]
    queries = [{"query": r.get("keys", [""])[0], "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0), "ctr": r.get("ctr", 0),
                "average_position": r.get("position", 0)} for r in query_rows]
    result = {
        "status": "connected",
        "source": "Google Search Console API only; no GA4, visitor tracking, analytics tags, or tracking pixels",
        "period": {"start": start_day.isoformat(), "end": end_day.isoformat()},
        "search_console": {
            "pages_returned": len(pages),
            "total_clicks": sum(x["clicks"] for x in pages),
            "total_impressions": sum(x["impressions"] for x in pages),
            "top_pages": sorted(pages, key=lambda x: x["clicks"], reverse=True)[:25],
            "top_queries": sorted(queries, key=lambda x: x["clicks"], reverse=True)[:25]
        }
    }
    out = Path("exposure_output")
    out.mkdir(exist_ok=True)
    (out / "google-performance.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with GROWTH_PLAN.open("a", encoding="utf-8") as handle:
        handle.write("\n\n## Google Search Console — last 28 complete days\n")
        handle.write(f"- Organic search clicks: {result['search_console']['total_clicks']}\n")
        handle.write(f"- Organic search impressions: {result['search_console']['total_impressions']}\n")
        handle.write("- Top pages and search queries: google-performance.json\n")
    print("Google Search Console organic-search report generated.")

if __name__ == "__main__":
    main()
