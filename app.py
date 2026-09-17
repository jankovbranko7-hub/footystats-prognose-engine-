"""Render entry point: legacy compatibility + final FULL7 contract engine."""
import app_v040 as legacy
from fastapi.responses import HTMLResponse
from spec11_joint_core_patch import apply_patch
from full7_homepage_patch import apply_full7_homepage
from full7_dev_api import router as full7_router
from full7_contract_api import production_router as full7_final_router

app = apply_patch(legacy)
apply_full7_homepage(legacy)
app.include_router(full7_router)
app.include_router(full7_final_router)

NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

app.router.routes = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/"
        and "GET" in (getattr(route, "methods", None) or set())
    )
]


@app.get("/", include_in_schema=False)
def index():
    html = legacy.INDEX_HTML
    if "http-equiv=\"Cache-Control\"" not in html:
        html = html.replace(
            "<head>",
            "<head><meta http-equiv=\"Cache-Control\" content=\"no-store, no-cache, must-revalidate\"><meta http-equiv=\"Pragma\" content=\"no-cache\"><meta http-equiv=\"Expires\" content=\"0\">",
            1,
        )
    if "full7Build" not in html:
        html = html.replace(
            "<h2>FULL-7 Contract</h2>",
            "<h2>FULL-7 Contract</h2><p class=\"s\" id=\"full7Build\">Build 20260917-1608 | Safari-Cache aus</p>",
            1,
        )
    return HTMLResponse(html, headers=NO_CACHE)
