# Invoice-Bot (RechnungAgent) — Codebase Overview

A **Telegram-based invoice management bot** for German freelancers and small businesses. Users create, manage, and send professional invoices and offers directly from Telegram, with ZUGFeRD-compliant PDF/XML generation, GDPR data handling, and AI-powered document recognition.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Bot Framework | python-telegram-bot 20.7 (async) |
| Database | PostgreSQL 16 via Supabase (cloud) or direct connection |
| Cache | Redis 7 (optional, via docker-compose) |
| AI / OCR | Anthropic Claude 3 Haiku |
| PDF | xhtml2pdf + ReportLab + Jinja2 templates |
| XML | lxml (ZUGFeRD 2.4 standard) |
| Email | aiosmtplib (async SMTP) |
| Infra | Docker + docker-compose |
| Frontend Forms | HTML/CSS/JS hosted on GitHub Pages, embedded via Telegram WebApp |

---

## Directory Structure

```
invoice-bot/
├── main_v1.py                         # Entry point — registers handlers, starts polling
├── requirements.txt                   # Python dependencies
├── Dockerfile / docker-compose.yml    # Container setup (bot + Postgres + Redis)
├── .env.example                       # Environment variable template
│
├── src/
│   ├── config_v1.py                   # Constants: URLs, VAT rates, units, model name
│   ├── handlers_v1.py                 # Telegram command & callback handlers (1819 lines)
│   ├── database_v1.py                 # Supabase DB client — all CRUD operations (1190 lines)
│   ├── ai_service_v1.py               # Claude AI integration for document OCR
│   ├── pdf_from_template.py           # HTML→PDF generation via Jinja2 + xhtml2pdf
│   ├── xml_generator_v2.py            # ZUGFeRD XML generation + PDF embedding
│   ├── query_db.py                    # Direct PostgreSQL client (alternative to Supabase)
│   ├── document_generator_v1.py       # Document creation utilities
│   └── pdf_generator_v2.py            # Alternative PDF generator
│
├── templates/default/
│   ├── invoice_template.html          # Jinja2 invoice PDF template
│   └── offer_template.html            # Jinja2 offer PDF template
│
├── database/
│   ├── schema_full.sql                # Complete PostgreSQL schema (15 tables)
│   └── schema_updates.sql             # Incremental migrations
│
└── docs/                              # HTML forms (GitHub Pages)
    ├── company_settings_FINAL.html    # Company profile form
    ├── invoice_form_FINAL.html        # Invoice creation form
    ├── offer_form_FINAL.html          # Offer creation form
    ├── invoices_list.html             # Invoice list view
    └── offers_list.html               # Offer list view
```

---

## Core Modules

### `main_v1.py` — Entry Point

Sets up logging (stdout + `bot_errors.log`), creates the Telegram `Application`, registers all handlers (commands, WebApp callbacks, inline buttons), and starts long polling.

### `src/handlers_v1.py` — Telegram Handlers

The central orchestration layer. Key responsibilities:

- **`/start`** — Creates user profile on first interaction
- **`web_app_data_handler()`** — Processes all form submissions (profile updates, invoice/offer creation, numbering settings). This is the main hub that ties form input to database writes and document generation.
- **Invoice operations** — List, copy, delete, lock invoices; generate PDF+XML; email to client
- **Offer operations** — List, copy, delete offers; convert offer → invoice
- **Settings** — Company profile editing, invoice/offer numbering configuration
- **Privacy & GDPR** — Consent tracking, data deletion with audit logging
- **Menus** — Builds Telegram `ReplyKeyboardMarkup` and `InlineKeyboardMarkup` for navigation

### `src/database_v1.py` — Supabase Database Client

All database operations in a single `Database` class:

- **Profiles** — CRUD for user company data (name, address, tax IDs, banking, legal form)
- **Clients** — Customer database with search
- **Invoices** — Full lifecycle: create (with items + VAT breakdown), read, update, copy, lock, delete
- **Offers** — Mirror of invoice operations + offer → invoice conversion
- **Financial calculations** — `compute_invoice_financials()` handles subtotals, discounts, shipping, per-item or global VAT, with `Decimal` precision
- **User limits** — Freemium plan enforcement (5 free invoices/month)
- **Document storage** — Binary PDF/XML storage in `document_files` table
- **GDPR deletion** — Cascading delete across all user data with audit log

### `src/ai_service_v1.py` — Claude AI Integration

Sends document images to Claude 3 Haiku for OCR. Extracts structured client data (company name, address, tax ID, VAT ID) from photos of business documents. Returns JSON with confidence score.

### `src/pdf_from_template.py` — PDF Generation

Loads Jinja2 HTML templates from `templates/default/`, renders with invoice/offer data, and converts to PDF via `xhtml2pdf` (pisa). Produces professional German-formatted invoices.

