-- ============================================
-- ОБНОВЛЕНИЕ СХЕМЫ БД ДЛЯ INVOICE BOT
-- ============================================

-- 1. Таблица для хранения PDF/ZUGFeRD файлов
CREATE TABLE IF NOT EXISTS document_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    document_type VARCHAR(20) NOT NULL, -- 'invoice' или 'offer'
    document_id UUID NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_data BYTEA NOT NULL, -- бинарные данные PDF
    file_size INTEGER NOT NULL,
    mime_type VARCHAR(100) DEFAULT 'application/pdf',
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_document_files_user ON document_files(user_id);
CREATE INDEX IF NOT EXISTS idx_document_files_doc ON document_files(document_id);

-- 2. Обновление таблицы offers - добавить недостающие поля для ZUGFeRD
ALTER TABLE offers ADD COLUMN IF NOT EXISTS vat_mode VARCHAR(20) DEFAULT 'standard';
ALTER TABLE offers ADD COLUMN IF NOT EXISTS vat_per_item BOOLEAN DEFAULT FALSE;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS global_vat_rate DECIMAL(5,2) DEFAULT 19.00;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS discount_percentage DECIMAL(5,2) DEFAULT 0;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(10,2) DEFAULT 0;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS shipping_cost DECIMAL(10,2) DEFAULT 0;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS shipping_vat_rate DECIMAL(5,2) DEFAULT 19.00;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS net_amount DECIMAL(10,2);
ALTER TABLE offers ADD COLUMN IF NOT EXISTS vat_amount DECIMAL(10,2);
ALTER TABLE offers ADD COLUMN IF NOT EXISTS gross_amount DECIMAL(10,2);
ALTER TABLE offers ADD COLUMN IF NOT EXISTS payment_terms VARCHAR(255);
ALTER TABLE offers ADD COLUMN IF NOT EXISTS delivery_date DATE;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS valid_until DATE;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS pdf_file_id UUID;
ALTER TABLE offers ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT FALSE; -- блокировка после создания счёта
ALTER TABLE offers ADD COLUMN IF NOT EXISTS offer_date DATE DEFAULT CURRENT_DATE;

-- 3. Создание таблицы для детализации НДС по офферам (аналог invoice_vat_breakdown)
CREATE TABLE IF NOT EXISTS offer_vat_breakdown (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    offer_id UUID NOT NULL,
    vat_rate DECIMAL(5,2) NOT NULL,
    taxable_amount DECIMAL(10,2) NOT NULL,
    vat_amount DECIMAL(10,2) NOT NULL,
    vat_category_code VARCHAR(5),
    vat_exemption_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_offer_vat_breakdown ON offer_vat_breakdown(offer_id);

-- 4. Обновление таблицы offer_items - добавить поля для расчётов
ALTER TABLE offer_items ADD COLUMN IF NOT EXISTS total_price DECIMAL(10,2);
ALTER TABLE offer_items ADD COLUMN IF NOT EXISTS vat_rate DECIMAL(5,2) DEFAULT 19.00;
ALTER TABLE offer_items ADD COLUMN IF NOT EXISTS vat_amount DECIMAL(10,2);
ALTER TABLE offer_items ADD COLUMN IF NOT EXISTS vat_category_code VARCHAR(5);
ALTER TABLE offer_items ADD COLUMN IF NOT EXISTS unit_code VARCHAR(10) DEFAULT 'C62';

-- 5. Таблица для отслеживания лимитов пользователей
CREATE TABLE IF NOT EXISTS user_limits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT UNIQUE NOT NULL,
    plan_type VARCHAR(20) DEFAULT 'free', -- 'free' или 'paid'
    invoices_limit INTEGER DEFAULT 5, -- лимит счетов в месяц для free
    invoices_this_month INTEGER DEFAULT 0,
    current_period_start DATE DEFAULT CURRENT_DATE,
    payment_status VARCHAR(20) DEFAULT 'none', -- 'none', 'pending', 'active'
    paid_until DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_limits_user ON user_limits(user_id);

-- 6. Обновление таблицы invoices - добавить блокировку редактирования
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT FALSE;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS pdf_file_id UUID;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP;

-- 7. Таблица для логов удаления данных
CREATE TABLE IF NOT EXISTS data_deletion_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    deletion_type VARCHAR(50) NOT NULL, -- 'full', 'invoices', 'offers', etc
    items_deleted INTEGER DEFAULT 0,
    requested_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- 8. Таблица для хранения архивов документов
CREATE TABLE IF NOT EXISTS document_archives (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    email VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'processing', 'sent', 'failed'
    archive_size INTEGER,
    documents_count INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    sent_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- 9. Таблица для обратной связи
CREATE TABLE IF NOT EXISTS user_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    feedback_type VARCHAR(50) DEFAULT 'general', -- 'general', 'bug', 'feature', 'cooperation'
    subject VARCHAR(255),
    message TEXT NOT NULL,
    contact_email VARCHAR(255),
    status VARCHAR(20) DEFAULT 'new', -- 'new', 'read', 'replied'
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_feedback_user ON user_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON user_feedback(status);

-- 10. Добавление полей в profiles для PayPal и email
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS user_email VARCHAR(255);
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS accepted_terms BOOLEAN DEFAULT FALSE;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS accepted_terms_date TIMESTAMP;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS total_donations DECIMAL(10,2) DEFAULT 0;

-- 11. Функция для автоматического сброса лимитов каждый месяц
CREATE OR REPLACE FUNCTION reset_monthly_limits()
RETURNS void AS $$
BEGIN
    UPDATE user_limits
    SET invoices_this_month = 0,
        current_period_start = CURRENT_DATE,
        updated_at = NOW()
    WHERE current_period_start < DATE_TRUNC('month', CURRENT_DATE);
END;
$$ LANGUAGE plpgsql;

-- Можно настроить cron job для вызова этой функции раз в день:
-- SELECT cron.schedule('reset-limits', '0 0 * * *', 'SELECT reset_monthly_limits()');

-- 12. Триггер для автоблокировки счёта после создания PDF
CREATE OR REPLACE FUNCTION lock_invoice_after_pdf()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.pdf_file_id IS NOT NULL AND OLD.pdf_file_id IS NULL THEN
        NEW.is_locked := TRUE;
        NEW.locked_at := NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER invoice_lock_trigger
BEFORE UPDATE ON invoices
FOR EACH ROW
EXECUTE FUNCTION lock_invoice_after_pdf();

-- 13. Аналогичный триггер для офферов
CREATE OR REPLACE FUNCTION lock_offer_after_invoice()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.converted_to_invoice_id IS NOT NULL AND OLD.converted_to_invoice_id IS NULL THEN
        NEW.is_locked := TRUE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER offer_lock_trigger
BEFORE UPDATE ON offers
FOR EACH ROW
EXECUTE FUNCTION lock_offer_after_invoice();

-- Комментарии к таблицам
COMMENT ON TABLE document_files IS 'Хранение PDF/ZUGFeRD файлов в БД';
COMMENT ON TABLE offer_vat_breakdown IS 'Детализация НДС по офферам для ZUGFeRD';
COMMENT ON TABLE user_limits IS 'Лимиты пользователей для free/paid режимов';
COMMENT ON TABLE data_deletion_logs IS 'Логи удаления пользовательских данных';
COMMENT ON TABLE document_archives IS 'Архивы документов для отправки на email';
COMMENT ON TABLE user_feedback IS 'Обратная связь от пользователей';
