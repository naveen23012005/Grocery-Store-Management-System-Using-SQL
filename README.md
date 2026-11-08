# Freshlane — Grocery Store Management

A working manager dashboard backed by SQLite or Amazon RDS MySQL and a Python HTTP server. Manage everyday store operations in the browser without writing SQL. SQLite needs no external database server.

## Run on Windows

Install Python 3.10+ if it is not already available, then run from this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Or run `python app.py` with Python 3.10+. Open http://127.0.0.1:8000 and create your manager password (at least 10 characters). The launcher also supports the Python runtime bundled with Codex on this computer.

The server listens only on this computer. Keep the terminal running; press Ctrl+C to stop. Change the port with the `PORT` environment variable. The first launch creates `data/grocery.db` and imports the supplied CSV files once. Restarting preserves changes.

## Amazon RDS MySQL connection

The default database is local SQLite. To use an Amazon RDS for MySQL or Aurora MySQL instance, first create an empty database and a least-privilege application user on the RDS instance. Create a project Python environment and install the one required driver:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Set connection details in the PowerShell window that starts the app. Do not put the real password in Git, source files, or `.env.example`.

```powershell
$env:DB_BACKEND = 'mysql'
$env:RDS_HOST = 'your-instance.xxxxxxxxxxxx.ap-south-1.rds.amazonaws.com'
$env:RDS_PORT = '3306'
$env:RDS_DATABASE = 'freshlane'
$env:RDS_USER = 'freshlane_app'
$env:RDS_PASSWORD = 'your-secret-password'
$env:RDS_SSL_CA = 'C:\secure\global-bundle.pem'  # Recommended RDS CA bundle
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

The launcher prefers `.venv` automatically. The connection is implemented in `db.py`; it selects MySQL only when `DB_BACKEND=mysql`. On the first successful RDS launch, Freshlane creates its tables from `schema_mysql.sql` and imports the supplied CSV data once. Do this only with a new, empty application database. Network access must be allowed from the computer running Freshlane to the RDS security group on port 3306.

## Manager workflows

- **Overview:** today's revenue/orders, active products, low-stock alerts, historical revenue chart, recent orders, and best sellers.
- **Inventory:** create and edit products, unique SKUs, selling prices, supplier/category links, reorder levels, and active status. Add categories from the UI.
- **Receive / adjust stock:** enter opening counts, supplier deliveries, damaged stock, or corrections with a required reason. Every change creates a stock movement.
- **Point of sale:** search products, build a basket, select a customer (or walk-in), employee, and Cash/Card/UPI payment method. Completion saves the order and reduces stock atomically.
- **Sales & orders:** search orders, view/print itemized receipts, export CSV, and void a live sale with a reason. Voiding restores stock exactly once and excludes the sale from revenue.
- **Customers, Suppliers, Team:** create/edit records and deactivate them while preserving historical relationships.
- **Reports:** total revenue, average order value, employee sales, payment breakdown, stock retail value, and the latest 200 stock movements.

## Important source-data decisions

The original `Grocery Store Management_SQL.sql` contains unrelated credit-card tables and had pre-existing local edits. It has been preserved. The application's correct grocery schema is `schema.sql`.

The supplied CSVs include no inventory quantities, tax rates, cost prices, or payment methods. Opening inventory therefore starts at **zero**. Receive your actual counted quantities before checkout. No fabricated inventory or recent sales are added. Historical orders retain their original dates and are labeled with the payment method `Historical`; they do not deduct current stock and cannot be voided.

Prices are rounded to two decimals and stored as integer paise. Imported order totals are recalculated from rounded unit prices × quantity, so they can differ slightly from the source's floating-point TotalPrice values. Category names are provisional labels for the source category IDs; review product categorization for your store. The legacy source includes some unusual assignments (for example, mouth wash under category 2), which can be corrected through Inventory.

## Database and integrity

`schema.sql` and `schema_mysql.sql` define categories, suppliers, customers, employees, products, orders, order_items, stock_movements, and settings. `db.py` selects the matching database connection. Foreign keys, unique SKU constraints, nonnegative stock/price checks, and positive line-item quantities protect data. Checkout and stock mutations acquire a database write transaction before validation to prevent concurrent overselling. Historical unit prices and product names are retained on order lines. The backend calculates totals and does not trust prices from the browser.

Manager passwords use salted PBKDF2-SHA256. Sessions use HttpOnly/SameSite cookies and expire after eight hours or a server restart. API writes reject cross-origin browser requests. Credentials and database files are not committed.

## Backups

Stop the server and copy `data/grocery.db` to a safe backup location. Restore by stopping the server and replacing that file with your backup. Store this file securely: it contains customer details and your manager password hash. `GROCERY_DB` can specify a separate database file for testing or another store.

## Tests

```powershell
python -m unittest discover -s tests -v
node --check web/app.js
```

The database tests create isolated temporary databases under `data/` and verify CSV import, monetary rounding, checkout/void behavior, rollback, inactive products, and overselling protection.

An optional Playwright browser test is in `tests/browser.cjs`. It needs Node.js, Playwright, and Microsoft Edge (or set `BROWSER_CHANNEL=chrome`). Start a **fresh disposable database** on port 8001, then run the script. It creates a test manager account and writes test records. Do not point it at a live store. Screenshots are written under `data/`.

## Scope

This is a functional local, single-manager application. Card/UPI selections record payments collected separately; there is no payment gateway. Voids record cancellation, not an automatic financial refund. It does not yet implement GST/tax invoices, discounts, partial returns, purchase orders/payables, batch/expiry tracking, cost-based profit, barcode hardware integration, multiple roles, or multi-store synchronization. It is not configured for public internet hosting; a public deployment needs a production server, HTTPS, login throttling, and operational backup/recovery controls.

## Files

- `app.py`: HTTP API, authentication, transaction logic, and CSV import
- `db.py`: database connection layer; SQLite by default, RDS MySQL through environment variables
- `schema.sql` / `schema_mysql.sql`: normalized SQLite and MySQL schemas
- `web/`: responsive dashboard, forms, point of sale, and receipts
- `tests/`: database and browser verification
- `start.ps1`: Windows launcher
- Original CSV/PDF/SQL files: preserved project source material
