"""
Тест подключения к PostgreSQL.

Запуск ВНУТРИ Docker-сети:
    docker compose exec bot python test_db_connection.py

Запуск с хоста (если порт 5432 проброшен):
    DATABASE_URL=postgresql://bot:пароль@localhost:5432/invoice_bot python test_db_connection.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

dsn = os.getenv("DATABASE_URL")
if not dsn:
    print("ERROR: DATABASE_URL не задан в .env")
    sys.exit(1)

print(f"DSN: {dsn[:30]}...{dsn[-15:]}")
print("-" * 50)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("ERROR: psycopg2 не установлен. pip install psycopg2-binary")
    sys.exit(1)

# 1. Подключение
print("[1] Подключение к PostgreSQL...")
try:
    conn = psycopg2.connect(dsn)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    print("    OK — подключение установлено")
except Exception as e:
    print(f"    FAIL — {e}")
    sys.exit(1)

# 2. Версия PostgreSQL
cur.execute("SELECT version()")
row = cur.fetchone()
print(f"    Версия: {row['version'][:50]}...")

# 3. Проверка таблиц
print("\n[2] Таблицы в БД:")
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
""")
tables = [r["table_name"] for r in cur.fetchall()]

expected = [
    "profiles", "clients", "invoices", "invoice_items",
    "invoice_vat_breakdown", "offers", "offer_items",
    "offer_vat_breakdown", "document_files", "user_limits",
    "user_feedback", "data_deletion_logs", "document_archives",
    "invoice_attachments", "invoice_payments", "invoice_templates",
]

for t in expected:
    status = "OK" if t in tables else "MISSING"
    print(f"    {status:>7}  {t}")

missing = [t for t in expected if t not in tables]
if missing:
    print(f"\n    WARNING: {len(missing)} таблиц не найдено!")
    print("    Проверь что schema_full.sql применился при старте контейнера.")

# 4. Кол-во колонок в ключевых таблицах
print("\n[3] Количество колонок:")
for t in ["profiles", "invoices", "invoice_items", "clients", "offers"]:
    if t not in tables:
        continue
    cur.execute("""
        SELECT count(*) as cnt
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
    """, [t])
    cnt = cur.fetchone()["cnt"]
    print(f"    {t:20s} → {cnt} колонок")

# 5. Тест записи/чтения
print("\n[4] Тест записи/чтения (profiles)...")
TEST_ID = 999999999  # тестовый user_id

try:
    # Удаляем если остался от прошлого теста
    cur.execute("DELETE FROM profiles WHERE id = %s", [TEST_ID])
    conn.commit()

    # INSERT
    cur.execute("""
        INSERT INTO profiles (id, owner_name, company_name, country_code)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, [TEST_ID, "Test User", "Test GmbH", "DE"])
    conn.commit()
    row = cur.fetchone()
    print(f"    INSERT OK — id={row['id']}")

    # SELECT
    cur.execute("SELECT * FROM profiles WHERE id = %s", [TEST_ID])
    profile = cur.fetchone()
    print(f"    SELECT OK — company_name={profile['company_name']}, klein={profile['is_kleinunternehmer']}")

    # UPDATE
    cur.execute("UPDATE profiles SET is_kleinunternehmer = TRUE WHERE id = %s", [TEST_ID])
    conn.commit()
    cur.execute("SELECT is_kleinunternehmer FROM profiles WHERE id = %s", [TEST_ID])
    val = cur.fetchone()["is_kleinunternehmer"]
    print(f"    UPDATE OK — is_kleinunternehmer={val}")

    # DELETE
    cur.execute("DELETE FROM profiles WHERE id = %s", [TEST_ID])
    conn.commit()
    print("    DELETE OK — тестовая запись удалена")

except Exception as e:
    print(f"    FAIL — {e}")
    conn.rollback()

# 6. Итог
cur.close()
conn.close()

print("\n" + "=" * 50)
if not missing:
    print("ВСЁ ОК! База готова к работе.")
else:
    print(f"ВНИМАНИЕ: {len(missing)} таблиц отсутствует.")
print("=" * 50)
