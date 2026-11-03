import json
import os
from datetime import date, timedelta
from pathlib import Path


def write_status(status, message, **extra):
    out = Path("exposure_output")
    out.mkdir(exist_ok=True)
    payload = {"status": status, "message": message, **extra}
    (out / "google-performance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / "growth-plan.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\n## Google performance data\n")
        handle.write(f"- Status: {status}\n- {message}\n")
        for key, value in extra.items():
            handle.write(f"- {key}: {value}\n")


def main():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    gsc_site = os.environ.get("GSC_SITE_URL", "").strip()
    ga4_property = os.environ.get("GA4_PROPERTY_ID", "").strip()
    missing = [
        name for name, value in (
            ("GOOGLE_SERVICE_ACCOUNT_JSON", raw),
            ("GSC_SITE_URL", gsc_site),
            ("GA4_PROPERTY_ID", ga4_property),
        ) if not value
    ]
    if missing:
        write_status(
            "not_connected",
            "Google APIs were not queried because required GitHub Actions secrets/variables are missing.",
            missing_configuration=", ".join(missing),
            setup="Add GOOGLE_SERVICE_ACCOUNT_JSON as a repository secret; add GSC_SITE_URL and GA4_PROPERTY_ID as repository variables or secrets. Grant the service-account email access to both properties."
        )
        print("Google performance integration not connected; generated setup status.")
        return

    import google.auth
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from google.analytics.data import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest
    )

    info = json.loads(raw)
    scopes = [
        "https://www.googleapis.com/auth/webmasters.readonly",
        "https://www.googleapis.com/auth/analytics.readonly",
    ]
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=scopes
    )

    # Search Console: stop three days before today to avoid incomplete daily data.
    end_day = date.today() - timedelta(days=3)
    start_day = end_day - timedelta(days=27)
    gsc = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
    search_rows = gsc.searchanalytics().query(
        siteUrl=gsc_site,
        body={
            "startDate": start_day.isoformat(),
            "endDate": end_day.isoformat(),
            "dimensions": ["page"],
            "rowLimit": 1000,
            "type": "web",
        },
    ).execute().get("rows", [])

    query_rows = gsc.searchanalytics().query(
        siteUrl=gsc_site,
        body={
            "startDate": start_day.isoformat(),
            "endDate": end_day.isoformat(),
            "dimensions": ["query"],
            "rowLimit": 1000,
            "type": "web",
        },
    ).execute().get("rows", [])

    # GA4 Data API: aggregate landing-page sessions for the last 28 complete days.
    analytics = BetaAnalyticsDataClient(credentials=credentials)
    request = RunReportRequest(
        property=f"properties/{ga4_property}",
        date_ranges=[DateRange(start_date="28daysAgo", end_date="yesterday")],
        dimensions=[Dimension(name="landingPagePlusQueryString")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="engagedSessions"),
            Metric(name="screenPageViews"),
            Metric(name="engagementRate"),
        ],
        limit=1000,
    )
    ga_response = analytics.run_report(request)
    ga_rows = []
    for row in ga_response.rows:
        ga_rows.append({
            "landing_page": row.dimension_values[0].value,
            "sessions": row.metric_values[0].value,
            "users": row.metric_values[1].value,
            "engaged_sessions": row.metric_values[2].value,
            "pageviews": row.metric_values[3].value,
            "engagement_rate": row.metric_values[4].value,
        })

    gsc_pages = [{
        "page": row.get("keys", [""])[0],
        "clicks": row.get("clicks", 0),
        "impressions": row.get("impressions", 0),
        "ctr": row.get("ctr", 0),
        "average_position": row.get("position", 0),
    } for row in search_rows]
    gsc_queries = [{
        "query": row.get("keys", [""])[0],
        "clicks": row.get("clicks", 0),
        "impressions": row.get("impressions", 0),
        "ctr": row.get("ctr", 0),
        "average_position": row.get("position", 0),
    } for row in query_rows]

    result = {
        "status": "connected",
        "period": {
            "search_console_start": start_day.isoformat(),
            "search_console_end": end_day.isoformat(),
            "ga4": "last 28 complete days",
        },
        "search_console": {
            "pages_returned": len(gsc_pages),
            "total_clicks": sum(x["clicks"] for x in gsc_pages),
            "total_impressions": sum(x["impressions"] for x in gsc_pages),
            "top_pages": sorted(gsc_pages, key=lambda x: x["clicks"], reverse=True)[:25],
            "top_queries": sorted(gsc_queries, key=lambda x: x["clicks"], reverse=True)[:25],
        },
        "ga4": {
            "landing_pages_returned": len(ga_rows),
            "sessions": sum(int(x["sessions"]) for x in ga_rows),
            "users": sum(int(x["users"]) for x in ga_rows),
            "engaged_sessions": sum(int(x["engaged_sessions"]) for x in ga_rows),
            "pageviews": sum(int(x["pageviews"]) for x in ga_rows),
            "top_landing_pages": sorted(ga_rows, key=lambda x: int(x["sessions"]), reverse=True)[:25],
        },
    }
    out = Path("exposure_output")
    out.mkdir(exist_ok=True)
    (out / "google-performance.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / "growth-plan.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\n## Google Search Console and GA4 — last 28 days\n")
        handle.write(f"- Search Console clicks: {result['search_console']['total_clicks']}\n")
        handle.write(f"- Search Console impressions: {result['search_console']['total_impressions']}\n")
        handle.write(f"- GA4 sessions: {result['ga4']['sessions']}\n")
        handle.write(f"- GA4 users: {result['ga4']['users']}\n")
        handle.write(f"- GA4 engaged sessions: {result['ga4']['engaged_sessions']}\n")
        handle.write(f"- GA4 pageviews: {result['ga4']['pageviews']}\n")
        handle.write("- Top landing pages and search queries are in google-performance.json.\n")
    print("Google Search Console and GA4 performance report generated.")


if __name__ == "__main__":
    main()
