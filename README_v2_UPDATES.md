# RechnungAgent Bot v2.0 - Обновления

## 🆕 Что нового в этой версии

### 1. ✅ Полная логика расчётов для Offer (Angebote)
- Добавлена таблица `offer_vat_breakdown` для детализации НДС
- Метод `compute_offer_financials()` аналогично invoice
- Полная цепочка вычислений: скидки → доставка → НДС → итоги
- Все расчёты происходят на сервере, результаты сохраняются в БД

### 2. 💾 Хранение файлов в БД
- Таблица `document_files` для хранения PDF/ZUGFeRD файлов
- Автоматическая блокировка документов после создания PDF
- Защита от редактирования выставленных счетов

### 3. 📊 Списки документов
- **invoices_list.html** - красивый список счетов с фильтрацией
- **offers_list.html** - список офферов с возможностью конвертации
- Статистика по месяцам
- Быстрый доступ к PDF

### 4. 📋 Копирование документов
- Кнопка "Копировать" для счетов и офферов
- Автоматическая генерация нового номера
- Сохранение всех позиций и настроек

### 5. 💎 Платный режим
- Таблица `user_limits` для отслеживания лимитов
- Free: 5 счетов в месяц (настраивается)
- Pro: неограниченно + хранение всех документов
- Предупреждения при достижении лимита

### 6. 🗑️ Удаление всех данных
- Полное удаление всех данных пользователя
- Подтверждение перед удалением
- Логирование в `data_deletion_logs`

### 7. 📦 Архив документов
- Запрос архива всех документов
- Отправка ZIP на email
- Таблица `document_archives` для отслеживания

### 8. 📧 Обратная связь
- Форма "Написать разработчику"
- Категории: предложение, баг, сотрудничество
- Хранение в `user_feedback`

### 9. ☕ PayPal благодарности
- Кнопка "Сказать спасибо" после создания счёта
- Ссылка на PayPal (настраивается)

### 10. 📜 Условия использования
- Файл terms_of_service.html
- Защита разработчика от претензий
- Юридический disclaimer

### 11. 🎨 Улучшенные шаблоны
- Двухколоночная layout для реквизитов
- Красивые итоговые таблицы
- Breakdown по ставкам НДС

### 12. 🔒 Блокировка документов
- Автоматическая блокировка после генерации PDF
- Триггеры в БД для автоблокировки
- Невозможность редактирования после отправки

## 📁 Структура новых файлов

```
invoice_bot_updated/
├── database/
│   └── schema_updates.sql         # SQL скрипт для обновления БД
├── docs/
│   ├── create_offer_v3.html       # Обновлённая форма offer
│   ├── invoices_list.html         # Список счетов
│   ├── offers_list.html           # Список офферов
│   ├── terms_of_service.html      # Условия использования
│   └── terms_of_service.md        # Текст условий
└── src/
    ├── database_v1.py             # Обновлённый модуль БД
    └── handlers_v1.py             # Новые обработчики
```

## 🚀 Установка обновлений

### 1. Обновление базы данных
```sql
-- Выполните schema_updates.sql в вашей Supabase БД
psql -h your-db-host -U postgres -d your-db < database/schema_updates.sql
```

### 2. Обновление кода
```bash
# Замените старые файлы новыми:
cp src/database_v1.py /path/to/your/project/src/
cp src/handlers_v1.py /path/to/your/project/src/

# Скопируйте новые HTML файлы:
cp docs/*.html /path/to/your/github-pages/
```

### 3. Конфигурация

#### В `config_v1.py` обновите URL:
```python
CREATE_OFFER_FORM_URL = f"{BASE_URL}/create_offer_v3.html?v={VERSION}"
```

#### Настройте PayPal:
В файле `handlers_v1.py` найдите функцию `show_donation_message()` и замените:
```python
url="https://paypal.me/YOURPAYPAL"  # <- Ваша ссылка
```

