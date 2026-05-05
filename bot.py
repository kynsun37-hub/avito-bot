import os
import asyncio
import aiohttp
import re
from datetime import datetime
from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
from aiogram.types import ParseMode

TOKEN = os.getenv("TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# ========== НАСТРОЙКИ (ИЗМЕНИТЕ ПОД СЕБЯ) ==========
AVITO_SEARCH_URL = "https://www.avito.ru/krasnodar/telefony/mobilnye_telefony/apple-ASgBAgICAkS0wA30qzmwwQ2I_Dc?q=iphone&s=104"
MY_BUDGET = 50000
STOP_WORDS = ["скупка", "выкуп", "ремонт", "запчасти", "услуги"]
MAX_ADS = 10  # Количество объявлений для отправки

def is_relevant(text):
    """Проверяет, не содержит ли объявление мусорных слов"""
    if not text:
        return True
    text_lower = text.lower()
    for word in STOP_WORDS:
        if word in text_lower:
            return False
    return True

async def fetch_avito():
    """Загружает страницу Авито"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(AVITO_SEARCH_URL, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    print(f"HTTP ошибка: {resp.status}")
                    return None
        except Exception as e:
            print(f"Ошибка соединения: {e}")
            return None

def parse_ads(html):
    """Извлекает объявления из HTML"""
    ads = []
    
    # Поиск всех объявлений через регулярные выражения
    # Ищем блоки с data-marker="item"
    item_pattern = r'data-marker="item"[^>]*>.*?</div></div></div></div>'
    items = re.findall(item_pattern, html, re.DOTALL)
    
    # Альтернативный метод через JSON-данные на странице
    # Ищем window._initialState
    json_match = re.search(r'window\._initialState\s*=\s*({.*?});', html, re.DOTALL)
    
    if json_match:
        try:
            import json
            data = json.loads(json_match.group(1))
            # Пытаемся найти items в структуре
            items_data = data.get('catalog', {}).get('items', [])
            for item in items_data[:MAX_ADS]:
                ad = {
                    'id': str(item.get('id', '')),
                    'title': item.get('title', 'Без названия'),
                    'price': item.get('price', {}).get('value', 0),
                    'url': f"https://www.avito.ru{item.get('urlPath', '')}",
                    'photo': item.get('images', [{}])[0].get('url', '') if item.get('images') else '',
                }
                ads.append(ad)
        except:
            pass
    
    # Если JSON-метод не сработал, используем старый метод с regex
    if not ads:
        id_matches = re.findall(r'"id"\s*:\s*"(\d+)"', html)
        title_matches = re.findall(r'"title"\s*:\s*"([^"]+)"', html)
        price_matches = re.findall(r'"price"\s*:\s*"(\d+)"', html)
        url_matches = re.findall(r'"urlPath"\s*:\s*"([^"]+)"', html)
        
        for i in range(min(len(id_matches), MAX_ADS * 2)):  # Берем с запасом
            if i < len(title_matches) and i < len(price_matches):
                ad = {
                    'id': id_matches[i],
                    'title': title_matches[i].replace('\\u0026', '&').replace('\\u0022', '"'),
                    'price': int(price_matches[i]) if price_matches[i].isdigit() else 0,
                    'url': f"https://www.avito.ru{url_matches[i]}" if i < len(url_matches) else "",
                    'photo': '',
                }
                ads.append(ad)
    
    return ads

async def get_top_ads():
    """Получает топ N объявлений без фильтрации по новизне"""
    print(f"[{datetime.now()}] Запрос к Авито...")
    
    html = await fetch_avito()
    if not html:
        return None, "❌ Не удалось загрузить Авито. Возможно, сайт временно недоступен."
    
    all_ads = parse_ads(html)
    if not all_ads:
        return None, "❌ Не найдено объявлений по вашему запросу."
    
    # Фильтруем по бюджету и стоп-словам
    filtered_ads = []
    for ad in all_ads:
        if ad['price'] <= MY_BUDGET and is_relevant(ad['title']):
            filtered_ads.append(ad)
    
    if not filtered_ads:
        return None, f"❌ Нет объявлений в пределах бюджета ({MY_BUDGET:,} руб.)"
    
    # Берём первые MAX_ADS
    top_ads = filtered_ads[:MAX_ADS]
    
    return top_ads, None

def format_ads_message(ads):
    """Форматирует объявления в одно сообщение"""
    if not ads:
        return "❌ Объявления не найдены"
    
    message = f"🔔 <b>АКТУАЛЬНЫЕ ОБЪЯВЛЕНИЯ</b>\n"
    message += f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
    message += f"💰 Бюджет: {MY_BUDGET:,} руб\n"
    message += f"📊 Найдено подходящих: {len(ads)}\n"
    message += f"─" * 30 + "\n\n"
    
    for i, ad in enumerate(ads, 1):
        # Обрезаем слишком длинные заголовки
        title = ad['title'][:70] + "..." if len(ad['title']) > 70 else ad['title']
        
        message += f"<b>{i}. {title}</b>\n"
        message += f"💰 {ad['price']:,} руб\n"
        message += f"🔗 <a href='{ad['url']}'>Открыть объявление</a>\n\n"
    
    message += f"─" * 30 + "\n"
    message += f"🔄 Чтобы обновить, снова отправьте /check"
    
    return message

async def send_ads_to_telegram(ads):
    """Отправляет объявления в Telegram (одним сообщением)"""
    if not ads:
        return
    
    message = format_ads_message(ads)
    
    try:
        # Пробуем отправить с фото первого объявления (если есть)
        first_ad = ads[0]
        if first_ad.get('photo'):
            try:
                await bot.send_photo(
                    CHAT_ID,
                    photo=first_ad['photo'],
                    caption=message,
                    parse_mode=ParseMode.HTML
                )
                return
            except:
                pass  # Если фото не отправилось, шлём обычное сообщение
        
        # Обычное сообщение без фото
        await bot.send_message(
            CHAT_ID,
            message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")
        await bot.send_message(CHAT_ID, f"❌ Ошибка при отправке: {e}")

# ========== КОМАНДЫ БОТА ==========
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.reply(
        f"🤖 <b>Авито Монитор</b>\n\n"
        f"✅ Бот готов к работе\n"
        f"💰 Бюджет: {MY_BUDGET:,} руб\n"
        f"📦 Показываю до {MAX_ADS} объявлений за раз\n"
        f"🔍 Поиск: {AVITO_SEARCH_URL.split('?')[0][:50]}...\n\n"
        f"📌 <b>Команды:</b>\n"
        f"/check — показать последние {MAX_ADS} объявлений\n"
        f"/status — показать настройки\n"
        f"/search — показать ссылку поиска\n"
        f"/help — помощь",
        parse_mode=ParseMode.HTML
    )

@dp.message_handler(commands=['check'])
async def check_command(message: types.Message):
    # Отправляем сообщение о начале проверки
    status_msg = await message.reply("🔍 Поиск объявлений на Авито... ⏳")
    
    # Получаем объявления
    ads, error = await get_top_ads()
    
    if error:
        await status_msg.edit_text(error)
        return
    
    # Удаляем сообщение "Поиск..." и отправляем результат
    await status_msg.delete()
    await send_ads_to_telegram(ads)
    
    # Логируем в консоль
    print(f"Отправлено {len(ads)} объявлений")

@dp.message_handler(commands=['status'])
async def status_command(message: types.Message):
    await message.reply(
        f"📊 <b>Статус монитора</b>\n\n"
        f"✅ Бот работает\n"
        f"💰 Бюджет: {MY_BUDGET:,} руб\n"
        f"📦 Показываю: до {MAX_ADS} объявлений\n"
        f"🚫 Стоп-слова: {', '.join(STOP_WORDS)}\n"
        f"🔗 Ссылка: {AVITO_SEARCH_URL[:60]}...\n\n"
        f"🔄 Используйте /check для поиска",
        parse_mode=ParseMode.HTML
    )

@dp.message_handler(commands=['search'])
async def search_command(message: types.Message):
    await message.reply(
        f"🔗 <b>Ваша ссылка поиска на Авито:</b>\n\n"
        f"<code>{AVITO_SEARCH_URL}</code>\n\n"
        f"📌 Скопируйте её и вставьте в браузер",
        parse_mode=ParseMode.HTML
    )

@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    await message.reply(
        f"📖 <b>Помощь</b>\n\n"
        f"⚙️ <b>Как работает бот:</b>\n"
        f"1. Вы отправляете /check\n"
        f"2. Бот парсит Авито по вашей ссылке\n"
        f"3. Отсеивает объявления дороже {MY_BUDGET:,} руб\n"
        f"4. Отсеивает объявления со стоп-словами\n"
        f"5. Показывает до {MAX_ADS} самых свежих\n\n"
        f"✏️ <b>Как изменить настройки:</b>\n"
        f"1. Откройте код на GitHub\n"
        f"2. Найдите переменные в начале файла:\n"
        f"   - AVITO_SEARCH_URL (ваша ссылка)\n"
        f"   - MY_BUDGET (бюджет)\n"
        f"   - STOP_WORDS (стоп-слова)\n"
        f"   - MAX_ADS (количество объявлений)\n"
        f"3. Сохраните изменения\n"
        f"4. Бот перезапустится автоматически\n\n"
        f"❓ Вопросы? Пишите @kynsun37",
        parse_mode=ParseMode.HTML
    )

if __name__ == '__main__':
    print("=" * 50)
    print("🤖 Бот запущен!")
    print(f"🔍 Поиск: {AVITO_SEARCH_URL[:70]}...")
    print(f"💰 Бюджет: {MY_BUDGET} руб")
    print(f"📦 Максимум объявлений: {MAX_ADS}")
    print("=" * 50)
    print("✅ Бот готов к работе. Отправьте /check в Telegram")
    print("=" * 50)
    
    executor.start_polling(dp)
