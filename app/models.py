import secrets
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_qr_token() -> str:
    """Случайный код для QR на упаковке: его нельзя подобрать перебором, в отличие от номера товара."""
    return secrets.token_hex(6)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Клиент пишет либо в Telegram, либо в Instagram Direct — заполнен один из ID
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    # Instagram-scoped ID (IGSID) — по нему отвечаем в Direct
    instagram_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(255))
    # Метка рекламной кампании из deep-link: t.me/bot?start=<utm>; клиенты из Instagram — «instagram»
    source: Mapped[str | None] = mapped_column(String(64), index=True)
    subscribed: Mapped[bool] = mapped_column(default=False)
    # Клиент заблокировал бота — рассылки ему не отправляются
    is_blocked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def __str__(self) -> str:
        return f"{self.full_name} (@{self.username})" if self.username else self.full_name


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # Куртки, шапки, обувь… — помогает AI подбирать похожие товары
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Артикул на Wildberries — по нему кнопка под рекомендацией ведёт на карточку товара
    wb_article: Mapped[int | None] = mapped_column(BigInteger)
    # Код в ссылке QR на упаковке: t.me/<bot>?start=q<код>
    qr_token: Mapped[str] = mapped_column(String(16), unique=True, default=new_qr_token)
    is_active: Mapped[bool] = mapped_column(default=True)

    def __str__(self) -> str:
        return self.name

    @property
    def wb_url(self) -> str | None:
        if self.wb_article is None:
            return None
        return f"https://www.wildberries.ru/catalog/{self.wb_article}/detail.aspx"


class Purchase(Base):
    """Покупка, подтверждённая сканированием QR-кода с упаковки товара."""

    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    # SET NULL — удаление товара из каталога не стирает историю покупок
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    client: Mapped[Client] = relationship(lazy="selectin")
    product: Mapped[Product | None] = relationship(lazy="selectin")


class Discount(Base):
    """Промокод Wildberries, созданный в кабинете продавца.

    Бот выдаёт покупателям самый новый активный промокод после сканирования QR.
    """

    __tablename__ = "discounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    percent: Mapped[int]
    # Заполнено — промокод действует только на этот товар (так настроено в кабинете WB)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    product: Mapped[Product | None] = relationship(lazy="selectin")

    def __str__(self) -> str:
        return f"{self.code} (−{self.percent}%)"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # Совпадает с Client.source — так считаем, сколько клиентов привела кампания
    utm: Mapped[str] = mapped_column(String(64), unique=True)
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Message(Base):
    """История диалога клиента с AI-менеджером."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    # user | assistant | event (служебное событие для AI, например «клиент отсканировал QR»)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)  # HTML-разметка Telegram
    # Если задано — только клиентам из этой рекламной кампании (Client.source)
    source: Mapped[str | None] = mapped_column(String(64))
    # Если задано — только этому клиенту (личное сообщение от магазина)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # scheduled → pending → sending → done; interrupted — старая незавершённая рассылка, не возобновляется
    # Время отправки в UTC; None — отправить сразу
    scheduled_at: Mapped[datetime | None] = mapped_column(index=True)
    sent_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    # ID последнего клиента, которому уже отправляли: с него рассылка продолжится после перезапуска
    last_client_id: Mapped[int] = mapped_column(default=0, server_default="0")
    # «Пульс» рассылки (UTC): обновляется с каждым сообщением. Давно не обновлялся — отправка оборвалась
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]

    client: Mapped[Client | None] = relationship(lazy="selectin")


class ChannelPost(Base):
    """Пост в Telegram-канал магазина. Текст пишет AI (или админ), публикует бот."""

    __tablename__ = "channel_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Задание для AI: «пост про скидки чёрной пятницы». Пусто — пост про товар или промокод ниже
    topic: Mapped[str] = mapped_column(Text, default="", server_default="")
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    discount_id: Mapped[int | None] = mapped_column(ForeignKey("discounts.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text, default="", server_default="")  # HTML-разметка Telegram
    # generating → draft → scheduled → publishing → published | failed
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # Время публикации в UTC; заполняется, когда пост поставлен в очередь
    scheduled_at: Mapped[datetime | None] = mapped_column(index=True)
    published_at: Mapped[datetime | None]
    # ID сообщения в канале — по нему пост можно найти в канале
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    # Копия поста в Instagram (только посты про товар: Instagram публикует лишь с фото)
    instagram_media_id: Mapped[str | None] = mapped_column(String(64))
    instagram_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    product: Mapped[Product | None] = relationship(lazy="selectin")
    discount: Mapped[Discount | None] = relationship(lazy="selectin")

    def __str__(self) -> str:
        return f"Пост #{self.id}"


class AppSetting(Base):
    """Значения, которые приложение меняет само (например, обновлённый токен Instagram)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
