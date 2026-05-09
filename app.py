import os
import random
import re
import json
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request

app = Flask(__name__)


def load_env_file() -> None:
    env_path = ".env"
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env_file()


# Здесь можно менять стиль генератора: тон, длину, эмодзи, CTA и хештеги.
STYLE_PRESETS = {
    "tone": {
        "friendly": "дружелюбный",
        "expert": "экспертный",
        "energetic": "энергичный",
    },
    "length": {
        "short": "короткий",
        "medium": "средний",
        "long": "подробный",
    },
    "emoji": {
        "low": ["✨"],
        "medium": ["✨", "🔥"],
        "high": ["✨", "🔥", "💡", "🛍️"],
    },
    "cta": {
        "soft": "Напишите в сообщения, и я помогу выбрать лучший вариант для вас.",
        "direct": "Оформляйте заказ прямо сейчас и забирайте выгодное предложение!",
        "urgent": "Количество ограничено — успейте заказать сегодня!",
    },
    "hashtags": {
        "classic": ["#покупка", "#выгодно", "#товары", "#лучшийвыбор"],
        "sales": ["#акция", "#скидка", "#горячеепредложение", "#успейкупить"],
        "brand": ["#качество", "#стиль", "#длявас", "#провереновременем"],
    },
}


EMOTIONS = [
    "восторг",
    "уют",
    "доверие",
    "удивление",
    "вдохновение",
    "радость",
]


MODEL_OPTIONS = {
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4": "gpt-5.4",
    "gpt-5.5": "gpt-5.5",
}

VK_API_VERSION = "5.199"
FAVORITES_FILE = "favorites.json"
SCHEDULED_FILE = "scheduled_posts.json"


def read_json_file(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, OSError):
        return []
    return []


