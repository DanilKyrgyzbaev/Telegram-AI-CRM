"""Веб-админка CRM на SQLAdmin: /admin"""

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqladmin.filters import AllUniqueStringValuesFilter, BooleanFilter, OperationColumnFilter
from sqladmin.i18n import I18nConfig
from sqlalchemy import update
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import Broadcast, Campaign, ChannelPost, Client, Discount, Message, Product, Purchase
from app.services.broadcasts import format_local, local_tz, utcnow
from app.ai.posts import RUBRICS
from app.services.channel_posts import STATUS_LABELS, create_auto_post, start_generation
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
        Client.created_at: "Создан", Client.telegram_id: "Telegram ID", Client.instagram_id: "Instagram ID",
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

    async def after_model_change(self, data: dict, model: Product, is_created: bool, request: Request) -> None:
        # Новый товар — AI пишет пост о поступлении для канала
        if is_created and model.is_active:
            await create_auto_post(product_id=model.id)

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

    async def after_model_change(self, data: dict, model: Discount, is_created: bool, request: Request) -> None:
        # Новый промокод — AI пишет пост о скидке для канала (сам код в пост не попадает)
        if is_created and model.is_active:
            await create_auto_post(discount_id=model.id)


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
        Broadcast.id, Broadcast.text, "audience", Broadcast.status,
        Broadcast.scheduled_at, Broadcast.sent_count, Broadcast.failed_count, Broadcast.finished_at,
    ]
    column_labels = {
        Broadcast.text: "Текст (HTML)", Broadcast.source: "Кампания (метка)",
        Broadcast.client: "Только клиенту", "audience": "Кому",
        Broadcast.status: "Статус", Broadcast.scheduled_at: "Отправка",
        Broadcast.sent_count: "Доставлено", Broadcast.failed_count: "Ошибок",
        Broadcast.finished_at: "Завершена",
    }
    column_default_sort = (Broadcast.id, True)
    column_formatters = {
        Broadcast.text: lambda m, a: m.text if len(m.text) <= 80 else m.text[:80] + "…",
        "audience": lambda m, a: _audience(m),
        Broadcast.scheduled_at: lambda m, a: _local(m, "scheduled_at"),
        Broadcast.finished_at: lambda m, a: _local(m, "finished_at"),
    }
    form_columns = [Broadcast.text, Broadcast.client, Broadcast.source, Broadcast.scheduled_at]
    # Поиск клиента по имени или @username, а не выпадающий список из всех клиентов
    form_ajax_refs = {"client": {"fields": ("full_name", "username"), "order_by": "id"}}
    form_args = {
        "client": {"description": "Заполните, чтобы написать одному клиенту. Пусто — рассылка по аудитории ниже."},
        "source": {
            "description": "Пусто — всем клиентам. Иначе — только тем, кто пришёл по ссылке с этой меткой "
            "(t.me/бот?start=метка; покупатели по QR — метка qr). Это не подпись и не имя клиента."
        },
        "scheduled_at": {
            "description": f"Время в часовом поясе {get_settings().timezone}. Пусто — отправить сразу."
        },
    }
    form_widget_args = {"text": {"rows": 6}}
    # Запущенную рассылку уже не изменить
    can_edit = False

    async def on_model_change(self, data: dict, model: Broadcast, is_created: bool, request: Request) -> None:
        # Пробелы вокруг метки («  qr ») не должны превращать рассылку в отправку «никому»
        data["source"] = (data.get("source") or "").strip() or None
        # Все рассылки из админки отправляет планировщик бота (в пределах 30 секунд)
        scheduled_at: datetime | None = data.get("scheduled_at")
        if scheduled_at is None:
            data["scheduled_at"] = utcnow()
        else:
            data["scheduled_at"] = scheduled_at.replace(tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)
        model.status = "scheduled"


def _audience(broadcast: Broadcast) -> str:
    if broadcast.client:
        return f"👤 {broadcast.client}"
    if broadcast.source:
        return f"метка «{broadcast.source}»"
    return "все клиенты"


