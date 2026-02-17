-- ============================================
-- ПОЛНАЯ СХЕМА БД — INVOICE BOT (PostgreSQL)
-- Точная копия Supabase production schema
-- Запускается при первом старте контейнера
-- ============================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============ PROFILES ============
CREATE TABLE IF NOT EXISTS profiles (
    id BIGINT PRIMARY KEY,
    company_name TEXT,
    owner_name TEXT,
    street TEXT,
    city TEXT,
    tax_id TEXT,
    vat_id TEXT,
    iban TEXT,
    bic TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    bank_name TEXT,
    phone TEXT,
    email TEXT,
    invoice_number_prefix TEXT DEFAULT 'RE-',
    invoice_number_format INTEGER DEFAULT 4,
    customer_id_prefix TEXT DEFAULT 'KUND-',
    postal_code TEXT,
    username TEXT,
    is_kleinunternehmer BOOLEAN DEFAULT FALSE,
    payment_terms INTEGER DEFAULT 14,
    next_invoice_number INTEGER DEFAULT 1,
    next_customer_number INTEGER DEFAULT 1,
    offer_number_prefix TEXT DEFAULT 'ANG-',
    offer_number_format INTEGER DEFAULT 4,
    next_offer_number INTEGER DEFAULT 1,
    offer_validity_days INTEGER DEFAULT 14,
    default_vat_rate NUMERIC DEFAULT 19,
    country_code TEXT DEFAULT 'DE',
    payment_terms_days INTEGER DEFAULT 14,
    legal_form TEXT,
    trade_register_number TEXT,
    trade_register_court TEXT,
    managing_director TEXT,
    website TEXT,
    global_location_number TEXT,
    duns_number TEXT,
    contact_department TEXT,
    contact_person TEXT,
    fax TEXT,
    sepa_creditor_id TEXT,
    sepa_mandate_reference TEXT,
    tax_office TEXT,
    sales_tax_id_local TEXT,
    default_currency TEXT DEFAULT 'EUR',
    default_language TEXT DEFAULT 'de',
    invoice_note_default TEXT,
    logo_url TEXT,
    vat_category_code TEXT DEFAULT 'S',
    gdpr_consent BOOLEAN DEFAULT FALSE,
    gdpr_consent_date TIMESTAMP,
    user_email VARCHAR(255),
    accepted_terms BOOLEAN DEFAULT FALSE,
    accepted_terms_date TIMESTAMP,
    total_donations NUMERIC DEFAULT 0
);

-- ============ CLIENTS ============
CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    customer_id TEXT,
    company_name TEXT NOT NULL,
    street TEXT,
    postal_code TEXT,
    city TEXT,
    country TEXT DEFAULT 'Deutschland',
    email TEXT,
    phone TEXT,
    tax_id TEXT,
    vat_id TEXT,
    iban TEXT,
    bic TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    country_code TEXT DEFAULT 'DE',
    buyer_reference TEXT,
    contact_name TEXT,
    contact_phone TEXT,
    street_additional TEXT,
    address_line2 TEXT,
    state_region TEXT,
    po_box TEXT,
    global_location_number TEXT,
    duns_number TEXT,
    eori_number TEXT,
    legal_form TEXT,
    trade_register_number TEXT,
    contact_department TEXT,
    contact_fax TEXT,
    contact_mobile TEXT,
    payment_terms_days INTEGER,
    credit_limit NUMERIC,
    discount_percentage NUMERIC,
    price_group TEXT,
    account_number TEXT,
    delivery_address_different BOOLEAN DEFAULT FALSE,
    delivery_street TEXT,
    delivery_postal_code TEXT,
    delivery_city TEXT,
    delivery_country_code TEXT,
    industry TEXT,
    annual_revenue NUMERIC,
    employee_count INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    rating TEXT,
    last_order_date DATE
);

CREATE INDEX IF NOT EXISTS idx_clients_user ON clients(user_id);

