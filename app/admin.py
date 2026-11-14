"""Веб-админка CRM на SQLAdmin: /admin"""

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqladmin.filters import AllUniqueStringValuesFilter, BooleanFilter, OperationColumnFilter
from sqladmin.i18n import I18nConfig
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import Broadcast, Campaign, Client, Discount, Message, Product, Purchase
from app.services.broadcasts import format_local, local_tz, utcnow
from app.services.promo import promo_status
from app.services.qr import product_link, qr_png


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        settings = get_settings()
        # Пустой пароль в .env — вход запрещён, чтобы админка не оказалась открытой
        if not settings.admin_password:
            return False
        ok = secrets.compare_digest(str(form.get("username", "")), settings.admin_username) and secrets.compare_digest(
            str(form.get("password", "")), settings.admin_password
        )
        if ok:
            request.session["admin"] = True
        return ok

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin"))


def _local(model: Any, attr: str) -> str:
    """Форматтер колонки: время из базы (UTC) → часовой пояс админа."""
    value = getattr(model, attr)
    return format_local(value) if value else "—"


class ClientAdmin(ModelView, model=Client):
    name = "Клиент"
    name_plural = "Клиенты"
    icon = "fa-solid fa-users"
    column_list = [
        Client.id, Client.full_name, Client.username, Client.source,
        Client.subscribed, Client.is_blocked, Client.created_at,
    ]
    column_labels = {
        Client.full_name: "Имя", Client.username: "Username", Client.source: "Источник",
        Client.subscribed: "Подписан", Client.is_blocked: "Заблокировал бота",
        Client.created_at: "Создан", Client.telegram_id: "Telegram ID",
    }
    column_searchable_list = [Client.full_name, Client.username, Client.telegram_id]
    column_filters = [
        AllUniqueStringValuesFilter(Client.source, title="Источник"),
        BooleanFilter(Client.subscribed, title="Подписан"),
        BooleanFilter(Client.is_blocked, title="Заблокировал бота"),
    ]
    column_sortable_list = [Client.id, Client.created_at]
    column_default_sort = (Client.id, True)
    column_formatters = {Client.created_at: lambda m, a: _local(m, "created_at")}
    # Клиенты появляются из бота, вручную их не создаём
    can_create = False
    can_export = True


class ProductAdmin(ModelView, model=Product):
    name = "Товар"
    name_plural = "Товары"
    icon = "fa-solid fa-box"
    column_list = [Product.id, Product.name, Product.category, Product.price, Product.wb_article, Product.is_active]
    column_labels = {
        Product.name: "Название", Product.category: "Категория", Product.description: "Описание",
        Product.price: "Цена", Product.wb_article: "Артикул WB", Product.is_active: "В продаже",
    }
    column_searchable_list = [Product.name, Product.wb_article]
    column_filters = [
        AllUniqueStringValuesFilter(Product.category, title="Категория"),
        BooleanFilter(Product.is_active, title="В продаже"),
    ]
    column_sortable_list = [Product.id, Product.name, Product.category, Product.price]
    form_columns = [
        Product.name, Product.category, Product.price, Product.wb_article, Product.description, Product.is_active,
    ]
    form_args = {
        "wb_article": {"description": "Артикул на Wildberries — под рекомендациями AI появится кнопка на этот товар."},
        "category": {"description": "Например: куртки, шапки, обувь. По категориям AI подбирает похожие товары."},
        "description": {"description": "Материал, цвет, с чем сочетается — AI использует это в рекомендациях."},
    }
    form_widget_args = {"description": {"rows": 5}}

    @action(name="qr", label="Скачать QR для упаковки", add_in_list=False)
    async def download_qr(self, request: Request) -> Response:
        product_id = int(request.query_params["pks"].split(",")[0])
        async with SessionLocal() as session:
            product = await session.get(Product, product_id)
        if product is None:
            return Response("Товар не найден", status_code=404)
        return Response(
            qr_png(await product_link(product.qr_token)),
            media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="qr-product-{product_id}.png"'},
        )


class PurchaseAdmin(ModelView, model=Purchase):
    name = "Покупка"
    name_plural = "Покупки (QR)"
    icon = "fa-solid fa-qrcode"
    column_list = [Purchase.id, Purchase.client, Purchase.product, Purchase.created_at]
    column_labels = {Purchase.client: "Клиент", Purchase.product: "Товар", Purchase.created_at: "Сканирование"}
    column_filters = [OperationColumnFilter(Purchase.product_id, title="ID товара")]
    column_default_sort = (Purchase.id, True)
    column_formatters = {Purchase.created_at: lambda m, a: _local(m, "created_at")}
    # Покупки появляются только при сканировании QR
    can_create = False
    can_edit = False
    can_export = True


