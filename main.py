import asyncio
import socket
import logging
from aiohttp import web, TCPConnector
from aiogram import Bot, Dispatcher

from app.database import init_db, get_payment_by_label, add_subscription, update_payment_status
from app.handlers import router
from app.admin_panel import admin_router
from app.config import BOT_TOKEN
from app.payments import check_pending_payments_task
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def activate_subscription(user_id, label, server, days):
    """Активирует подписку пользователя"""
    try:
        from app.database import get_user_subscription, delete_subscription

        # Удаляем старую подписку если есть
        existing_sub = get_user_subscription(user_id)
        if existing_sub:
            delete_subscription(user_id)
            logger.info(f"🗑️ Удалена старая подписка для user_id={user_id}")

        # Активируем подписку
        start_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        add_subscription(user_id, server, start_date, end_date)
        update_payment_status(label, "success")

        # Уведомляем пользователя
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            user_id,
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"Ваша подписка на сервере {server} активирована.\n"
            f"📅 Доступен до: {end_date}\n\n"
            f"Нажмите 'Показать купленный сервер' для получения конфигурации.",
            parse_mode="HTML"
        )

        logger.info(f"🎉 Подписка активирована для user_id={user_id}, сервер: {server}, дней: {days}")

    except Exception as e:
        logger.error(f"❌ Ошибка активации подписки: {e}")


async def cancel_subscription(user_id):
    """Отменяет подписку пользователя"""
    try:
        from app.database import delete_subscription
        delete_subscription(user_id)
        logger.info(f"Подписка отменена для user_id={user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отмены подписки: {e}")


# --- Обработчик вебхуков от ЮKassa ---
async def handle_yookassa_webhook(request: web.Request):
    """
    Этот endpoint будет принимать уведомления от ЮKassa
    """
    try:
        # ЮKassa отправляет JSON
        data = await request.json()
        logger.info("🔄 Пришёл webhook от ЮKassa: %s", data)

        # Валидация обязательных полей
        if not data.get('event') or not data.get('object'):
            logger.warning("⚠️ Невалидный webhook от ЮKassa: отсутствуют обязательные поля")
            return web.Response(text="OK", status=200)

        event = data.get('event')
        payment_object = data.get('object')

        if event == 'payment.waiting_for_capture':
            # Платеж ожидает подтверждения
            payment_id = payment_object.get('id')
            logger.info(f"⏳ Платеж ожидает подтверждения: {payment_id}")

        elif event == 'payment.succeeded':
            # Платеж прошел успешно!
            payment_id = payment_object.get('id')
            amount = payment_object.get('amount', {}).get('value')
            metadata = payment_object.get('metadata', {})
            user_id = metadata.get('user_id')

            logger.info(f"✅ Платеж успешен: {payment_id} для user_id={user_id}, сумма: {amount}")

            # Ищем платеж в базе
            label = f"yk_{payment_id}"
            payment_data = get_payment_by_label(label)

            if payment_data and payment_data['status'] == "pending":
                user_id_db = payment_data['user_id']
                server = payment_data['server']
                days = payment_data['days']

                await activate_subscription(user_id_db, label, server, days)
            else:
                logger.warning(f"⚠️ Платеж не найден в базе или уже обработан: {label}")

        elif event == 'payment.canceled':
            # Платеж отменен
            payment_id = payment_object.get('id')
            metadata = payment_object.get('metadata', {})
            user_id = metadata.get('user_id')

            logger.info(f"❌ Платеж отменен: {payment_id} для user_id={user_id}")

            label = f"yk_{payment_id}"
            update_payment_status(label, "failed")

            # Уведомляем пользователя об отмене
            if user_id:
                try:
                    bot = Bot(token=BOT_TOKEN)
                    await bot.send_message(
                        user_id,
                        "❌ <b>Платеж отменен</b>\n\n"
                        "Ваш платеж был отменен. Если это ошибка, попробуйте оплатить снова.",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось уведомить пользователя: {e}")

        elif event == 'refund.succeeded':
            # Возврат средств
            payment_id = payment_object.get('id')
            logger.info(f"↩️ Возврат средств: {payment_id}")

            # Отменяем подписку если она активна
            metadata = payment_object.get('metadata', {})
            user_id = metadata.get('user_id')
            if user_id:
                await cancel_subscription(user_id)

        else:
            logger.info(f"ℹ️ Необрабатываемое событие от ЮKassa: {event}")

        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике webhook ЮKassa: {e}")
        return web.Response(text="OK", status=200)


# --- Обработчик для ЮMoney (резерв) ---
async def handle_yoomoney_webhook(request: web.Request):
    """
    Резервный endpoint для уведомлений от ЮMoney
    """
    try:
        data = await request.post()
        logger.info("🔄 Пришёл callback от ЮMoney: %s", dict(data))

        notification_type = data.get('notification_type')
        label = data.get('label')

        if notification_type == 'p2p-incoming':
            payment_data = get_payment_by_label(label)
            if payment_data and payment_data['status'] == "pending":
                user_id = payment_data['user_id']
                server = payment_data['server']
                days = payment_data['days']
                await activate_subscription(user_id, label, server, days)
            else:
                logger.warning(f"⚠️ Платеж ЮMoney не найден в базе: {label}")

        return web.Response(text="OK")

    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике ЮMoney: {e}")
        return web.Response(text="OK")


# --- aiohttp сервер ---
async def start_web_server():
    app = web.Application()

    # Webhook для ЮKassa (основной)
    app.router.add_post("/yookassa", handle_yookassa_webhook)

    # Webhook для ЮMoney (резервный)
    app.router.add_post("/yoomoney", handle_yoomoney_webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    # 🟢 слушаем на всех интерфейсах и правильном порту (8080)
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    logger.info("🌐 Web-сервер запущен на порту 8080")
    logger.info("📝 Webhook URLs:")
    logger.info("   - ЮKassa: https://vbkvpn.online/yookassa")
    logger.info("   - ЮMoney: https://vbkvpn.online/yoomoney")


# --- Telegram бот ---
async def start_bot():
    connector = TCPConnector(family=socket.AF_INET)
    bot = Bot(token=BOT_TOKEN, connector=connector)
    dp = Dispatcher()

    dp.include_router(router)
    dp.include_router(admin_router)

    logger.info("🤖 Бот запущен и ждёт сообщения...")
    await dp.start_polling(bot)


# --- Главная точка входа ---
async def main():
    try:
        # Инициализация и проверка базы данных
        from app.database import check_and_fix_database
        init_db()
        check_and_fix_database()
        logger.info("✅ База данных инициализирована и проверена")

        # Запускаем проверку платежей в фоне как асинхронную задачу
        payment_checker_task = asyncio.create_task(check_pending_payments_task())

        await asyncio.gather(
            start_bot(),
            start_web_server()
        )
    except KeyboardInterrupt:
        logger.info("🛑 Выключение бота...")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    finally:
        logger.info("🔚 Бот завершил работу")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот выключен пользователем")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка: {e}")
