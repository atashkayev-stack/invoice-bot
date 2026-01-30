import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ANTHROPIC_API_KEY")

print(f"--- Тест связи с Anthropic ---")
print(f"Использую ключ: {api_key[:15]}...")

url = "https://api.anthropic.com/v1/messages"
headers = {
    "x-api-key": api_key,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json"
}

# Тестируем самую простую модель Haiku
data = {
    "model": "claude-3-haiku-20240307",
    "max_tokens": 10,
    "messages": [{"role": "user", "content": "Hello"}]
}

try:
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        print("✅ УСПЕХ! Связь есть.")
        print("Ответ Claude:", response.json()['content'][0]['text'])
    else:
        print(f"❌ ОШИБКА {response.status_code}")
        print("Текст ошибки:", response.text)
except Exception as e:
    print(f"❌ Не удалось даже отправить запрос: {e}")