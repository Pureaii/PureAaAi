import asyncio
import time
import base64
import os
from datetime import datetime, timedelta
import aiosqlite
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from aiocryptopay import AioCryptoPay, Networks

# --- СЕКРЕТЫ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")
IDEOGRAM_TOKEN = os.getenv("IDEOGRAM_TOKEN")
LOG_BOT_TOKEN = os.getenv("LOG_BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL") # Сюда потом вставишь ссылку от Render

LOG_CHAT_IDS = [7436250641, 8328958508]
ADMIN_IDS = [7436250641, 8328958508] 
CARD_DETAILS = "2202 2085 7276 0628"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
log_bot = Bot(token=LOG_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
crypto = AioCryptoPay(token=CRYPTO_BOT_TOKEN, network=Networks.MAIN_NET)
admin_payment_messages = {}

DB_FILE = "database.db"

# ==========================================
# БД И ЛОГИКА
# ==========================================
async def send_log(text: str):
    for admin_id in LOG_CHAT_IDS:
        try: await log_bot.send_message(chat_id=admin_id, text=f"📝 <b>Лог:</b>\n\n{text}")
        except Exception: pass

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0.0, sub_end TIMESTAMP, is_banned INTEGER DEFAULT 0, last_free_gen TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS promos (code TEXT PRIMARY KEY, reward REAL, uses_left INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS used_promos (user_id INTEGER, code TEXT)")
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT balance, sub_end, last_free_gen FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                await db.commit()
                return 0.0, None, None
            return row[0], row[1], row[2]

async def update_balance(user_id, amount):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def consume_free_gen(user_id):
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE users SET last_free_gen = ? WHERE user_id = ?", (now, user_id))
        await db.commit()

# ==========================================
# ТЕЛЕГРАМ
# ==========================================
@dp.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    await get_user(message.from_user.id)
    if not WEBAPP_URL:
        return await message.answer("⚠️ WEBAPP_URL не настроен!")
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть Pure AI", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    await message.answer("Добро пожаловать в студию дизайна Pure AI.", reply_markup=kb)

class TopUpState(StatesGroup): screenshot = State(); amount = State()

@dp.message(TopUpState.screenshot, F.photo)
async def process_screenshot(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    user_id = message.from_user.id
    payment_id = str(int(time.time()))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"fiat_ok_{user_id}_{amount}_{payment_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"fiat_no_{user_id}_{payment_id}")]
    ])
    admin_payment_messages[payment_id] = []
    for admin in ADMIN_IDS:
        try:
            msg = await bot.send_photo(chat_id=admin, photo=message.photo[-1].file_id, caption=f"Заявка РФ Банк\nID: {user_id}\nСумма: {amount}₽", reply_markup=kb)
            admin_payment_messages[payment_id].append((admin, msg.message_id))
        except: pass
    await message.answer("✔️ Чек отправлен!")
    await state.clear()

@dp.callback_query(F.data.startswith("fiat_ok_"))
async def approve_fiat(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, amount, payment_id = int(parts[2]), float(parts[3]), parts[4]
    if payment_id not in admin_payment_messages: return await call.answer("Обработано!")
    admin_payment_messages.pop(payment_id, [])
    await update_balance(user_id, amount)
    try: await bot.send_message(user_id, f"✅ Баланс пополнен на {amount} ₽.")
    except: pass
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n✅ ОДОБРЕНО", reply_markup=None)

@dp.callback_query(F.data.startswith("fiat_no_"))
async def reject_fiat(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, payment_id = int(parts[2]), parts[3]
    if payment_id not in admin_payment_messages: return await call.answer("Обработано!")
    admin_payment_messages.pop(payment_id, [])
    try: await bot.send_message(user_id, f"❌ Чек отклонен.")
    except: pass
    await call.message.edit_caption(caption=f"{call.message.caption}\n\n❌ ОТКЛОНЕНО", reply_markup=None)

# ==========================================
# WEB-СЕРВЕР (API)
# ==========================================
routes = web.RouteTableDef()

@routes.get("/")
async def index_handler(request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), 'index.html'))

@routes.get("/style.css")
async def style_handler(request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), 'style.css'))

@routes.get("/app.js")
async def js_handler(request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), 'app.js'))

@routes.post("/api/profile")
async def api_profile(request):
    data = await request.json()
    balance, sub_end, _ = await get_user(data['user_id'])
    return web.json_response({"success": True, "balance": balance, "sub_end": sub_end})