def write_json_file(path: str, data: list) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def parse_product_page(product_url: str) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        )
    }

    response = requests.get(product_url, headers=headers, timeout=15)
    html_text = response.text if response.ok else ""

    if not html_text:
        return {
            "title": extract_title_from_url(product_url),
            "description": "",
            "content": "",
            "source_status": f"http_{response.status_code}",
        }

    soup = BeautifulSoup(html_text, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""

    meta_description = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_description = meta_tag["content"].strip()

    text_blocks = []
    for tag in soup.find_all(["h1", "h2", "p", "li"], limit=120):
        text = tag.get_text(" ", strip=True)
        if len(text) >= 30:
            text_blocks.append(text)

    page_text = "\n".join(text_blocks)
    page_text = re.sub(r"\s+", " ", page_text).strip()

    return {
        "title": title,
        "description": meta_description,
        "content": page_text[:5000],
        "source_status": "ok",
    }


def extract_title_from_url(product_url: str) -> str:
    parsed = urlparse(product_url)
    segments = [segment for segment in parsed.path.split("/") if segment]

    slug = ""
    for segment in segments:
        if segment != "product":
            slug = segment
            break

    slug = re.sub(r"-\d+$", "", slug)
    slug = slug.replace("-", " ").strip()
    if not slug:
        return "Товар по ссылке"

    return slug.capitalize()


def generate_post_with_llm(form_data: dict) -> str:
    api_key = os.getenv("PROXYAPI_KEY", "").strip()
    if not api_key:
        return "Не найден ключ ProxyAPI. Добавьте ключ в переменную окружения PROXYAPI_KEY."

    product_url = form_data.get("product_url", "").strip()
    tone = form_data.get("tone", "friendly")
    length = form_data.get("length", "medium")
    emoji_level = form_data.get("emoji", "medium")
    cta_style = form_data.get("cta", "soft")
    hashtag_style = form_data.get("hashtags", "classic")
    model = form_data.get("model", "gpt-5.4-mini")
    model = MODEL_OPTIONS.get(model, "gpt-5.4-mini")

    try:
        page_info = parse_product_page(product_url)
    except requests.RequestException:
        page_info = {
            "title": extract_title_from_url(product_url),
            "description": "",
            "content": "",
            "source_status": "fetch_error",
        }
    emotion = random.choice(EMOTIONS)

    system_prompt = (
        "Ты редактор продающих постов для соцсетей. "
        "Пиши оригинально, без шаблонных фраз. "
        "Верни только готовый текст поста без служебных меток и без названий разделов."
    )

    source_warning = ""
    if page_info.get("source_status") != "ok":
        source_warning = (
            "Источник ограничил доступ к содержимому страницы. "
            "Опирайся на название из ссылки и пиши аккуратно, без выдуманных фактов."
        )

    user_prompt = f"""
Сгенерируй пост по товару на русском языке.

Настройки:
- Тон: {STYLE_PRESETS['tone'].get(tone, 'дружелюбный')}
- Длина: {STYLE_PRESETS['length'].get(length, 'средний')}
- Уровень эмодзи: {emoji_level}
- Стиль CTA: {cta_style}
- Стиль хештегов: {hashtag_style}
- Эмоция поста: {emotion}

Источник товара:
- Ссылка: {product_url}
- Заголовок страницы: {page_info['title']}
- Meta description: {page_info['description']}
- Фрагменты страницы: {page_info['content']}
- Статус чтения страницы: {page_info.get('source_status', 'unknown')}
- Дополнительная инструкция: {source_warning}

Требования:
- Не выдумывай характеристики, которых нет в данных.
- Сделай текст интересным, но правдоподобным.
- Эмодзи добавляй естественно внутри заголовка, основного текста, блока пользы и CTA.
- Не делай отдельный блок или строку только из эмодзи.
- Добавь 3-5 релевантных хештегов.
- CTA должен быть в конце и побуждать к действию.
- Нельзя писать названия разделов: "Заголовок", "Основной текст", "Польза", "CTA", "Хештеги".
- Нельзя использовать нумерацию разделов вида "1)", "2)", "3)".
""".strip()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        "https://api.proxyapi.ru/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=40,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def clean_post_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^\s*\d+[\).:-]\s*\*{0,2}\s*[^\n]{0,40}\n", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(
        r"^\s*\*{0,2}\s*(заголовок|основной текст|польза.*|cta|хештеги|эмодзи)\s*\*{0,2}\s*[:.-]?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def publish_to_vk(text: str, publish_at: Optional[int] = None) -> dict:
    vk_token = os.getenv("VK_ACCESS_TOKEN", "").strip()
    vk_group_id = os.getenv("VK_GROUP_ID", "").strip()

    if not vk_token or not vk_group_id:
        return {
            "ok": False,
            "message": "Не заполнены VK_ACCESS_TOKEN или VK_GROUP_ID в .env",
        }

    if not vk_group_id.isdigit():
        return {
            "ok": False,
            "message": "VK_GROUP_ID должен быть числом (без минуса).",
        }

    params = {
        "owner_id": f"-{vk_group_id}",
        "from_group": 1,
        "message": text,
        "access_token": vk_token,
        "v": VK_API_VERSION,
    }

    if publish_at is not None:
        params["publish_date"] = publish_at

    response = requests.post("https://api.vk.com/method/wall.post", data=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        error_data = data["error"]
        error_code = error_data.get("error_code")
        error_msg = error_data.get("error_msg", "Unknown error")

        if error_code == 8:
            return {
                "ok": False,
                "message": (
                    "VK API ошибка 8: приложение/токен заблокированы или неподходящие. "
                    "Создайте новый сервисный ключ в сообществе VK (Управление -> Работа с API -> Ключи доступа), "
                    "выдайте право wall, обновите VK_ACCESS_TOKEN в .env и перезапустите Flask."
                ),
            }

        return {
            "ok": False,
            "message": f"VK API ошибка {error_code}: {error_msg}",
        }

    post_id = data.get("response", {}).get("post_id")
    return {
        "ok": True,
        "message": f"Пост опубликован во ВКонтакте. ID поста: {post_id}",
    }


def parse_schedule_datetime(value: str) -> int:
    planned_dt = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    return int(planned_dt.timestamp())

@app.route("/", methods=["GET", "POST"])
def index():
    post_text = ""
    error_message = ""
    status_message = ""
    product_url = ""
    selected = {
        "tone": "friendly",
        "length": "medium",
        "emoji": "medium",
        "cta": "soft",
        "hashtags": "classic",
        "model": "gpt-5.4-mini",
    }

    if request.method == "POST":
        forced_action = request.form.get("force_action", "").strip()
        action = forced_action or request.form.get("action", "generate")
        product_url = request.form.get("product_url", "").strip()
        post_text = request.form.get("post_text", "").strip()
        selected = {
            "tone": request.form.get("tone", "friendly"),
            "length": request.form.get("length", "medium"),
            "emoji": request.form.get("emoji", "medium"),
            "cta": request.form.get("cta", "soft"),
            "hashtags": request.form.get("hashtags", "classic"),
            "model": request.form.get("model", "gpt-5.4-mini"),
        }

        if action == "generate":
            if not product_url:
                error_message = "Добавьте ссылку на товар"
            else:
                try:
                    generated_text = generate_post_with_llm(request.form)
                    post_text = clean_post_text(generated_text)
                except requests.RequestException:
                    error_message = "Не удалось получить данные товара или ответ модели. Проверьте ссылку и ключ API."
                except (KeyError, IndexError, TypeError, ValueError):
                    error_message = "Модель вернула неожиданный ответ. Попробуйте снова."

        if action == "publish":
            if not post_text:
                error_message = "Сначала сформируйте или вставьте текст поста"
            else:
                try:
                    vk_text = clean_post_text(post_text)
                    result = publish_to_vk(vk_text)
                    if result["ok"]:
                        status_message = result["message"]
                    else:
                        error_message = result["message"]
                except requests.RequestException:
                    error_message = "Не удалось отправить пост во ВКонтакте. Проверьте токен и доступы."

        if action == "schedule":
            planned_time = request.form.get("publish_time", "").strip()
            if not post_text:
                error_message = "Сначала сформируйте или вставьте текст поста"
            elif not planned_time:
                error_message = "Выберите время для отложенной публикации"
            else:
                try:
                    publish_ts = parse_schedule_datetime(planned_time)
                    now_ts = int(datetime.now().timestamp())
                    if publish_ts <= now_ts:
                        error_message = "Время публикации должно быть в будущем"
                    else:
                        vk_text = clean_post_text(post_text)
                        result = publish_to_vk(vk_text, publish_at=publish_ts)
                        if result["ok"]:
                            status_message = f"Отложенный пост создан на {planned_time.replace('T', ' ')}"
                            scheduled_items = read_json_file(SCHEDULED_FILE)
                            scheduled_items.insert(
                                0,
                                {
                                    "text": vk_text,
                                    "publish_time": planned_time,
                                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                },
                            )
                            write_json_file(SCHEDULED_FILE, scheduled_items[:20])
                        else:
                            error_message = result["message"]
                except ValueError:
                    error_message = "Некорректный формат времени"
                except requests.RequestException:
                    error_message = "Не удалось создать отложенный пост во ВКонтакте"

        if action == "favorite":
            if not post_text:
                error_message = "Сначала сформируйте или вставьте текст поста"
            else:
                favorite_text = clean_post_text(post_text)
                favorites = read_json_file(FAVORITES_FILE)
                favorites.insert(
                    0,
                    {
                        "text": favorite_text,
                        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    },
                )
                write_json_file(FAVORITES_FILE, favorites[:30])
                status_message = "Пост добавлен в избранное"

        if action == "save_edit":
            if not post_text:
                error_message = "Нет текста для сохранения"
            else:
                post_text = post_text.strip()
                status_message = "Правки сохранены"

    favorites = read_json_file(FAVORITES_FILE)[:5]
    scheduled_posts = read_json_file(SCHEDULED_FILE)[:5]

    return render_template(
        "index.html",
        post_text=post_text,
        error_message=error_message,
        status_message=status_message,
        product_url=product_url,
        selected=selected,
        model_options=MODEL_OPTIONS,
        favorites=favorites,
        scheduled_posts=scheduled_posts,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5500, debug=True)