-- ============ INVOICES ============
CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT REFERENCES profiles(id) ON DELETE CASCADE,
    client_id UUID,
    number TEXT NOT NULL,
    amount NUMERIC,
    vat_rate NUMERIC DEFAULT 19.0,
    created_at TIMESTAMPTZ DEFAULT now(),
    client_address TEXT,
    client_name TEXT,
    total NUMERIC,
    invoice_date DATE,
    description TEXT,
    status TEXT DEFAULT 'created',
    customer_id TEXT,
    purchase_order_number TEXT,
    format_type TEXT DEFAULT 'ZUGFeRD',
    pdf_url TEXT,
    xml_url TEXT,
    notes TEXT,
    due_date DATE,
    delivery_date DATE,
    buyer_reference TEXT,
    payment_method TEXT DEFAULT 'SEPA',
    currency_code TEXT DEFAULT 'EUR',
    tax_exemption_reason TEXT,
    zugferd_profile TEXT DEFAULT 'BASIC',
    contract_number TEXT,
    project_number TEXT,
    cost_center TEXT,
    order_confirmation_number TEXT,
    delivery_note_number TEXT,
    billing_period_start DATE,
    billing_period_end DATE,
    skonto_percentage NUMERIC,
    skonto_days INTEGER,
    partial_payment_allowed BOOLEAN DEFAULT FALSE,
    ship_to_name TEXT,
    ship_to_street TEXT,
    ship_to_postal_code TEXT,
    ship_to_city TEXT,
    ship_to_country_code TEXT,
    incoterms TEXT,
    delivery_terms TEXT,
    shipping_method TEXT,
    tracking_number TEXT,
    discount_amount NUMERIC,
    discount_percentage NUMERIC,
    shipping_cost NUMERIC,
    shipping_vat_rate NUMERIC,
    packaging_cost NUMERIC,
    prepaid_amount NUMERIC,
    rounding_amount NUMERIC,
    payment_status TEXT DEFAULT 'unpaid',
    payment_date DATE,
    payment_reference TEXT,
    dunning_level INTEGER DEFAULT 0,
    last_dunning_date DATE,
    credit_note_for_invoice_id UUID,
    corrects_invoice_id UUID,
    is_credit_note BOOLEAN DEFAULT FALSE,
    is_advance_payment BOOLEAN DEFAULT FALSE,
    is_partial_invoice BOOLEAN DEFAULT FALSE,
    is_final_invoice BOOLEAN DEFAULT FALSE,
    reverse_charge BOOLEAN DEFAULT FALSE,
    reverse_charge_info TEXT,
    tax_point_date DATE,
    internal_reference TEXT,
    sales_person TEXT,
    commission_percentage NUMERIC,
    preceding_invoice_number TEXT,
    invoice_type_code TEXT DEFAULT '380',
    document_context_parameter TEXT,
    payment_means_code VARCHAR DEFAULT '58',
    vat_per_item BOOLEAN DEFAULT FALSE,
    global_vat_rate NUMERIC,
    payment_days INTEGER,
    vat_mode TEXT DEFAULT 'standard',
    vat_amount NUMERIC,
    shipping_vat_amount NUMERIC,
    is_locked BOOLEAN DEFAULT FALSE,
    pdf_file_id UUID,
    locked_at TIMESTAMP,
    client_street TEXT,
    client_postal_code TEXT,
    client_city TEXT,
    client_country TEXT,
    client_email TEXT,
    client_vat_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_invoices_user ON invoices(user_id);

