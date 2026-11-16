import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers import broadcast, channel, chat, posts, start
from app.bot.middlewares.db import DbSessionMiddleware
from app.config import get_settings
from app.services.scheduler import run_scheduler


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(get_settings().bot_token)
    dp = Dispatcher()
    dp.update.middleware(DbSessionMiddleware())
    # Порядок важен: команды раньше общего текстового хендлера AI-менеджера
    dp.include_routers(start.router, broadcast.router, posts.router, channel.router, chat.router)

    # Отложенные рассылки (и созданные в боте, и через API) отправляет процесс бота
    scheduler = asyncio.create_task(run_scheduler(bot))
    try:
        # chat_member (подписки на канал) Telegram присылает, только если запросить явно
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.cancel()


if __name__ == "__main__":
    asyncio.run(main())
