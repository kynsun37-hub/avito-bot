import asyncio
import aiohttp
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from bs4 import BeautifulSoup

# ========== НАСТРОЙКИ (ЗАМЕНИТЕ НА СВОИ) ==========
TELEGRAM_TOKEN = "8562770208:AAGNWBr2joXmde87yHqCLutU0zot5KCSk6g"  
CHAT_ID = 1123010011  

# НАСТРОЙКИ ПОИСКА АВИТО
# Как получить URL для нужного поиска:
# 1. Зайдите на avito.ru
# 2. Введите поисковый запрос (например, "iphone 13")
# 3. Скопируйте URL из адресной строки
AVITO_SEARCH_URL = "https://www.avito.ru/krasnodar/telefony/mobilnye_telefony/apple-ASgBAgICAkS0wA3OqzmwwQ2I_Dc?cd=1&context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImRta1YxZFEzT3BueHlrOHYiO327WDBqJgAAAA&localPriority=0&s=104&user=1"

# НАСТРОЙКИ ФИЛЬТРАЦИИ
MY_BUDGET = 40000  # Ваш бюджет в рублях (объявления дороже не будут отправляться)
STOP_WORDS = ["скупка", "выкуп", "ремонт", "запчасти", "услуги", "trade-in", "айфон", "акб"]  # Мусорные слова

# ПРОЦЕНТ ДЛЯ ОПРЕДЕЛЕНИЯ ВЫГОДНОЙ ЦЕНЫ (например, если цена ниже рынка на 20%, считаем выгодной)
GOOD_PRICE_PERCENT = 20  # 20% - если цена ниже средней на 20%, то "ОЧЕНЬ ВЫГОДНО"

# ========== ИНИЦИАЛИЗАЦИЯ БОТА ==========
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Файл для хранения ID уже отправленных объявлений
SEEN_FILE = "seen_ads.json"

def load_seen_ids():
    """Загружает ID уже отправленных объявлений"""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen_ids(ids):
    """Сохраняет ID отправленных объявлений"""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f, ensure_ascii=False, indent=2)

def is_relevant_by_keywords(text):
    """Проверяет, не содержит ли объявление мусорных слов"""
    if not text:
        return True
    text_lower = text.lower()
    for word in STOP_WORDS:
        if word.lower() in text_lower:
            return False
    return True

def analyze_price(ad_price, market_avg_price):
    """
    Анализирует цену и возвращает вердикт:
    - None - не подходит по бюджету
    - строка с оценкой выгодности
    """
    if ad_price > MY_BUDGET:
        return None  # Не подходит по бюджету
    
    # Расчет экономии
    if market_avg_price and market_avg_price > 0:
        discount_percent = ((market_avg_price - ad_price) / market_avg_price) * 100
        
        if discount_percent >= GOOD_PRICE_PERCENT:
            return f"🔥 ОЧЕНЬ ВЫГОДНО! Цена ниже рынка на {discount_percent:.0f}%\n💰 Ваша экономия: {market_avg_price - ad_price:,} руб"
        elif discount_percent > 0:
            return f"✅ Хорошая цена! Ниже рынка на {discount_percent:.0f}%"
        elif discount_percent > -10:
            return f"💰 Цена соответствует рынку"
    
    return f"💰 Цена в рамках вашего бюджета"

def calculate_market_average(items):
    """
    Вычисляет среднюю цену на рынке из последних объявлений
    """
    prices = []
    for item in items:
        price = item.get("priceDetailed", {}).get("value")
        if price and isinstance(price, (int, float)) and price > 0:
            prices.append(price)
    
    if not prices:
        return None
    
    return sum(prices) // len(prices)