class DiscountAdmin(ModelView, model=Discount):
    name = "Промокод WB"
    name_plural = "Промокоды WB"
    icon = "fa-solid fa-percent"
    column_list = [
        Discount.id, Discount.code, Discount.percent, Discount.product, "status",
        Discount.expires_at, Discount.created_at,
    ]
    column_labels = {
        Discount.code: "Промокод", Discount.percent: "Скидка, %", Discount.product: "Только на товар",
        Discount.is_active: "Включён", "status": "Статус",
        Discount.expires_at: "Действует до", Discount.created_at: "Добавлен",
    }
    column_searchable_list = [Discount.code]
    column_default_sort = (Discount.id, True)
    column_formatters = {
        "status": lambda m, a: promo_status(m),
        Discount.expires_at: lambda m, a: _local(m, "expires_at"),
        Discount.created_at: lambda m, a: _local(m, "created_at"),
    }
    column_formatters_detail = column_formatters
    form_columns = [Discount.code, Discount.percent, Discount.product, Discount.expires_at, Discount.is_active]
    form_args = {
        "code": {
            "description": "Создайте промокод в кабинете продавца Wildberries и впишите его сюда. "
            "Бот выдаёт покупателям после сканирования QR самый новый включённый промокод."
        },
        "product": {"description": "Заполните, если в кабинете WB промокод действует только на один товар."},
        "expires_at": {"description": f"Время в часовом поясе {get_settings().timezone}. Пусто — бессрочно."},
    }

    async def on_model_change(self, data: dict, model: Discount, is_created: bool, request: Request) -> None:
        data["code"] = data["code"].strip().upper()
        if expires_at := data.get("expires_at"):
            data["expires_at"] = expires_at.replace(tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)


class CampaignAdmin(ModelView, model=Campaign):
    name = "Кампания"
    name_plural = "Рекламные кампании"
    icon = "fa-solid fa-bullhorn"
    column_list = [Campaign.id, Campaign.name, Campaign.utm, Campaign.budget, Campaign.created_at]
    column_labels = {
        Campaign.name: "Название", Campaign.utm: "Метка (start=)",
        Campaign.budget: "Бюджет", Campaign.created_at: "Создана",
    }
    column_formatters = {Campaign.created_at: lambda m, a: _local(m, "created_at")}
    form_excluded_columns = [Campaign.created_at]


class MessageAdmin(ModelView, model=Message):
    name = "Сообщение"
    name_plural = "Диалоги с AI"
    icon = "fa-solid fa-comments"
    column_list = [Message.id, Message.client_id, Message.role, Message.text, Message.created_at]
    column_labels = {
        Message.client_id: "ID клиента", Message.role: "Кто",
        Message.text: "Текст", Message.created_at: "Время",
    }
    column_searchable_list = [Message.text]
    column_filters = [
        OperationColumnFilter(Message.client_id, title="ID клиента"),
        AllUniqueStringValuesFilter(Message.role, title="Кто"),
    ]
    column_default_sort = (Message.id, True)
    column_formatters = {
        Message.role: lambda m, a: {"user": "Клиент", "assistant": "AI", "event": "Событие"}.get(m.role, m.role),
        Message.text: lambda m, a: m.text if len(m.text) <= 120 else m.text[:120] + "…",
        Message.created_at: lambda m, a: _local(m, "created_at"),
    }
    # История переписки только для чтения
    can_create = False
    can_edit = False
    can_export = True


class BroadcastAdmin(ModelView, model=Broadcast):
    name = "Рассылка"
    name_plural = "Рассылки"
    icon = "fa-solid fa-paper-plane"
    column_list = [
        Broadcast.id, Broadcast.text, Broadcast.source, Broadcast.status,
        Broadcast.scheduled_at, Broadcast.sent_count, Broadcast.failed_count, Broadcast.finished_at,
    ]
    column_labels = {
        Broadcast.text: "Текст (HTML)", Broadcast.source: "Кампания (метка)",
        Broadcast.status: "Статус", Broadcast.scheduled_at: "Отправка",
        Broadcast.sent_count: "Доставлено", Broadcast.failed_count: "Ошибок",
        Broadcast.finished_at: "Завершена",
    }
    column_default_sort = (Broadcast.id, True)
    column_formatters = {
        Broadcast.text: lambda m, a: m.text if len(m.text) <= 80 else m.text[:80] + "…",
        Broadcast.scheduled_at: lambda m, a: _local(m, "scheduled_at"),
        Broadcast.finished_at: lambda m, a: _local(m, "finished_at"),
    }
    form_columns = [Broadcast.text, Broadcast.source, Broadcast.scheduled_at]
    form_args = {
        "source": {"description": "Пусто — всем клиентам. Иначе — только клиентам с этой меткой кампании."},
        "scheduled_at": {
            "description": f"Время в часовом поясе {get_settings().timezone}. Пусто — отправить сразу."
        },
    }
    form_widget_args = {"text": {"rows": 6}}
    # Запущенную рассылку уже не изменить
    can_edit = False

    async def on_model_change(self, data: dict, model: Broadcast, is_created: bool, request: Request) -> None:
        # Все рассылки из админки отправляет планировщик бота (в пределах 30 секунд)
        scheduled_at: datetime | None = data.get("scheduled_at")
        if scheduled_at is None:
            data["scheduled_at"] = utcnow()
        else:
            data["scheduled_at"] = scheduled_at.replace(tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)
        model.status = "scheduled"


def setup_admin(app: FastAPI) -> None:
    admin = Admin(
        app,
        engine,
        title="Telegram AI CRM",
        authentication_backend=AdminAuth(secret_key=get_settings().secret_key),
        i18n_config=I18nConfig(default_locale="ru"),
    )
    for view in (
        ClientAdmin, MessageAdmin, PurchaseAdmin, ProductAdmin,
        DiscountAdmin, CampaignAdmin, BroadcastAdmin,
    ):
        admin.add_view(view)