@routes.post("/api/promo")
async def api_promo(request):
    data = await request.json()
    user_id, code = data['user_id'], data['code'].strip()
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT 1 FROM used_promos WHERE user_id = ? AND code = ?", (user_id, code)) as c:
            if await c.fetchone(): return web.json_response({"success": False, "error": "Использован"})
        async with db.execute("SELECT reward, uses_left FROM promos WHERE code = ?", (code,)) as c:
            promo = await c.fetchone()
            if promo and promo[1] > 0:
                await update_balance(user_id, promo[0])
                await db.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code = ?", (code,))
                await db.execute("INSERT INTO used_promos (user_id, code) VALUES (?, ?)", (user_id, code))
                await db.commit()
                return web.json_response({"success": True, "reward": promo[0]})
            return web.json_response({"success": False, "error": "Неверный код"})

@routes.post("/api/topup_crypto")
async def api_topup_crypto(request):
    data = await request.json()
    try:
        amount_usdt = round(float(data['amount']) / 100, 2)
        invoice = await crypto.create_invoice(asset='USDT', payload=str(data['user_id']), amount=amount_usdt)
        return web.json_response({"success": True, "url": invoice.bot_invoice_url})
    except Exception as e: return web.json_response({"success": False, "error": str(e)})

@routes.post("/api/topup_fiat")
async def api_topup_fiat(request):
    data = await request.json()
    user_id, amount = data['user_id'], float(data['amount'])
    await bot.send_message(chat_id=user_id, text=f"💳 <b>Карта РФ</b>\nСумма: {amount} ₽\nРеквизиты: <code>{CARD_DETAILS}</code>\n\nСкинь скрин чека сюда.")
    state = dp.fsm.resolve_context(bot=bot, chat_id=user_id, user_id=user_id)
    await state.set_state(TopUpState.screenshot)
    await state.update_data(amount=amount)
    return web.json_response({"success": True})