#### Настройте лимиты:
В SQL скрипте измените дефолтный лимит (по умолчанию 5):
```sql
invoices_limit INTEGER DEFAULT 5,  -- <- Ваш лимит
```

### 4. Обновление main_v1.py

Добавьте новые handlers в `main_v1.py`:
```python
# Callback handlers для новых функций
app.add_handler(CallbackQueryHandler(
    handlers_v1.handle_confirm_delete, pattern="^confirm_delete_"))
app.add_handler(CallbackQueryHandler(
    handlers_v1.handle_feedback_callback, pattern="^feedback_"))

# Command handlers
app.add_handler(CommandHandler("upgrade", handlers_v1.show_upgrade_info))
app.add_handler(CommandHandler("delete", handlers_v1.delete_all_data_handler))
app.add_handler(CommandHandler("archive", handlers_v1.request_documents_archive))
app.add_handler(CommandHandler("feedback", handlers_v1.show_feedback_form))
```

## ⚙️ Настройка для WhatsApp (TODO)

В текущей версии подготовлена структура, но интеграция с WhatsApp требует:
1. Регистрация в WhatsApp Business API
2. Настройка webhooks
3. Адаптация handlers для WhatsApp формата
4. Тестирование

Пример заглушки в `config_v1.py`:
```python
WHATSAPP_ENABLED = False  # Включить когда готово
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_TOKEN")
```

## 🧪 Тестирование

### Проверочный список:
- [ ] SQL скрипт выполнен без ошибок
- [ ] Создание offer с расчётами работает
- [ ] Создание invoice проверяет лимит
- [ ] Списки документов отображаются
- [ ] Копирование работает
- [ ] Кнопка удаления данных функционирует
- [ ] Terms of Service открываются
- [ ] PayPal ссылка правильная
- [ ] ZUGFeRD 2.4 генерируется корректно

### Тестовый сценарий:
```bash
1. Создайте тестового пользователя
2. Создайте 3 счета (проверка лимита)
3. Создайте offer и конвертируйте в invoice
4. Скопируйте invoice
5. Откройте список документов
6. Запросите архив (проверка email)
7. Отправьте feedback
8. Удалите все данные
```

## ⚠️ Важные замечания

### Логика расчётов (п.15 из ТЗ)
Как договорились:
1. **На форме** - визуальный preview расчётов (JavaScript)
2. **На сервере** (`database_v1.py`) - КАНОНИЧЕСКИЕ расчёты
3. **В БД** - сохраняются ТОЛЬКО серверные значения
4. **В PDF/XML** - берутся ТОЛЬКО из БД

### Порядок расчётов:
```
Items (quantity × price) 
  → Subtotal
  → Discount (% или фиксир.)
  → После скидки = база для НДС
  → НДС по ставкам
  → Shipping + НДС на доставку
  → GROSS TOTAL
```

### Формат ZUGFeRD 2.4
Все поля для XML уже подготовлены:
- `vat_category_code` (S, E, AE, G, Z)
- `exemption_reason` для klein/reverse/export
- Breakdown по ставкам
- Unit codes (UNECE Rec.20)

Проверка XML будет в финальной стадии.

## 📝 TODO для финализации

1. **Архивация документов** - фоновая задача для создания ZIP
2. **Email отправка** - интеграция SMTP или SendGrid
3. **Платёжная система** - Stripe/PayPal интеграция для Pro
4. **WhatsApp** - полная интеграция
5. **Уведомления** - напоминания о лимитах/платежах
6. **Аналитика** - dashboard для пользователей

## 🐛 Известные проблемы

- Архив документов пока заглушка (нужен background worker)
- Email отправка требует настройки SMTP
- WhatsApp не реализован
- Payment gateway не интегрирован

## 📞 Поддержка

Для вопросов используйте:
- Feedback форма в боте
- GitHub Issues
- Email: your-email@example.com

---

**Версия:** 2.0  
**Дата:** Февраль 2026  
**Автор:** RechnungAgent Team

© 2026 RechnungAgent - Все права защищены
