import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import db


class StoreTests(unittest.TestCase):
    def setUp(self):
        # Keep test databases inside the project so no system-temp permissions
        # are required. `data/` is created by the application on first launch.
        self.tmp = tempfile.TemporaryDirectory(dir=app.ROOT)
        self.original = db.SQLITE_PATH
        db.SQLITE_PATH = Path(self.tmp.name) / 'test.db'
        app.initialize()

    def tearDown(self):
        db.SQLITE_PATH = self.original
        self.tmp.cleanup()

    def action(self, endpoint, body):
        conn = db.connect()
        try:
            with conn:
                conn.begin_write()
                return app.mutate(conn, endpoint, body)
        finally:
            conn.close()

    def query(self, sql):
        conn = db.connect()
        try:
            return conn.execute(sql).fetchone()[0]
        finally:
            conn.close()

    def receive(self, qty=10):
        return self.action('stock',dict(product_id=1,quantity=qty,type='receive',reason='Opening count'))

    def sale(self, items=None):
        return self.action('checkout',dict(employee_id=1,payment='Cash',items=items or [dict(product_id=1,quantity=2)]))

    def test_import_is_idempotent_and_totals_match(self):
        count = self.query('SELECT COUNT(*) FROM orders')
        app.initialize()
        self.assertEqual(count,self.query('SELECT COUNT(*) FROM orders'))
        self.assertEqual(50,self.query('SELECT COUNT(*) FROM products'))
        self.assertEqual(0,self.query('SELECT SUM(stock) FROM products'))
        self.assertEqual(0,self.query('SELECT COUNT(*) FROM orders WHERE total != (SELECT SUM(quantity*unit_price) FROM order_items WHERE order_id=orders.id)'))

    def test_checkout_and_void_restore_stock_exactly_once(self):
        self.receive()
        sale = self.sale()
        self.assertEqual(8,self.query('SELECT stock FROM products WHERE id=1'))
        self.assertEqual(self.query('SELECT price*2 FROM products WHERE id=1'),sale['total'])
        self.action('void',dict(id=sale['order_id'],reason='Cancelled'))
        self.assertEqual(10,self.query('SELECT stock FROM products WHERE id=1'))
        with self.assertRaises(ValueError):
            self.action('void',dict(id=sale['order_id'],reason='Again'))
        self.assertEqual(10,self.query('SELECT stock FROM products WHERE id=1'))

    def test_failed_sale_rolls_back_everything(self):
        self.receive()
        count = self.query('SELECT COUNT(*) FROM orders')
        with self.assertRaises(ValueError):
            self.sale([dict(product_id=1,quantity=2),dict(product_id=2,quantity=1)])
        self.assertEqual(count,self.query('SELECT COUNT(*) FROM orders'))
        self.assertEqual(10,self.query('SELECT stock FROM products WHERE id=1'))

    def test_duplicate_cart_lines_cannot_oversell(self):
        self.receive(3)
        with self.assertRaises(ValueError):
            self.sale([dict(product_id=1,quantity=2),dict(product_id=1,quantity=2)])
        self.assertEqual(3,self.query('SELECT stock FROM products WHERE id=1'))

    def test_invalid_stock_and_historical_void_rejected(self):
        with self.assertRaises(ValueError):
            self.action('stock',dict(product_id=1,quantity=1,type='remove',reason='Damage'))
        with self.assertRaises(ValueError):
            self.action('void',dict(id=1,reason='Historical'))
        self.assertEqual(0,self.query('SELECT COUNT(*) FROM stock_movements'))

    def test_prices_and_inactive_product(self):
        self.assertEqual(101,app.money('1.005'))
        for value in ['NaN','Infinity','-1']:
            with self.assertRaises(ValueError): app.money(value)
        self.receive()
        self.action('products',dict(id=1,name='Rice',sku='GR-0001',category_id=1,supplier_id=1,price='20',active=0))
        with self.assertRaises(ValueError): self.sale()

if __name__ == '__main__':
    unittest.main()
