import secrets

from fastapi import Header, HTTPException

from app.config import get_settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().admin_api_key
    # compare_digest — сравнение за постоянное время, чтобы ключ нельзя было подобрать по задержке ответа
    if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")
