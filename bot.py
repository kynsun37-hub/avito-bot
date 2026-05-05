import os
import asyncio
import aiohttp
import re
import json
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
# ИСПОЛЬЗУЕМ МОБИЛЬНУЮ ВЕРСИЮ АВИТО (она стабильнее для парсинга)
# Просто добавьте 'm.' перед avito.ru в вашей ссылке
AVITO_SEARCH_URL = "https://m.avito.ru/krasnodar/telefony/mobilnye_telefony/apple-ASgBAgICAkS0wA30qzmwwQ2I_Dc?q=iphone&s=104"

MY_BUDGET = 50000
STOP_WORDS = ["скупка", "выкуп", "ремонт", "запчасти", "услуги", "trade-in"]
MAX_ADS = 10

def is_relevant(text):
    if not text:
        return True
    text_lower = text.lower()
    for word in STOP_WORDS:
        if word.lower() in text_lower:
            return False
    return True

async def fetch_avito():
    """Загружает страницу мобильного Авито"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(AVITO_SEARCH_URL, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    print(f"Загружено {len(html)} символов")
                    return html
                else:
                    print(f"HTTP ошибка: {resp.status}")
                    return None
        except Exception as e:
            print(f"Ошибка соединения: {e}")
            return None

def parse_mobile_avito(html):
    """Парсит мобильную версию Авито"""
    ads = []
    
    # Метод 1: Ищем JSON-данные в скриптах
    json_pattern = r'<script type="application/ld\+json">(.*?)</script>'
    json_matches = re.findall(json_pattern, html, re.DOTALL)
    
    for match in json_matches:
        try:
            data = json.loads(match)
            if isinstance(data, dict) and 'itemListElement' in data:
                for item in data['itemListElement']:
                    if 'item' in item:
                        item_data = item['item']
                        ad = {
                            'id': str(item_data.get('@id', '').split('/')[-1] if item_data.get('@id') else ''),
                            'title': item_data.get('name', 'Без названия'),
                            'price': int(item_data.get('price', '0')) if item_data.get('price') else 0,
                            'url': item_data.get('url', ''),
                            'photo': item_data.get('image', '')
                        }
                        if ad['id'] and ad['price'] > 0:
                            ads.append(ad)
        except:
            pass
    
    # Метод 2: Если JSON не сработал, ищем блоки объявлений
    if not ads:
        # Ищем блоки с классом item
        item_pattern = r'<div class="item[^"]*"[^>]*>.*?<a href="([^"]+)".*?<h3[^>]*>(.*?)</h3>.*?<span class="price">([^<]+)</span>'
        matches = re.findall(item_pattern, html, re.DOTALL)
        
        for match in matches[:MAX_ADS]:
            url = match[0] if match[0].startswith('http') else f"https://m.avito.ru{match[0]}"
            title = match[1].strip()
            price_text = match[2].strip()
            
            # Извлекаем цифры из цены
            price_numbers = re.findall(r'\d+', price_text)
            price = int(''.join(price_numbers)) if price_numbers else 0
            
            ad_id = url.split('/')[-1] if url else str(hash(url))
            
            ads.append({
                'id': ad_id,
                'title': title,
                'price': price,
                'url': url,
                'photo': ''
            })
    
    # Метод 3: Самый простой — ищем через data-marker
    if not ads:
        marker_pattern = r'data-marker="item(?:/title)?"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        matches = re.findall(marker_pattern, html, re.DOTALL)
        
        for match in matches[:MAX_ADS]:
            url = match[0] if match[0].startswith('http') else f"https://m.avito.ru{match[0]}"
            title = re.sub(r'<[^>]+>', '', match[1]).strip()
            
            # Ищем цену отдельно
            price_pattern = r'<span[^>]*data-marker="item-price"[^>]*>([^<]+)</span>'
            price_match = re.search(price_pattern, html)
            price = 0
            if price_match:
                price_text = price_match.group(1)
                price_numbers = re.findall(r'\d+', price_text)
                price = int(''.join(price_numbers)) if price_numbers else 0
            
            ad_id = url.split('/')[-1] if url else str(hash(url))
            
            ads.append({
                'id': ad_id,
                'title': title,
                'price': price,
                'url': url,
                'photo': ''
            })
    
    # Убираем дубликаты по ID
    unique_ads = []
    seen_ids = set()
    for ad in ads:
        if ad['id'] not in seen_ids:
            seen_ids.add(ad['id'])
            unique_ads.append(ad)
    
    return unique_ads

async def get_top_ads():
    """Получает топ объявлений"""
    print(f"[{datetime.now()}] Запрос к мобильному Авито...")
    
    html = await fetch_avito()
    if not html:
        return None, "❌ Не удалось загрузить Авито. Проверьте интернет или повторите позже."
    
    all_ads = parse_mobile_avito(html)
    
    if not all_ads:
        # Сохраним HTML для отладки (первые 500 символов)
        debug_info = html[:500] if html else "пусто"
        print(f"Не удалось найти объявления. HTML: {debug_info}")
        return None, "❌ Не найдено объявлений. Возможно, сайт изменил структуру."
    
    print(f"Найдено объявлений: {len(all_ads)}")
    
    # Фильтруем по бюджету и стоп-словам
    filtered_ads = []
    for ad in all_ads:
        if ad['price'] <= MY_BUDGET and is_relevant(ad['title']):
            filtered_ads.append(ad)
    
    print(f"После фильтрации: {len(filtered_ads)} (бюджет {MY_BUDGET})")
    
    if not filtered_ads:
        return None, f"❌ Нет объявлений в пределах вашего бюджета ({MY_BUDGET:,} руб.).\n\n💡 Совет: увеличьте бюджет или измените поисковый запрос."
    
    # Берём первые MAX_ADS
    top_ads = filtered_ads[:MAX_ADS]
    
    return top_ads, None

def format_ads_message(ads):
    """Форматирует объявления"""
    if not ads:
        return "❌ Объявления не найдены"
    
    message = f"🔔 <b>АКТУАЛЬНЫЕ ОБЪЯВЛЕНИЯ</b>\n"
    message += f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
    message += f"💰 Бюджет: {MY_BUDGET:,} руб\n"
    message += f"📊 Найдено подходящих: {len(ads)}\n"
    message += f"─" * 35 + "\n\n"
    
    for i, ad in enumerate(ads, 1):
        title = ad['title'][:60] + "..." if len(ad['title']) > 60 else ad['title']
        
        message += f"<b>{i}. {title}</b>\n"
        message += f"💰 {ad['price']:,} руб\n"
        message += f"🔗 <a href='{ad['url']}'>Открыть объявление</a>\n\n"
    
    message += f"─" * 35 + "\n"
    message += f"🔄 Для обновления отправьте /check"
    
    return message

async def send_ads_to_telegram(ads):
    if not ads:
        return
    
    message = format_ads_message(ads)
    
    try:
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
        f"🔍 Поиск: мобильная версия Авито\n\n"
        f"📌 <b>Команды:</b>\n"
        f"/check — найти объявления\n"
        f"/status — показать настройки\n"
        f"/search — показать ссылку поиска\n"
        f"/help — помощь",
        parse_mode=ParseMode.HTML
    )

@dp.message_handler(commands=['check'])
async def check_command(message: types.Message):
    status_msg = await message.reply("🔍 Поиск объявлений на Авито... ⏳")
    
    ads, error = await get_top_ads()
    
    if error:
        await status_msg.edit_text(error)
        return
    
    await status_msg.delete()
    await send_ads_to_telegram(ads)
    
    print(f"Отправлено {len(ads)} объявлений")

@dp.message_handler(commands=['status'])
async def status_command(message: types.Message):
    await message.reply(
        f"📊 <b>Статус монитора</b>\n\n"
        f"✅ Бот работает\n"
        f"💰 Бюджет: {MY_BUDGET:,} руб\n"
        f"📦 Показываю: до {MAX_ADS} объявлений\n"
        f"🚫 Стоп-слова: {', '.join(STOP_WORDS)}\n"
        f"🔗 Ссылка: {AVITO_SEARCH_URL[:70]}...\n\n"
        f"🔄 Используйте /check для поиска",
        parse_mode=ParseMode.HTML
    )

@dp.message_handler(commands=['search'])
async def search_command(message: types.Message):
    await message.reply(
        f"🔗 <b>Ваша ссылка поиска (мобильная версия):</b>\n\n"
        f"<code>{AVITO_SEARCH_URL}</code>\n\n"
        f"📌 <b>Как обновить ссылку?</b>\n"
        f"1. Откройте m.avito.ru в браузере\n"
        f"2. Найдите нужные товары\n"
        f"3. Скопируйте URL\n"
        f"4. Замените AVITO_SEARCH_URL в коде на GitHub",
        parse_mode=ParseMode.HTML
    )

@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    await message.reply(
        f"📖 <b>Помощь</b>\n\n"
        f"⚙️ <b>Как работает бот:</b>\n"
        f"1. Использует <b>мобильную версию</b> Авито (стабильнее)\n"
        f"2. Парсит до {MAX_ADS} объявлений\n"
        f"3. Отсеивает: дороже {MY_BUDGET:,} руб + стоп-слова\n\n"
        f"✏️ <b>Как изменить настройки:</b>\n"
        f"• Откройте код на GitHub\n"
        f"• Найдите переменные в начале файла\n"
        f"• Сохраните — бот перезапустится\n\n"
        f"❓ Не нашли объявления?\n"
        f"• Проверьте ссылку через /search\n"
        f"• Увеличьте бюджет /status\n"
        f"• Уберите стоп-слова из кода",
        parse_mode=ParseMode.HTML
    )

if __name__ == '__main__':
    print("=" * 50)
    print("🤖 Бот запущен!")
    print(f"🔍 Поиск (моб.версия): {AVITO_SEARCH_URL[:80]}...")
    print(f"💰 Бюджет: {MY_BUDGET} руб")
    print(f"📦 Максимум объявлений: {MAX_ADS}")
    print("=" * 50)
    print("✅ Отправьте /check в Telegram")
    print("=" * 50)
    
    executor.start_polling(dp)
