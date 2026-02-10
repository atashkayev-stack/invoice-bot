# ДОБАВИТЬ В main_v1.py

## В секцию CallbackQueryHandler добавить:

```python
# Обработчики принятия условий
app.add_handler(CallbackQueryHandler(
    handlers_v1.handle_toggle_terms, 
    pattern="^toggle_terms$"
))

app.add_handler(CallbackQueryHandler(
    handlers_v1.handle_accept_terms_invoice, 
    pattern="^accept_terms_invoice$"
))

app.add_handler(CallbackQueryHandler(
    handlers_v1.handle_accept_terms_offer, 
    pattern="^accept_terms_offer$"
))
```

## Полный пример секции:

```python
# Callback handlers
app.add_handler(CallbackQueryHandler(
    handlers_v1.handle_toggle_terms, 
    pattern="^toggle_terms$"
))

app.add_handler(CallbackQueryHandler(
    handlers_v1.handle_accept_terms_invoice, 
    pattern="^accept_terms_invoice$"
))

app.add_handler(CallbackQueryHandler(
    handlers_v1.handle_accept_terms_offer, 
    pattern="^accept_terms_offer$"
))

# Остальные callback handlers...
```

## Где в файле:

Найди строку где уже есть `CallbackQueryHandler` и добавь эти три handler'а.
