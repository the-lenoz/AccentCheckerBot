import asyncio
import json
import logging
import datetime
import os

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Загрузка настроек из config.json
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

# Загрузка токена бота
with open("BOT_TOKEN", "r", encoding="utf-8") as f:
    BOT_TOKEN = f.read().strip()

DEFAULT_RATE = config.get("default_rate", 5)
USER_DATA_FILE = "user_data.json"

# Загрузка списка слов из words.txt
with open("words.txt", "r", encoding="utf-8") as f:
    master_words = [line.strip() for line in f if line.strip()]

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальный словарь для хранения данных пользователей
user_data = {}

def load_user_data():
    """Загрузка данных пользователей из файла."""
    global user_data
    if os.path.exists(USER_DATA_FILE):
        with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
            user_data = json.load(f)
    else:
        user_data = {}

def save_user_data():
    """Сохранение данных пользователей в файл."""
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=4)

def init_user(user_id: str):
    """Инициализация нового пользователя, если его нет в базе."""
    if str(user_id) not in user_data:
        user_data[str(user_id)] = {
            "queue": master_words.copy(),
            "rate": DEFAULT_RATE,
            "quiz": None
        }
        save_user_data()

def get_stress_letter(word: str) -> str:
    """Определяет ударную букву в слове (первая заглавная буква считается правильной)."""
    for char in word:
        if char.isupper():
            return char
    return ""

async def send_question(user_id: str):
    """Отправляет пользователю очередное слово для ответа."""
    data = user_data.get(str(user_id))
    if not data or not data.get("quiz"):
        return

    quiz = data["quiz"]
    index = quiz["index"]
    words = quiz["words"]

    if index >= len(words):
        await bot.send_message(user_id, config.get("quiz_complete", "Проверка завершена!"))
        data["quiz"] = None
        save_user_data()
    else:
        current_word = words[index]
        message_text = config.get("question_text", "Слово: {word}\nВведите ударную букву:").format(word=current_word)
        await bot.send_message(user_id, message_text)

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    """Команда /start – приветствие, инициализация пользователя и панель команд."""
    user_id = str(message.from_user.id)
    init_user(user_id)

    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("/start"), KeyboardButton("/help"))
    keyboard.add(KeyboardButton("/rate"), KeyboardButton("/quiz"))

    await message.reply(config.get("start_message", "Привет!"), reply_markup=keyboard)

@dp.message_handler(commands=["help"])
async def cmd_help(message: types.Message):
    """Команда /help – отправка списка команд."""
    await message.reply(config.get("help_message", "Доступные команды: ..."))

@dp.message_handler(commands=["rate"])
async def cmd_rate(message: types.Message):
    """Команда /rate – установка количества слов для проверки."""
    user_id = str(message.from_user.id)
    init_user(user_id)
    args = message.get_args()

    try:
        new_rate = int(args.strip())
        if new_rate < 1:
            raise ValueError
        user_data[user_id]["rate"] = new_rate
        save_user_data()
        await message.reply(f"Количество слов для проверки установлено: {new_rate}")
    except Exception:
        await message.reply("Используйте: /rate число (например, /rate 7)")

@dp.message_handler(commands=["quiz"])
async def cmd_quiz(message: types.Message):
    """Команда /quiz – запуск проверки слов."""
    user_id = str(message.from_user.id)
    init_user(user_id)
    data = user_data[user_id]

    if data.get("quiz"):
        await message.reply("У вас уже идёт проверка. Введите ответ или используйте /cancel для отмены.")
        return

    rate = data.get("rate", DEFAULT_RATE)

    if len(data["queue"]) < rate:
        data["queue"] = master_words.copy()

    words_for_quiz = data["queue"][:rate]
    data["queue"] = data["queue"][rate:]

    data["quiz"] = {
        "words": words_for_quiz,
        "index": 0
    }
    save_user_data()
    await send_question(user_id)

@dp.message_handler(commands=["cancel"])
async def cmd_cancel(message: types.Message):
    """Команда /cancel – отмена текущей проверки."""
    user_id = str(message.from_user.id)
    data = user_data.get(user_id)

    if data and data.get("quiz"):
        data["quiz"] = None
        save_user_data()
        await message.reply("Тест прерван.")
    else:
        await message.reply("Нет активного теста.")

@dp.message_handler()
async def answer_handler(message: types.Message):
    """Обработка ответов пользователей во время проверки."""
    user_id = str(message.from_user.id)
    data = user_data.get(user_id)

    if not data or not data.get("quiz"):
        return

    quiz = data["quiz"]
    index = quiz["index"]
    current_word = quiz["words"][index]
    correct = get_stress_letter(current_word)
    user_answer = message.text.strip().upper()

    if user_answer == correct:
        response_text = config.get("correct_text", "Верно!")
    else:
        response_text = config.get("incorrect_text", "Неверно. Правильный ответ: {correct}").format(correct=correct)
        data["queue"].append(current_word)

    await message.reply(response_text)
    quiz["index"] += 1

    if quiz["index"] < len(quiz["words"]):
        await send_question(user_id)
    else:
        await bot.send_message(user_id, config.get("quiz_complete", "Проверка завершена!"))
        data["quiz"] = None

    save_user_data()

async def daily_quiz_scheduler():
    """Фоновая задача, запускающая проверку слов каждый день в указанное время."""
    time_str = config.get("daily_quiz_time", "09:00")

    while True:
        now = datetime.datetime.now()
        target_time = datetime.datetime.strptime(time_str, "%H:%M").time()
        next_run = datetime.datetime.combine(now.date(), target_time)

        if next_run < now:
            next_run += datetime.timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        for user_id in list(user_data.keys()):
            data = user_data[user_id]
            if data.get("quiz") is None:
                if len(data["queue"]) < data.get("rate", DEFAULT_RATE):
                    data["queue"] = master_words.copy()
                rate = data.get("rate", DEFAULT_RATE)
                words_for_quiz = data["queue"][:rate]
                data["queue"] = data["queue"][rate:]
                data["quiz"] = {
                    "words": words_for_quiz,
                    "index": 0
                }
                save_user_data()
                try:
                    await bot.send_message(user_id, config.get("daily_quiz_start", "Начинается ежедневная проверка!"))
                    await send_question(user_id)
                except Exception as e:
                    logger.error(f"Ошибка отправки теста {user_id}: {e}")

async def on_startup(dp):
    """Запускает фоновую задачу при старте бота."""
    load_user_data()
    asyncio.create_task(daily_quiz_scheduler())

if __name__ == '__main__':
    executor.start_polling(dp, on_startup=on_startup)