@routes.post("/api/generate")
async def api_generate(request):
    data = await request.json()
    user_id = data['user_id']
    gen_type = data['type']
    description = data['prompt'] 
    
    balance, sub_end, last_free_gen = await get_user(user_id)
    now = datetime.now()
    has_sub = sub_end and datetime.fromisoformat(sub_end) > now
    can_try_free = not last_free_gen or (datetime.fromisoformat(last_free_gen) + timedelta(days=8) <= now)
    
    if not has_sub and not can_try_free: return web.json_response({"success": False, "need_sub": True})

    await send_log(f"⚙️ <b>API ГЕНЕРАЦИЯ ({gen_type})</b>\nЮзер: {user_id}\nТекст: {description}")

    try:
        timeout = aiohttp.ClientTimeout(total=None)
        connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            
            if gen_type == 'logo':
                headers = {"Api-Key": IDEOGRAM_TOKEN, "Content-Type": "application/json"}
                ideogram_prompt = f"A minimalist, premium corporate logo for '{description}'. Clean typography, million-dollar company aesthetic, high-end digital branding style. Solid background, high quality, vector style."
                payload = {"image_request": {"prompt": ideogram_prompt, "aspect_ratio": "ASPECT_1_1", "model": "V_2", "magic_prompt_option": "ON"}}
                async with session.post("https://api.ideogram.ai/generate", headers=headers, json=payload) as resp:
                    if resp.status != 200: raise Exception(await resp.text())
                    res_json = await resp.json()
                    async with session.get(res_json['data'][0]['url']) as img_resp:
                        result_b64 = base64.b64encode(await img_resp.read()).decode('utf-8')
                        
            else:
                base64_image = data['image'] 
                if gen_type == 'info':
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent?key={GEMINI_TOKEN}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": (
                                    f"You are an elite, world-class e-commerce Art Director creating an ultra-premium, beautifully decorated, high-converting product card for Wildberries/Ozon. Aspect Ratio: strictly 3:4 vertical. "
                                    f"Task: Elevate the provided product image to a luxurious, 'million-dollar brand' marketplace standard based on this description: '{description}'. "
                                    f"\n\nCRITICAL DIRECTIVES: "
                                    f"\n1. ZERO DEFORMATION (THE SACRED PRODUCT): The original product is strictly immutable. DO NOT hallucinate, redraw, or alter its design. You are only allowed to apply a slight, natural tilt for a dynamic angle. Make it the hero object, seamlessly grounded with hyper-realistic studio lighting and contact shadows. "
                                    f"\n2. COHESIVE ADAPTIVE ENVIRONMENT & DECOR: Auto-analyze the product's niche. Generate a flawless background AND matching contextual decor along the edges or surrounding the product (e.g., floating leaves/water for beauty, neon particles for tech, splashes for food). The scene must look 'rich' and perfectly match the product's vibe. "
                                    f"\n3. PUNCHY MINIMALIST HEADLINE: Generate a striking main headline in Russian at the top. CRITICAL TEXT RULE: Maximum 1 or 2 words capturing ONLY the core product noun. The font family MUST dynamically adapt to the product's character (e.g., elegant thin serifs for premium goods, massive brutalist sans-serifs for tools). "
                                    f"\n4. ANTI-TEMPLATE DYNAMIC UI CALLOUTS (УТП): Extract 3-4 short selling points with flat 2D icons. "
                                    f"- BREAK THE GRID: Do NOT use a rigid, predictable template. Do NOT just stack them in a boring straight column on one side. Distribute them organically: place them elegantly along the bottom, stagger them asymmetrically around the product, or use creative wrapping layouts. "
                                    f"- VARIED SHAPES & MIXED STYLES: Avoid repetitive square boxes. Use diverse, modern shapes like rounded pills, elegant thin underline strokes, or sleek tags. To make it look like high-end editorial design rather than a cheap template, MIX presentations on the same card: you can put one highly important feature inside a beautiful plaque, and leave the other features as clean, free-floating text with icons. "
                                    f"- NO 3D PLATES: All UI elements must remain flat and graphic (vector style, modern UI). No heavy bevels or 3D extrusions. "
                                    f"\n5. THE RESULT: A visual masterpiece that NEVER looks like a cheap template. Every generation must feature a completely fresh, asymmetrical, and highly creative composition that is expensive, beautifully decorated, and highly clickable."
                                )},
                                {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}}
                            ]
                        }],
                        "generationConfig": {
                            "responseModalities": ["IMAGE"]
                        }
                    }
                else:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent?key={GEMINI_TOKEN}"
                    ai_prompt = f"World-class commercial product photographer. High-end product lifestyle photo based on: '{description}'. 1. PRODUCT PRESERVATION: 100% untouched. 2. ENVIRONMENT: Realistic premium background. 3. INTEGRATION: Highly realistic drop shadows. 4. NO TEXT OR UI: STRICTLY NO text, NO graphic overlays."
                    payload = {"contents": [{"parts": [{"text": ai_prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}}]}], "generationConfig": {"responseModalities": ["IMAGE"]}}
                
                max_retries = 3
                result_b64 = None
                for attempt in range(max_retries):
                    try:
                        async with session.post(url, json=payload) as resp:
                            if resp.status == 200:
                                res_json = await resp.json()
                                candidates = res_json.get('candidates', [])
                                if not candidates: raise Exception("Пустой ответ (Safety).")
                                parts = candidates[0].get('content', {}).get('parts', [])
                                for p in parts:
                                    if 'inlineData' in p: result_b64 = p['inlineData']['data']; break
                                    elif 'inline_data' in p: result_b64 = p['inline_data']['data']; break
                                if result_b64: break
                            elif resp.status in [503, 429, 500]:
                                if attempt < max_retries - 1: await asyncio.sleep(3); continue
                            raise Exception(f"Код {resp.status}")
                    except (asyncio.TimeoutError, aiohttp.ClientError, OSError):
                        if attempt < max_retries - 1: await asyncio.sleep(2); continue
                        raise Exception("Сетевой обрыв.")
                if not result_b64: raise Exception("Сбой серверов ИИ.")

        if not has_sub: await consume_free_gen(user_id)
        return web.json_response({"success": True, "image": result_b64})

    except Exception as e:
        await send_log(f"❌ Ошибка: {str(e)[:200]}")
        return web.json_response({"success": False, "error": str(e)[:100]})

async def main():
    print("🔧 Инициализация базы данных...")
    await init_db()
    
    print("🌐 Настройка Web-сервера...")
    app = web.Application(client_max_size=50 * 1024 * 1024) 
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render динамически выдает порт через переменную окружения PORT (по умолчанию 10000 для локальных тестов)
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Web-сервер запущен на порту {port}!")
    
    print("📨 Попытка отправить сообщение в лог-бот...")
    await send_log(f"🚀 <b>WebApp запущен на порту {port}!</b>")
    
    print("🤖 Сброс вебхуков Телеграма...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"⚠️ Ошибка при сбросе вебхука: {e}")
    
    try: 
        print("🚀 ПОЕХАЛИ! Бот начал слушать сообщения...")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА БОТА: {e}")
    finally: 
        await bot.session.close()
        await log_bot.session.close()
        print("🛑 Бот остановлен.")

if __name__ == "__main__":
    asyncio.run(main())

