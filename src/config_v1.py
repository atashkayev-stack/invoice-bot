import time

GITHUB_USERNAME = "atashkayev-stack"
BASE_URL = f"https://{GITHUB_USERNAME}.github.io/invoice-bot"

# Автоматическая версия (timestamp)
VERSION = int(time.time())  # Меняется каждый раз при перезапуске бота

# ФИНАЛЬНЫЕ ВЕРСИИ ФОРМ (новые имена)
SETTINGS_FORM_URL = f"{BASE_URL}/company_settings_FINAL.html?v={VERSION}"
CREATE_INVOICE_FORM_URL = f"{BASE_URL}/invoice_form_FINAL.html?v={VERSION}"
CREATE_OFFER_FORM_URL = f"{BASE_URL}/offer_form_FINAL.html?v={VERSION}"

CLAUDE_MODEL = "claude-3-haiku-20240307"
CONVERSATION_TIMEOUT = 900
INVOICE_FORMATS = ["ZUGFeRD", "XRechnung"]
UNITS = ["Stk", "Std", "Tag", "kg", "m", "m²", "m³", "km", "l"]
VAT_RATES = {"STANDARD": 19, "REDUCED": 7, "ZERO": 0}
