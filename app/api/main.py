from fastapi import Depends, FastAPI

from app.admin import setup_admin
from app.api import public
from app.api.deps import require_api_key
from app.api.routers import broadcasts, clients, products, promo, stats
from app.instagram import webhook as instagram_webhook
from app.site import router as site_router

app = FastAPI(title="Telegram AI CRM")
setup_admin(app)

for router in (clients.router, products.router, stats.router, broadcasts.router, promo.router):
    app.include_router(router, prefix="/api", dependencies=[Depends(require_api_key)])

# Без ключа API: Meta сама обращается к webhook и скачивает фото
app.include_router(public.router)
app.include_router(instagram_webhook.router)
# Сайт для покупателей: каталог, карточки товаров, политика конфиденциальности
app.include_router(site_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