def parse_avito_items(html_content):
    """
    Парсит HTML-страницу Авито и извлекает объявления
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    items = []
    
    # Ищем все блоки объявлений на странице
    ad_blocks = soup.find_all('div', {'data-marker': 'item'})
    
    for block in ad_blocks:
        try:
            # Извлекаем ID объявления
            ad_id = block.get('id', '').replace('i', '')
            
            # Извлекаем заголовок
            title_elem = block.find('h3', {'itemprop': 'name'})
            if not title_elem:
                title_elem = block.find('a', {'data-marker': 'item-title'})
            title = title_elem.text.strip() if title_elem else "Без названия"
            
            # Извлекаем цену
            price_elem = block.find('span', {'data-marker': 'item-price'})
            if not price_elem:
                price_elem = block.find('meta', {'itemprop': 'price'})
            price = 0
            if price_elem:
                price_text = price_elem.text.strip() if not price_elem.get('content') else price_elem.get('content')
                # Убираем пробелы и не-цифры
                price = int(''.join(filter(str.isdigit, price_text))) if price_text else 0
            
            # Извлекаем ссылку
            link_elem = block.find('a', {'data-marker': 'item-title'})
            if not link_elem:
                link_elem = block.find('a', {'class': 'iva-item-title'})
            link = link_elem.get('href') if link_elem else ''
            if link and not link.startswith('http'):
                link = f"https://www.avito.ru{link}"
            
            # Извлекаем фото
            img_elem = block.find('img', {'data-marker': 'item-img'})
            photo_url = img_elem.get('src') if img_elem else None
            
            # Извлекаем описание (краткое)
            desc_elem = block.find('div', {'data-marker': 'item-specific-params'})
            description = desc_elem.text.strip() if desc_elem else ""
            
            items.append({
                'id': ad_id,
                'title': title,
                'price': price,
                'url': link,
                'photo': photo_url,
                'description': description
            })
        except Exception as e:
            print(f"Ошибка при парсинге объявления: {e}")
            continue
    
    return items

async def fetch_avito_page():
    """
    Загружает страницу Авито с поиском
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(AVITO_SEARCH_URL, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    return html
                else:
                    print(f"Ошибка HTTP {response.status}")
                    return None
        except Exception as e:
            print(f"Ошибка соединения: {e}")
            return None

def format_ad_message(item, price_verdict):
    """
    Форматирует сообщение для отправки в Telegram
    """
    message = f"🏠 {item['title']}\n\n"
    message += f"💰 Цена: {item['price']:,} руб\n"
    
    if price_verdict:
        message += f"\n{price_verdict}\n"
    
    message += f"\n🔗 Ссылка: {item['url']}"
    
    if item['description']:
        message += f"\n\n📝 {item['description'][:150]}..."
    
    message += f"\n\n🕒 Найдено: {datetime.now().strftime('%H:%M:%S')}"
    
    return message

async def send_ad(item, price_verdict):
    """
    Отправляет объявление в Telegram
    """
    text = format_ad_message(item, price_verdict)
    
    try:
        if item['photo'] and item['photo'].startswith('http'):
            await bot.send_photo(
                chat_id=CHAT_ID,
                photo=item['photo'],
                caption=text,
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
        return True
    except Exception as e:
        print(f"Ошибка отправки: {e}")
        return False

async def check_new_ads():
    """
    Основная функция проверки новых объявлений
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Начинаю проверку...")
    
    # Загружаем страницу Авито
    html = await fetch_avito_page()
    if not html:
        print("Не удалось загрузить страницу")
        return
    
    # Парсим объявления
    items = parse_avito_items(html)
    if not items:
        print("Не удалось найти объявления")
        return
    
    print(f"Найдено объявлений: {len(items)}")
    
    # Загружаем ID уже отправленных объявлений
    seen_ids = load_seen_ids()
    
    # Вычисляем среднюю цену на рынке (первые 20 объявлений)
    market_avg = calculate_market_average(items[:20])
    if market_avg:
        print(f"Средняя цена на рынке: {market_avg:,} руб")
    
    # Проверяем новые объявления
    new_items = []
    for item in items:
        if item['id'] and item['id'] not in seen_ids:
            # Проверяем на мусорные слова
            if not is_relevant_by_keywords(item['title'] + " " + item['description']):
                print(f"Пропускаем (мусор): {item['title']}")
                continue
            
            # Анализируем цену
            price_verdict = analyze_price(item['price'], market_avg)
            if not price_verdict:
                print(f"Пропускаем (дорого): {item['title']} - {item['price']:,} руб")
                continue
            
            new_items.append((item, price_verdict))
    
    # Отправляем новые объявления
    if new_items:
        print(f"Найдено {len(new_items)} новых релевантных объявлений!")
        for item, verdict in new_items:
            success = await send_ad(item, verdict)
            if success:
                seen_ids.add(item['id'])
                print(f"Отправлено: {item['title']}")
            await asyncio.sleep(2)  # Пауза между отправками
        
        save_seen_ids(seen_ids)
    else:
        print("Нет новых подходящих объявлений")
    
    print("Проверка завершена\n")

# ========== КОМАНДЫ БОТА В TELEGRAM ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 Привет! Я бот для мониторинга Авито\n\n"
        "Я автоматически проверяю новые объявления и отправляю только выгодные варианты\n\n"
        "Команды:\n"
        "/status - статус мониторинга\n"
        "/check - ручная проверка\n"
        "/help - помощь"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📖 Как это работает:\n\n"
        "1. Я проверяю Авито каждые 5 минут\n"
        "2. Отсеиваю объявления с мусорными словами\n"
        "3. Сравниваю цену с рыночной\n"
        "4. Отправляю только выгодные предложения\n\n"
        f"💰 Ваш бюджет: {MY_BUDGET:,} руб\n"
        f"📉 Выгодная цена: ниже рынка на {GOOD_PRICE_PERCENT}%\n"
        f"🚫 Стоп-слова: {', '.join(STOP_WORDS)}"
    )

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    seen_count = len(load_seen_ids())
    await message.answer(
        f"📊 Статус монитора:\n\n"
        f"✅ Работает\n"
        f"🔍 URL поиска: {AVITO_SEARCH_URL[:50]}...\n"
        f"💰 Бюджет: {MY_BUDGET:,} руб\n"
        f"📦 Отправлено объявлений: {seen_count}\n"
        f"⏱️ Проверка каждые 5 минут"
    )

@dp.message(Command("check"))
async def cmd_check(message: types.Message):
    await message.answer("🔍 Запускаю ручную проверку...")
    await check_new_ads()
    await message.answer("✅ Проверка завершена!")

# ========== ЗАПУСК БОТА ==========
async def periodic_check():
    """Запускает периодическую проверку каждые 5 минут"""
    while True:
        await check_new_ads()
        await asyncio.sleep(300)  # 300 секунд = 5 минут

# ЗАМЕНИТЕ КОНЕЦ ФАЙЛА НА ЭТО:

async def periodic_check():
    """Запускает периодическую проверку каждые 5 минут"""
    while True:
        try:
            await check_new_ads()
        except Exception as e:
            print(f"Ошибка в цикле: {e}")
        await asyncio.sleep(300)  # 300 секунд = 5 минут

async def main():
    # Запускаем периодическую проверку в фоне
    asyncio.create_task(periodic_check())
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    print("Бот запущен!")
    # Для PythonAnywhere используем asyncio.run()
    asyncio.run(main())