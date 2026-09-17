"""Render entry point: FULL-7 V2 homepage + contract engine."""
import app_v040 as legacy
from fastapi.responses import HTMLResponse
from spec11_joint_core_patch import apply_patch
from full7_v2_homepage import apply_v2_homepage
from full7_dev_api import router as full7_router
from full7_contract_api import production_router as full7_final_router

app = apply_patch(legacy)
apply_v2_homepage(legacy)
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
    return HTMLResponse(legacy.INDEX_HTML, headers=NO_CACHE)