### `src/xml_generator_v2.py` — ZUGFeRD XML

Generates ZUGFeRD 2.4-compliant XML for e-invoicing. Builds `CrossIndustryInvoice` XML structure with proper namespaces, parties, line items, VAT breakdown, and monetary summation. Includes `embed_xml_in_pdf()` to attach XML as a PDF file attachment per the ZUGFeRD standard.

### `src/config_v1.py` — Configuration

Constants: GitHub Pages URLs for forms, Claude model name, conversation timeout, supported invoice formats (ZUGFeRD, XRechnung), unit codes (Stk, Std, Tag, kg…), and VAT rates (19% standard, 7% reduced, 0%).

---

## Database Schema (15 Tables)

| Table | Purpose |
|---|---|
| `profiles` | User company data (62 columns — address, tax IDs, banking, numbering prefs, consent) |
| `clients` | Customer database (company, address, contact, tax info, payment terms) |
| `invoices` | Invoice headers (number, dates, parties, amounts, status, VAT mode, locking) |
| `invoice_items` | Line items (quantity, unit, price, VAT rate, article codes, discounts) |
| `invoice_vat_breakdown` | VAT summary per rate (taxable amount, VAT amount, category) |
| `invoice_attachments` | Files attached to invoices |
| `invoice_payments` | Payment tracking history |
| `invoice_templates` | Recurring invoice templates |
| `offers` | Quote/proposal headers (similar to invoices + validity, acceptance) |
| `offer_items` | Quote line items |
| `offer_vat_breakdown` | Quote VAT summary |
| `document_files` | Binary PDF/XML file storage (BYTEA) |
| `user_limits` | Freemium plan tracking (free/paid, invoice count, limits) |
| `data_deletion_logs` | GDPR audit trail for data deletions |
| `document_archives` | User data export requests |

---

## End-to-End Workflows

### Invoice Creation

```
User taps "Neue Rechnung" in Telegram
  → Bot opens invoice_form_FINAL.html as WebApp (profile data Base64-encoded in URL)
  → User fills form (client, items, dates, VAT mode)
  → Form submits JSON via Telegram WebApp API
  → handlers_v1.web_app_data_handler() receives data
    → Creates/updates client record
    → Normalizes items (unit codes, VAT rates)
    → db.create_invoice() computes financials + inserts rows
  → PDFFromTemplateV2 renders Jinja2 template → PDF
  → XMLGeneratorV2 generates ZUGFeRD XML → embeds in PDF
  → PDF saved to document_files table
  → PDF sent to user in Telegram
  → Optional: emailed via async SMTP
```

### Offer → Invoice Conversion

```
User selects offer → taps "Convert"
  → db.convert_offer_to_invoice()
    → Copies offer header + items into new invoice
    → Generates new invoice number
    → Links offer to invoice (converted_to_invoice_id)
  → Follows standard invoice PDF/email flow
```

### GDPR Data Deletion

```
User taps "Daten löschen" → selects scope (invoices/offers/all)
  → Confirmation prompt with warning
  → db.delete_all_user_data()
    → Logs deletion in data_deletion_logs
    → Cascading delete: items → VAT breakdowns → invoices → offers → clients → files
    → Returns deletion statistics
```

---

## Key Design Decisions

- **German-first UI** — All bot messages and forms in German (target market: DACH region)
- **Supabase + direct PostgreSQL** — Dual database support; Supabase for cloud, psycopg2 for self-hosted
- **Decimal arithmetic** — All financial calculations use `Decimal("0.01")` rounding to avoid floating-point errors
- **Multiple VAT modes** — Standard (19%), reduced (7%), zero, Kleinunternehmer (small business exemption), reverse charge, export
- **UNECE Rec. 20 unit codes** — Proper mapping (C62=pieces, HUR=hours, DAY=days, KGM=kg, etc.)
- **ZUGFeRD compliance** — XML embedded in PDF per German e-invoicing standard
- **Freemium model** — 5 free invoices/month, upgrade to Pro for unlimited
- **Async throughout** — All handlers, SMTP, and I/O are async for scalability
- **GDPR compliance** — Consent tracking, full data deletion with audit logging

---

## Environment Variables (from `.env.example`)

| Variable | Purpose |
|---|---|
| `TELEGRAM_TOKEN` | Telegram Bot API token |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/service key |
| `DATABASE_URL` | Direct PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | Claude AI API key |
| `SMTP_HOST` / `SMTP_PORT` | Email server |
| `SMTP_USER` / `SMTP_PASSWORD` | Email credentials |
| `SMTP_FROM` | Sender email address |

---

## Running the Bot

```bash
# With Docker
docker-compose up -d

# Without Docker
pip install -r requirements.txt
cp .env.example .env  # fill in values
python main_v1.py
```
