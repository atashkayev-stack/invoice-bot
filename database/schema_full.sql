-- ============================================
-- ПОЛНАЯ СХЕМА БД — INVOICE BOT (PostgreSQL)
-- Запускается при первом старте контейнера
-- ============================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============ PROFILES ============
CREATE TABLE IF NOT EXISTS profiles (
    id BIGINT PRIMARY KEY,                          -- telegram user_id
    owner_name VARCHAR(255),
    username VARCHAR(255),
    company_name VARCHAR(255),
    legal_form VARCHAR(100) DEFAULT 'Einzelunternehmer',
    street VARCHAR(255) DEFAULT '',
    postal_code VARCHAR(20) DEFAULT '',
    city VARCHAR(255) DEFAULT '',
    country_code VARCHAR(5) DEFAULT 'DE',
    phone VARCHAR(50),
    email VARCHAR(255),
    website VARCHAR(255),
    tax_id VARCHAR(50),
    vat_id VARCHAR(50),
    bank_name VARCHAR(255),
    iban VARCHAR(50),
    bic VARCHAR(20),
    paypal_email VARCHAR(255),
    invoice_number_prefix VARCHAR(20) DEFAULT 'RE-',
    invoice_number_format INTEGER DEFAULT 4,
    next_invoice_number INTEGER DEFAULT 1,
    offer_number_prefix VARCHAR(20) DEFAULT 'ANG-',
    offer_number_format INTEGER DEFAULT 4,
    next_offer_number INTEGER DEFAULT 1,
    customer_id_prefix VARCHAR(20) DEFAULT 'KUND-',
    next_customer_number INTEGER DEFAULT 1,
    default_vat_rate DECIMAL(5,2) DEFAULT 19.00,
    is_kleinunternehmer BOOLEAN DEFAULT FALSE,
    payment_terms_days INTEGER DEFAULT 14,
    user_email VARCHAR(255),
    accepted_terms BOOLEAN DEFAULT FALSE,
    accepted_terms_date TIMESTAMP,
    total_donations DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============ CLIENTS ============
CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    customer_id VARCHAR(50),
    company_name VARCHAR(255),
    contact_name VARCHAR(255),
    street VARCHAR(255),
    postal_code VARCHAR(20),
    city VARCHAR(255),
    country_code VARCHAR(5) DEFAULT 'DE',
    email VARCHAR(255),
    phone VARCHAR(50),
    vat_id VARCHAR(50),
    client_type VARCHAR(10) DEFAULT 'b2b',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clients_user ON clients(user_id);

-- ============ INVOICES ============
CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    client_id UUID,
    number VARCHAR(50),
    invoice_date DATE DEFAULT CURRENT_DATE,
    delivery_date DATE,
    client_name VARCHAR(255),
    client_address TEXT,
    customer_id VARCHAR(50),
    purchase_order_number VARCHAR(100),
    amount DECIMAL(12,2),
    vat_amount DECIMAL(12,2),
    vat_rate DECIMAL(5,2),
    total DECIMAL(12,2),
    vat_mode VARCHAR(20) DEFAULT 'standard',
    vat_per_item BOOLEAN DEFAULT FALSE,
    global_vat_rate VARCHAR(20),
    discount_percentage DECIMAL(5,2) DEFAULT 0,
    discount_amount DECIMAL(12,2) DEFAULT 0,
    shipping_cost DECIMAL(12,2) DEFAULT 0,
    shipping_vat_rate DECIMAL(5,2) DEFAULT 0,
    format_type VARCHAR(20) DEFAULT 'ZUGFeRD',
    notes TEXT,
    status VARCHAR(20) DEFAULT 'draft',
    payment_terms VARCHAR(255),
    payment_means VARCHAR(50),
    is_locked BOOLEAN DEFAULT FALSE,
    locked_at TIMESTAMP,
    pdf_file_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoices_user ON invoices(user_id);

-- ============ INVOICE ITEMS ============
CREATE TABLE IF NOT EXISTS invoice_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    position_number INTEGER,
    description TEXT,
    quantity DECIMAL(12,4),
    unit VARCHAR(20),
    unit_code VARCHAR(10) DEFAULT 'C62',
    unit_price DECIMAL(12,2),
    total_price DECIMAL(12,2),
    vat_rate DECIMAL(5,2),
    vat_amount DECIMAL(12,2),
    vat_category_code VARCHAR(5),
    article_number VARCHAR(100),
    ean_code VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoice_items ON invoice_items(invoice_id);

-- ============ INVOICE VAT BREAKDOWN ============
CREATE TABLE IF NOT EXISTS invoice_vat_breakdown (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    vat_rate DECIMAL(5,2) NOT NULL,
    taxable_amount DECIMAL(12,2) NOT NULL,
    vat_amount DECIMAL(12,2) NOT NULL,
    vat_category_code VARCHAR(5),
    exemption_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoice_vat ON invoice_vat_breakdown(invoice_id);

-- ============ OFFERS ============
CREATE TABLE IF NOT EXISTS offers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    client_id UUID,
    offer_number VARCHAR(50),
    offer_date DATE DEFAULT CURRENT_DATE,
    client_name VARCHAR(255),
    client_address TEXT,
    customer_id VARCHAR(50),
    purchase_order_number VARCHAR(100),
    amount DECIMAL(12,2),
    vat_rate DECIMAL(5,2),
    total DECIMAL(12,2),
    net_amount DECIMAL(12,2),
    vat_amount DECIMAL(12,2),
    gross_amount DECIMAL(12,2),
    vat_mode VARCHAR(20) DEFAULT 'standard',
    vat_per_item BOOLEAN DEFAULT FALSE,
    global_vat_rate DECIMAL(5,2) DEFAULT 19.00,
    discount_percentage DECIMAL(5,2) DEFAULT 0,
    discount_amount DECIMAL(12,2) DEFAULT 0,
    shipping_cost DECIMAL(12,2) DEFAULT 0,
    shipping_vat_rate DECIMAL(5,2) DEFAULT 19.00,
    format_type VARCHAR(20) DEFAULT 'ZUGFeRD',
    notes TEXT,
    status VARCHAR(20) DEFAULT 'draft',
    payment_terms VARCHAR(255),
    delivery_date DATE,
    valid_until DATE,
    pdf_file_id UUID,
    is_locked BOOLEAN DEFAULT FALSE,
    converted_to_invoice_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_offers_user ON offers(user_id);

-- ============ OFFER ITEMS ============
CREATE TABLE IF NOT EXISTS offer_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    offer_id UUID NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    position_number INTEGER,
    description TEXT,
    quantity DECIMAL(12,4),
    unit VARCHAR(20),
    unit_code VARCHAR(10) DEFAULT 'C62',
    unit_price DECIMAL(12,2),
    total_price DECIMAL(12,2),
    vat_rate DECIMAL(5,2) DEFAULT 19.00,
    vat_amount DECIMAL(12,2),
    vat_category_code VARCHAR(5),
    article_number VARCHAR(100),
    ean_code VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_offer_items ON offer_items(offer_id);

-- ============ OFFER VAT BREAKDOWN ============
CREATE TABLE IF NOT EXISTS offer_vat_breakdown (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    offer_id UUID NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    vat_rate DECIMAL(5,2) NOT NULL,
    taxable_amount DECIMAL(12,2) NOT NULL,
    vat_amount DECIMAL(12,2) NOT NULL,
    vat_category_code VARCHAR(5),
    vat_exemption_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_offer_vat ON offer_vat_breakdown(offer_id);

-- ============ DOCUMENT FILES ============
CREATE TABLE IF NOT EXISTS document_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    document_type VARCHAR(20) NOT NULL,
    document_id UUID NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_data BYTEA NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type VARCHAR(100) DEFAULT 'application/pdf',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_files_user ON document_files(user_id);
CREATE INDEX IF NOT EXISTS idx_doc_files_doc ON document_files(document_id);

-- ============ USER LIMITS ============
CREATE TABLE IF NOT EXISTS user_limits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT UNIQUE NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    plan_type VARCHAR(20) DEFAULT 'free',
    invoices_limit INTEGER DEFAULT 5,
    invoices_this_month INTEGER DEFAULT 0,
    current_period_start DATE DEFAULT CURRENT_DATE,
    payment_status VARCHAR(20) DEFAULT 'none',
    paid_until DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_limits ON user_limits(user_id);

-- ============ DATA DELETION LOGS ============
CREATE TABLE IF NOT EXISTS data_deletion_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    deletion_type VARCHAR(50) NOT NULL,
    items_deleted INTEGER DEFAULT 0,
    requested_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- ============ DOCUMENT ARCHIVES ============
CREATE TABLE IF NOT EXISTS document_archives (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    archive_size INTEGER,
    documents_count INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    sent_at TIMESTAMP,
    error_message TEXT
);

-- ============ USER FEEDBACK ============
CREATE TABLE IF NOT EXISTS user_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    feedback_type VARCHAR(50) DEFAULT 'general',
    subject VARCHAR(255),
    message TEXT NOT NULL,
    contact_email VARCHAR(255),
    status VARCHAR(20) DEFAULT 'new',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_user ON user_feedback(user_id);

-- ============ TRIGGERS ============

-- Автоблокировка счёта после привязки PDF
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

DROP TRIGGER IF EXISTS invoice_lock_trigger ON invoices;
CREATE TRIGGER invoice_lock_trigger
BEFORE UPDATE ON invoices
FOR EACH ROW
EXECUTE FUNCTION lock_invoice_after_pdf();

-- Автоблокировка оффера после конвертации в счёт
CREATE OR REPLACE FUNCTION lock_offer_after_invoice()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.converted_to_invoice_id IS NOT NULL AND OLD.converted_to_invoice_id IS NULL THEN
        NEW.is_locked := TRUE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS offer_lock_trigger ON offers;
CREATE TRIGGER offer_lock_trigger
BEFORE UPDATE ON offers
FOR EACH ROW
EXECUTE FUNCTION lock_offer_after_invoice();

-- Сброс месячных лимитов
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