-- ============ INVOICE ITEMS ============
CREATE TABLE IF NOT EXISTS invoice_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    position_number INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 1,
    unit TEXT DEFAULT 'Stk',
    unit_price NUMERIC NOT NULL,
    total_price NUMERIC NOT NULL,
    vat_rate NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now(),
    vat_category_code TEXT DEFAULT 'S',
    net_price NUMERIC,
    vat_amount NUMERIC,
    article_number TEXT,
    ean_code TEXT,
    manufacturer_article_number TEXT,
    buyer_article_number TEXT,
    customs_tariff_number TEXT,
    weight_kg NUMERIC,
    volume_m3 NUMERIC,
    length_m NUMERIC,
    width_m NUMERIC,
    height_m NUMERIC,
    list_price NUMERIC,
    discount_percentage NUMERIC,
    discount_amount NUMERIC,
    surcharge_amount NUMERIC,
    batch_number TEXT,
    serial_number TEXT,
    expiry_date DATE,
    country_of_origin TEXT,
    warranty_months INTEGER,
    category TEXT,
    product_group TEXT,
    long_description TEXT,
    technical_data TEXT,
    item_notes TEXT,
    parent_item_id UUID,
    is_sub_item BOOLEAN DEFAULT FALSE,
    sub_item_level INTEGER DEFAULT 0,
    delivery_date DATE,
    delivery_note_number TEXT,
    unit_code TEXT DEFAULT 'C62'
);

CREATE INDEX IF NOT EXISTS idx_invoice_items ON invoice_items(invoice_id);

-- ============ INVOICE VAT BREAKDOWN ============
CREATE TABLE IF NOT EXISTS invoice_vat_breakdown (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    vat_rate NUMERIC NOT NULL,
    vat_category_code TEXT NOT NULL,
    taxable_amount NUMERIC NOT NULL,
    vat_amount NUMERIC NOT NULL,
    exemption_reason TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invoice_vat ON invoice_vat_breakdown(invoice_id);

-- ============ INVOICE ATTACHMENTS ============
CREATE TABLE IF NOT EXISTS invoice_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_type TEXT,
    file_size INTEGER,
    file_url TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invoice_attachments ON invoice_attachments(invoice_id);

-- ============ INVOICE PAYMENTS ============
CREATE TABLE IF NOT EXISTS invoice_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    payment_date DATE NOT NULL,
    amount NUMERIC NOT NULL,
    payment_method TEXT,
    reference TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invoice_payments ON invoice_payments(invoice_id);

-- ============ INVOICE TEMPLATES ============
CREATE TABLE IF NOT EXISTS invoice_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    template_name TEXT NOT NULL,
    client_id UUID,
    interval_type TEXT,
    next_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    template_data JSONB,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invoice_templates_user ON invoice_templates(user_id);

-- ============ OFFERS ============
CREATE TABLE IF NOT EXISTS offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    client_id UUID,
    offer_number TEXT NOT NULL,
    offer_date DATE NOT NULL,
    valid_until DATE NOT NULL,
    client_name TEXT NOT NULL,
    client_address TEXT,
    customer_id TEXT,
    purchase_order_number TEXT,
    amount NUMERIC NOT NULL DEFAULT 0,
    vat_rate NUMERIC NOT NULL DEFAULT 19,
    total NUMERIC NOT NULL DEFAULT 0,
    format_type TEXT DEFAULT 'ZUGFeRD',
    notes TEXT,
    converted_to_invoice_id UUID,
    pdf_url TEXT,
    xml_url TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    delivery_date DATE,
    buyer_reference TEXT,
    currency_code TEXT DEFAULT 'EUR',
    zugferd_profile TEXT DEFAULT 'BASIC',
    project_number TEXT,
    cost_center TEXT,
    validity_days INTEGER DEFAULT 14,
    discount_percentage NUMERIC,
    discount_amount NUMERIC,
    shipping_cost NUMERIC,
    incoterms TEXT,
    delivery_time_days INTEGER,
    payment_terms_text TEXT,
    special_conditions TEXT,
    sales_person TEXT,
    offer_status TEXT DEFAULT 'draft',
    accepted_date DATE,
    rejection_reason TEXT,
    followup_date DATE,
    vat_mode VARCHAR DEFAULT 'standard',
    vat_per_item BOOLEAN DEFAULT FALSE,
    global_vat_rate NUMERIC DEFAULT 19.00,
    shipping_vat_rate NUMERIC DEFAULT 19.00,
    net_amount NUMERIC,
    vat_amount NUMERIC,
    gross_amount NUMERIC,
    payment_terms VARCHAR,
    pdf_file_id UUID,
    is_locked BOOLEAN DEFAULT FALSE,
    client_street TEXT,
    client_postal_code TEXT,
    client_city TEXT,
    client_country TEXT,
    client_email TEXT,
    client_vat_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_offers_user ON offers(user_id);

-- ============ OFFER ITEMS ============
CREATE TABLE IF NOT EXISTS offer_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_id UUID NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    position_number INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 1,
    unit TEXT DEFAULT 'Stk',
    unit_price NUMERIC NOT NULL,
    total_price NUMERIC NOT NULL,
    vat_rate NUMERIC NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    vat_category_code TEXT DEFAULT 'S',
    net_price NUMERIC,
    vat_amount NUMERIC,
    article_number TEXT,
    ean_code TEXT,
    manufacturer_article_number TEXT,
    buyer_article_number TEXT,
    weight_kg NUMERIC,
    volume_m3 NUMERIC,
    list_price NUMERIC,
    discount_percentage NUMERIC,
    discount_amount NUMERIC,
    long_description TEXT,
    delivery_time_days INTEGER,
    availability_status TEXT,
    minimum_order_quantity NUMERIC,
    unit_code TEXT DEFAULT 'C62'
);

