from fastapi import Depends, FastAPI

from app.admin import setup_admin
from app.api.deps import require_api_key
from app.api.routers import broadcasts, clients, products, promo, stats

app = FastAPI(title="Telegram AI CRM")
setup_admin(app)

for router in (clients.router, products.router, stats.router, broadcasts.router, promo.router):
    app.include_router(router, prefix="/api", dependencies=[Depends(require_api_key)])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
