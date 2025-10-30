import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
from app.v2ray_config import generate_v2ray_config
from app.payments import create_payment_link
from app.database import add_user, save_payment_label, get_user_subscription, add_subscription, delete_subscription
from app.keyboards import (
    get_main_inline_keyboard,
    get_welcome_inline_keyboard,
    get_subscription_inline_keyboard,
    get_servers_inline_keyboard
)

logger = logging.getLogger(__name__)
router = Router()


class BuyFlow(StatesGroup):
    choosing_duration = State()
    choosing_server = State()


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    user_id = message.from_user.id

    # Добавляем/обновляем пользователя
    is_new_user = add_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        reg_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    if is_new_user:
        # ТОЛЬКО НОВЫЕ пользователи получают тестовый период
        start_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

        # Создаем тестовую подписку
        add_subscription(user_id, "🇩🇪 Германия", start_date, end_date)

        await message.answer(
            "🎉 <b>Добро пожаловать! Вам активирован БЕСПЛАТНЫЙ тестовый период на 3 дня!</b>\n\n"
            "🌐 <b>Доступен сервер:</b> 🇩🇪 Германия\n"
            "⏰ <b>Срок действия:</b> 3 дня\n"
            "📅 <b>Активен до:</b> " + end_date + "\n\n"
                                                 "Нажмите кнопку ниже чтобы получить конфигурацию VPN 🔥",
            parse_mode="HTML",
            reply_markup=get_welcome_inline_keyboard()
        )

        logger.info(f"🎁 Выдан тестовый период НОВОМУ пользователю {user_id}")
    else:
        # СУЩЕСТВУЮЩИЕ пользователи получают обычное меню
        # Проверяем есть ли активная подписка
        existing_sub = get_user_subscription(user_id)

        if existing_sub:
            # Есть активная подписка
            await message.answer(
                "Рады снова видеть тебя 🌍\n 🔒Управляй своим VPN легко — просто выбери нужный пункт ниже",
                parse_mode="HTML",
                reply_markup=get_main_inline_keyboard(),
                disable_web_page_preview=True
            )
        else:
            # Нет активной подписки - предлагаем купить
            await message.answer(
                "С возвращением! ❤️\n\n"
                "К сожалению, ваш тестовый период закончился.\n"
                "Приобретите подписку для продолжения использования VPN 🔥",
                parse_mode="HTML",
                reply_markup=get_main_inline_keyboard(),
                disable_web_page_preview=True
            )


@router.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 С возвращением! Нажмите кнопку ниже для управления VPN",
        reply_markup=get_main_inline_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "buy_access")
async def buy_access_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BuyFlow.choosing_duration)
    await callback.message.edit_text(
        "Выберите срок подписки:",
        reply_markup=get_subscription_inline_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sub_"))
async def duration_selected_handler(callback: CallbackQuery, state: FSMContext):
    duration_map = {
        "sub_1month": "1 месяц — 150 ₽",
        "sub_3month": "3 месяца — 430 ₽",
        "sub_6month": "6 месяцев — 850 ₽"
    }

    duration = duration_map.get(callback.data)
    if duration:
        await state.update_data(duration=duration)
        await state.set_state(BuyFlow.choosing_server)
        await callback.message.edit_text(
            "Выберите сервер:",
            reply_markup=get_servers_inline_keyboard()
        )
    await callback.answer()


@router.callback_query(F.data == "back_to_subscription")
async def back_to_subscription_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BuyFlow.choosing_duration)
    await callback.message.edit_text(
        "Выберите срок подписки:",
        reply_markup=get_subscription_inline_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("server_"))
async def server_selected_handler(callback: CallbackQuery, state: FSMContext):
    server_map = {
        "server_germany": "🇩🇪 Германия"
    }

    server = server_map.get(callback.data)
    if server:
        user_data = await state.get_data()
        duration = user_data.get("duration")

        # Цены
        prices = {
            "1 месяц — 150 ₽": (150, 30),
            "3 месяца — 430 ₽": (430, 90),
            "6 месяцев — 850 ₽": (850, 180)
        }

        amount, days = prices[duration]

        # Создаем платеж
        link, label = create_payment_link(
            user_id=callback.from_user.id,
            duration=duration,
            server=server,
            amount=amount
        )

        if link:
            # Сохраняем платеж
            save_payment_label(
                user_id=callback.from_user.id,
                label=label,
                server=server,
                amount=amount,
                days=days,
                status="pending"
            )

            await callback.message.edit_text(
                f"✅ <b>Детали заказа:</b>\n\n"
                f"📅 <b>Подписка:</b> {duration}\n"
                f"🌐 <b>Сервер:</b> {server}\n"
                f"💰 <b>Сумма:</b> {amount} ₽\n\n"
                f"➡️ <a href='{link}'>Нажмите для оплаты</a>\n\n"
                f"После оплаты подписка активируется автоматически!",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        else:
            await callback.message.edit_text(
                "❌ Ошибка создания платежа. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_subscription")]
                    ]
                )
            )
    await callback.answer()


@router.callback_query(F.data == "show_server")
async def show_server_handler(callback: CallbackQuery):
    subscription = get_user_subscription(callback.from_user.id)

    if subscription:
        server = subscription.get('server')
        end_date = subscription.get('end_date')

        # Генерируем УНИКАЛЬНЫЙ конфиг для пользователя
        config_link = generate_v2ray_config(callback.from_user.id, server)

        if config_link:
            await callback.message.answer(
                f"<b>🌐 Ваш ПЕРСОНАЛЬНЫЙ VPN сервер</b>\n\n"
                f"<b>Сервер:</b> {server}\n"
                f"<b>Активен до:</b> {end_date}\n\n"
                f"<b>Ваш уникальный конфиг:</b>\n"
                f"<code>{config_link}</code>\n\n"
                f"📋 Этот конфиг создан только для вас!",
                parse_mode="HTML"
            )
        else:
            await callback.message.answer(
                "❌ Ошибка создания конфигурации. Обратитесь к администратору.",
                parse_mode="HTML"
            )
    else:
        await callback.message.edit_text(
            "❌ <b>У вас нет активной подписки</b>\n\n"
            "Приобретите подписку чтобы получить доступ к VPN",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy_access")]
                ]
            ),
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "instructions")
async def instructions_handler(callback: CallbackQuery):
    await callback.message.answer(
        "📖 <b>Инструкция по использованию:</b>\n\n"
        "1. Установите приложение <b>V2RayBox</b>\n"
        "2. Нажмите на <b>+</b> (добавить сервер)\n"
        "3. Выберите <b>Импортировать v2ray URI из буфера</b>\n"
        "4. Автоматически добавится ваш сервер\n"
        "5. Нажмите <b>Подключить</b>\n\n"
        "⚡ <b>Готово! VPN активирован.</b>",
        parse_mode="HTML"
    )
    await callback.answer()