CREATE INDEX IF NOT EXISTS idx_offer_items ON offer_items(offer_id);

-- ============ OFFER VAT BREAKDOWN ============
CREATE TABLE IF NOT EXISTS offer_vat_breakdown (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    offer_id UUID NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    vat_rate NUMERIC NOT NULL,
    taxable_amount NUMERIC NOT NULL,
    vat_amount NUMERIC NOT NULL,
    vat_category_code VARCHAR,
    vat_exemption_reason TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_offer_vat ON offer_vat_breakdown(offer_id);

-- ============ DOCUMENT FILES ============
CREATE TABLE IF NOT EXISTS document_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    document_type VARCHAR NOT NULL,
    document_id UUID NOT NULL,
    file_name VARCHAR NOT NULL,
    file_data BYTEA NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type VARCHAR DEFAULT 'application/pdf',
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doc_files_user ON document_files(user_id);
CREATE INDEX IF NOT EXISTS idx_doc_files_doc ON document_files(document_id);

-- ============ USER LIMITS ============
CREATE TABLE IF NOT EXISTS user_limits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL UNIQUE REFERENCES profiles(id) ON DELETE CASCADE,
    plan_type VARCHAR DEFAULT 'free',
    invoices_limit INTEGER DEFAULT 5,
    invoices_this_month INTEGER DEFAULT 0,
    current_period_start DATE DEFAULT CURRENT_DATE,
    payment_status VARCHAR DEFAULT 'none',
    paid_until DATE,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_limits ON user_limits(user_id);

-- ============ DATA DELETION LOGS ============
CREATE TABLE IF NOT EXISTS data_deletion_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    deletion_type VARCHAR NOT NULL,
    items_deleted INTEGER DEFAULT 0,
    requested_at TIMESTAMP DEFAULT now(),
    completed_at TIMESTAMP
);

-- ============ DOCUMENT ARCHIVES ============
CREATE TABLE IF NOT EXISTS document_archives (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    email VARCHAR NOT NULL,
    status VARCHAR DEFAULT 'pending',
    archive_size INTEGER,
    documents_count INTEGER,
    created_at TIMESTAMP DEFAULT now(),
    sent_at TIMESTAMP,
    error_message TEXT
);

-- ============ USER FEEDBACK ============
CREATE TABLE IF NOT EXISTS user_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    feedback_type VARCHAR DEFAULT 'general',
    subject VARCHAR,
    message TEXT NOT NULL,
    contact_email VARCHAR,
    status VARCHAR DEFAULT 'new',
    created_at TIMESTAMP DEFAULT now()
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
