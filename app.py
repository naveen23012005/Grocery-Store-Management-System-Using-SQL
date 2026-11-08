"""Freshlane: local grocery management with SQLite or Amazon RDS MySQL."""
import csv
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import db

ROOT = Path(__file__).resolve().parent
SESSIONS = {}

def now():
    return datetime.now().isoformat(timespec='seconds')

def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]

def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 10000000:
            raise ValueError('Price must be between 0 and 10,000,000.')
        return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise ValueError('Enter a valid price.')

def integer(value, minimum=0):
    if isinstance(value, bool) or str(value) != str(int(value)) or not minimum <= int(value) <= 1000000:
        raise ValueError('Enter a valid whole number.')
    return int(value)

def label(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError('Name is required (maximum 200 characters).')
    return value.strip()

def initialize():
    schema = ROOT / ('schema_mysql.sql' if db.BACKEND == 'mysql' else 'schema.sql')
    with db.connect() as conn:
        conn.executescript(schema.read_text())
        if conn.execute("SELECT 1 FROM settings WHERE setting_key='imported'").fetchone():
            return
        def read(name):
            with (ROOT / name).open(encoding='utf-8-sig', newline='') as f:
                return list(csv.DictReader(f))
        for i, name in enumerate(['Pantry', 'Dairy & chilled', 'Snacks & essentials', 'Personal care', 'Household'], 1):
            conn.execute('INSERT INTO categories VALUES (?,?)', (i, name))
        for table, file, id_key, name_key in [('suppliers','Suppliers (1).csv','SupplierID','SupplierName'), ('customers','Customers (3).csv','CustomerID','Name'), ('employees','Store_Employees (1).csv','EmployeeID','Name')]:
            for r in read(file):
                extra = 'hire_date' if table == 'employees' else 'address'
                value = datetime.strptime(r['HireDate'], '%m/%d/%Y').date().isoformat() if table == 'employees' else r['Address']
                conn.execute(f'INSERT INTO {table} (id,name,{extra}) VALUES (?,?,?)', (int(r[id_key]), r[name_key].strip(), value))
        for r in read('Products (1).csv'):
            conn.execute('INSERT INTO products (id,name,sku,category_id,supplier_id,price) VALUES (?,?,?,?,?,?)', (int(r['ProductID']), r['Name'], 'GR-'+r['ProductID'].zfill(4), int(r['CategoryID']), int(r['SupplierID']), money(r['Price'])))
        for r in read('Orders (4).csv'):
            conn.execute("INSERT INTO orders (id,customer_id,employee_id,created_at,total,payment,source) VALUES (?,?,?,?,0,'Historical','import')", (int(r['OrderID']), int(r['CustomerID']), int(r['EmployeeID']), datetime.strptime(r['OrderDate'], '%m/%d/%Y').isoformat()))
        for r in read('OrderDetails (1).csv'):
            p = conn.execute('SELECT name FROM products WHERE id=?', (int(r['ProductID']),)).fetchone()
            conn.execute('INSERT INTO order_items VALUES (?,?,?,?,?,?)', (int(r['OrderDetailID']), int(r['OrderID']), int(r['ProductID']), p['name'], int(r['Quantity']), money(r['PriceEach'])))
        conn.execute('UPDATE orders SET total=COALESCE((SELECT SUM(quantity*unit_price) FROM order_items WHERE order_id=orders.id),0)')
        conn.execute("INSERT INTO settings VALUES ('imported','1')")

def active(db, table, record_id):
    r = db.execute(f'SELECT * FROM {table} WHERE id=? AND active=1', (record_id,)).fetchone()
    if not r:
        raise ValueError(f'Select an active {table.rstrip("s")}.')
    return r

def mutate(db, endpoint, body):
    if endpoint in ('products', 'customers', 'suppliers', 'employees'):
        record_id = body.get('id')
        values = {'name': label(body.get('name')), 'active': integer(body.get('active', 1))}
        if values['active'] not in (0,1):
            raise ValueError('Invalid active status.')
        if endpoint == 'products':
            values.update(sku=label(body.get('sku')), category_id=integer(body.get('category_id'),1), supplier_id=integer(body.get('supplier_id'),1), price=money(body.get('price')), reorder_level=integer(body.get('reorder_level',10)))
            active(db, 'suppliers', values['supplier_id'])
        else:
            values['phone'] = str(body.get('phone',''))[:50]
            if endpoint != 'employees':
                values['address'] = str(body.get('address',''))[:500]
            else:
                values['hire_date'] = datetime.strptime(body.get('hire_date') or datetime.now().date().isoformat(), '%Y-%m-%d').date().isoformat()
        if record_id:
            result = db.execute(f'UPDATE {endpoint} SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(),integer(record_id,1)))
            if not result.rowcount:
                raise ValueError('Record not found.')
        else:
            db.execute(f'INSERT INTO {endpoint} ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')', tuple(values.values()))
        return {'ok': True}
    if endpoint == 'categories':
        db.execute('INSERT INTO categories (name) VALUES (?)', (label(body.get('name')),))
        return {'ok': True}
    if endpoint == 'stock':
        p = active(db, 'products', integer(body.get('product_id'),1))
        q = integer(body.get('quantity'),1)
        if body.get('type') not in ('receive','remove'):
            raise ValueError('Invalid stock operation.')
        q *= -1 if body['type']=='remove' else 1
        if p['stock'] + q < 0:
            raise ValueError('Not enough stock to remove.')
        reason = label(body.get('reason'))
        db.execute('UPDATE products SET stock=stock+? WHERE id=?', (q,p['id']))
        db.execute('INSERT INTO stock_movements (product_id,quantity,reason,created_at) VALUES (?,?,?,?)', (p['id'],q,reason,now()))
        return {'ok':True}
    if endpoint == 'checkout':
        employee = integer(body.get('employee_id'),1)
        active(db,'employees',employee)
        customer = body.get('customer_id') or None
        if customer:
            active(db,'customers',integer(customer,1))
        payment = body.get('payment')
        if payment not in ('Cash','Card','UPI'):
            raise ValueError('Choose a payment method.')
        cart = body.get('items')
        if not isinstance(cart,list) or not 1 <= len(cart) <= 200:
            raise ValueError('Add items to the cart.')
        quantities = {}
        for item in cart:
            pid = integer(item.get('product_id'),1)
            quantities[pid] = quantities.get(pid,0) + integer(item.get('quantity'),1)
        items = []
        for pid,q in quantities.items():
            p = active(db,'products',pid)
            if p['stock'] < q:
                raise ValueError(f'Not enough stock for {p["name"]}. Available: {p["stock"]}.')
            items.append((p,q))
        total = sum(p['price']*q for p,q in items)
        oid = db.execute('INSERT INTO orders (customer_id,employee_id,created_at,total,payment) VALUES (?,?,?,?,?)', (customer,employee,now(),total,payment)).lastrowid
        for p,q in items:
            db.execute('INSERT INTO order_items (order_id,product_id,name,quantity,unit_price) VALUES (?,?,?,?,?)', (oid,p['id'],p['name'],q,p['price']))
            db.execute('UPDATE products SET stock=stock-? WHERE id=?', (q,p['id']))
            db.execute('INSERT INTO stock_movements (product_id,quantity,reason,created_at,order_id) VALUES (?,?,?,?,?)', (p['id'],-q,'Sale',now(),oid))
        return {'ok':True,'order_id':oid,'total':total}
    if endpoint == 'void':
        oid = integer(body.get('id'),1)
        order = db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not order or order['status']!='completed' or order['source']!='live':
            raise ValueError('Only completed live sales can be voided.')
        reason = label(body.get('reason'))
        for r in db.execute('SELECT * FROM order_items WHERE order_id=?',(oid,)).fetchall():
            db.execute('UPDATE products SET stock=stock+? WHERE id=?',(r['quantity'],r['product_id']))
            db.execute('INSERT INTO stock_movements (product_id,quantity,reason,created_at,order_id) VALUES (?,?,?,?,?)',(r['product_id'],r['quantity'],'Void: '+reason,now(),oid))
        db.execute("UPDATE orders SET status='void',void_reason=? WHERE id=?",(reason,oid))
        return {'ok':True}
    raise ValueError('Unknown operation.')

class Handler(BaseHTTPRequestHandler):
    def send(self, status, data, cookie=None, content_type='application/json'):
        payload = json.dumps(data).encode() if content_type=='application/json' else data
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(payload)

    def authenticated(self):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: return False
        token = cookie.get('session')
        return bool(token and SESSIONS.get(token.value,0)>time.time())

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            with db.connect() as conn:
                if path == '/api/session':
                    return self.send(200,{'authenticated':self.authenticated(),'setup':not bool(conn.execute("SELECT 1 FROM settings WHERE setting_key='password'").fetchone())})
                if not self.authenticated(): return self.send(401,{'error':'Please sign in.'})
                if path == '/api/state':
                    data = {t:rows(conn,f'SELECT * FROM {t} ORDER BY id') for t in ['products','categories','suppliers','customers','employees']}
                    data['orders'] = rows(conn,"SELECT o.*,COALESCE(c.name,'Walk-in customer') customer,e.name employee FROM orders o LEFT JOIN customers c ON o.customer_id=c.id JOIN employees e ON o.employee_id=e.id ORDER BY o.created_at DESC,o.id DESC")
                    data['movements'] = rows(conn,'SELECT m.*,p.name FROM stock_movements m JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT 200')
                    data['top_products'] = rows(conn,"SELECT i.name,SUM(i.quantity) units,SUM(i.quantity*i.unit_price) revenue FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.status='completed' GROUP BY i.product_id ORDER BY revenue DESC LIMIT 5")
                    return self.send(200,data)
                if path.startswith('/api/orders/'):
                    try: oid = int(path.rsplit('/',1)[1])
                    except ValueError: return self.send(400,{'error':'Invalid order.'})
                    return self.send(200,rows(conn,'SELECT * FROM order_items WHERE order_id=?',(oid,)))
            return self.send(404,{'error':'Not found.'})
        files = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if path not in files: return self.send(404,{'error':'Not found.'})
        file = ROOT / 'web' / files[path]
        self.send(200,file.read_bytes(),content_type={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[file.suffix[1:]])

    def do_POST(self):
        origin = self.headers.get('Origin')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and origin != 'http://'+self.headers.get('Host','')):
            return self.send(403,{'error':'Cross-origin request rejected.'})
        try:
            length = int(self.headers.get('Content-Length',0))
            if not 0 < length <= 100000: raise ValueError('Invalid request size.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise ValueError('Expected an object.')
            endpoint = urlparse(self.path).path.removeprefix('/api/')
            with db.connect() as conn:
                conn.begin_write()
                if endpoint in ('setup','login'):
                    saved = conn.execute("SELECT value FROM settings WHERE setting_key='password'").fetchone()
                    password = body.get('password','')
                    if not isinstance(password,str) or not 10 <= len(password) <= 256:
                        raise ValueError('Use a password of 10–256 characters.')
                    if endpoint=='setup':
                        if saved: raise ValueError('Manager account already exists.')
                        salt = secrets.token_hex(16)
                        hashed = hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),200000).hex()
                        conn.execute("INSERT INTO settings VALUES ('password',?)",(salt+':'+hashed,))
                    else:
                        if not saved: raise ValueError('Create your manager account first.')
                        salt, hashed = saved['value'].split(':')
                        if not hmac.compare_digest(hashed,hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),200000).hex()):
                            return self.send(401,{'error':'Incorrect password.'})
                    token = secrets.token_urlsafe(32)
                    SESSIONS[token] = time.time()+8*3600
                    conn.commit()
                    return self.send(200,{'ok':True},cookie=f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
                if not self.authenticated(): return self.send(401,{'error':'Please sign in.'})
                if endpoint=='logout':
                    cookie = SimpleCookie(self.headers.get('Cookie',''))
                    if cookie.get('session'): SESSIONS.pop(cookie['session'].value,None)
                    return self.send(200,{'ok':True},cookie='session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                result = mutate(conn,endpoint,body)
                conn.commit()
                self.send(200,result)
        except (ValueError,TypeError,KeyError,OverflowError) as e:
            self.send(400,{'error':str(e) or 'Invalid input.'})
        except db.IntegrityError:
            self.send(400,{'error':'Duplicate SKU/category or invalid linked record. Check your entries.'})
        except db.OperationalError:
            self.send(503,{'error':'Database is busy or unavailable. Please retry.'})

if __name__ == '__main__':
    initialize()
    port = int(os.environ.get('PORT','8000'))
    print(f'Freshlane is running at http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