class ChannelPostAdmin(ModelView, model=ChannelPost):
    name = "Пост"
    name_plural = "Посты и сторис"
    icon = "fa-solid fa-newspaper"
    column_list = [
        ChannelPost.id, ChannelPost.kind, ChannelPost.status, "about", ChannelPost.text,
        ChannelPost.scheduled_at, ChannelPost.published_at,
    ]
    column_labels = {
        ChannelPost.topic: "Задание для AI", ChannelPost.product: "Товар", ChannelPost.discount: "Промокод",
        ChannelPost.text: "Текст поста (HTML)", ChannelPost.status: "Статус", "about": "О чём",
        ChannelPost.scheduled_at: "Публикация", ChannelPost.published_at: "Опубликован",
        ChannelPost.error: "Ошибка", ChannelPost.message_id: "ID сообщения в канале",
        ChannelPost.instagram_media_id: "ID поста в Instagram", ChannelPost.instagram_error: "Ошибка Instagram",
        ChannelPost.kind: "Тип", ChannelPost.rubric: "Рубрика", ChannelPost.planned_at: "По плану",
    }
    column_default_sort = (ChannelPost.id, True)
    column_formatters = {
        ChannelPost.status: lambda m, a: STATUS_LABELS.get(m.status, m.status),
        ChannelPost.kind: lambda m, a: "📱 сторис" if m.kind == "story" else "📝 пост",
        "about": lambda m, a: (f"📅 {RUBRICS[m.rubric][0]}: {m.product}" if m.rubric in RUBRICS else None) or m.topic or (f"🆕 {m.product}" if m.product else f"🎁 {m.discount.code}" if m.discount else "—"),
        ChannelPost.text: lambda m, a: m.text if len(m.text) <= 100 else m.text[:100] + "…",
        ChannelPost.scheduled_at: lambda m, a: _local(m, "scheduled_at"),
        ChannelPost.published_at: lambda m, a: _local(m, "published_at"),
    }
    column_details_list = [
        ChannelPost.id, ChannelPost.kind, ChannelPost.rubric, ChannelPost.status, ChannelPost.topic,
        ChannelPost.product, ChannelPost.discount, ChannelPost.planned_at,
        ChannelPost.text, ChannelPost.scheduled_at, ChannelPost.published_at, ChannelPost.message_id, ChannelPost.error,
        ChannelPost.instagram_media_id, ChannelPost.instagram_error,
    ]
    column_formatters_detail = {
        ChannelPost.status: column_formatters[ChannelPost.status],
        ChannelPost.scheduled_at: column_formatters[ChannelPost.scheduled_at],
        ChannelPost.published_at: column_formatters[ChannelPost.published_at],
    }
    form_columns = [ChannelPost.topic, ChannelPost.product, ChannelPost.text, ChannelPost.scheduled_at]
    form_args = {
        "topic": {
            "description": "Что написать, например: «скидки чёрной пятницы на тёплые брюки». "
            "Текст поста оставьте пустым — AI напишет его и пришлёт вам в Telegram."
        },
        "product": {"description": "Необязательно. Под постом появится кнопка на этот товар на WB."},
        "text": {"description": "Пусто — напишет AI. Можно поправить готовый текст перед публикацией."},
        "scheduled_at": {
            "description": f"Время в часовом поясе {get_settings().timezone}. "
            "Пусто — пост останется черновиком, опубликуйте кнопкой «Опубликовать сейчас»."
        },
    }
    form_widget_args = {"topic": {"rows": 2}, "text": {"rows": 10}}

    async def on_model_change(self, data: dict, model: ChannelPost, is_created: bool, request: Request) -> None:
        if model.status in ("publishing", "published"):
            raise ValueError("Опубликованный пост уже не изменить: правки в канал не попадут.")
        data["text"] = (data.get("text") or "").strip()
        if scheduled_at := data.get("scheduled_at"):
            data["scheduled_at"] = scheduled_at.replace(tzinfo=local_tz()).astimezone(timezone.utc).replace(tzinfo=None)
        if not data["text"]:
            model.status = "generating"
        else:
            model.status = "scheduled" if data.get("scheduled_at") else "draft"

    async def after_model_change(self, data: dict, model: ChannelPost, is_created: bool, request: Request) -> None:
        if model.status == "generating":
            start_generation(model.id)

    async def _set_status(
        self, request: Request, values: dict, statuses: tuple[str, ...]
    ) -> tuple[RedirectResponse, list[int]]:
        """Меняет статус выбранных постов (только тех, что в одном из statuses) и возвращает их ID."""
        ids = [int(pk) for pk in request.query_params.get("pks", "").split(",") if pk]
        async with SessionLocal() as session:
            changed = (
                await session.scalars(
                    update(ChannelPost)
                    .where(ChannelPost.id.in_(ids), ChannelPost.status.in_(statuses))
                    .values(**values)
                    .returning(ChannelPost.id)
                )
            ).all()
            await session.commit()
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302), changed

    @action(name="publish", label="📢 Опубликовать сейчас", confirmation_message="Опубликовать выбранные посты в канал?")
    async def publish_now(self, request: Request) -> RedirectResponse:
        # Публикует планировщик бота в течение 30 секунд; итог придёт админам в Telegram
        response, _ = await self._set_status(
            request, {"status": "scheduled", "scheduled_at": utcnow()}, ("draft", "failed", "scheduled")
        )
        return response

    @action(name="rewrite", label="🔄 Переписать с AI")
    async def rewrite(self, request: Request) -> RedirectResponse:
        response, changed = await self._set_status(request, {"status": "generating"}, ("draft", "failed"))
        for post_id in changed:
            start_generation(post_id)
        return response


def setup_admin(app: FastAPI) -> None:
    admin = Admin(
        app,
        engine,
        title=f"{get_settings().shop_name or 'Telegram AI'} CRM",
        # Картинки бренда отдаёт сайт (app/site); меню админки тёмное — логотип светлый
        logo_url="/logo-light.png",
        logo_width=150,
        logo_height=56,
        favicon_url="/favicon.png?v=2",
        authentication_backend=AdminAuth(secret_key=get_settings().secret_key),
        i18n_config=I18nConfig(default_locale="ru"),
    )
    for view in (
        ClientAdmin, MessageAdmin, PurchaseAdmin, ProductAdmin,
        DiscountAdmin, CampaignAdmin, BroadcastAdmin, ChannelPostAdmin,
    ):
        admin.add_view(view)
