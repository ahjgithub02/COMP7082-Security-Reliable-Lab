"""SQLite persistence layer for products, saved carts, inventory, and orders."""
import sqlite3
from contextlib import closing
from models import Product


class StoreRepository:
    """Handles all SQLite database operations for the online store."""

    def __init__(self, db_path='shop.db'):
        """Initialize the repository with the path to a SQLite database file."""
        self.db_path = db_path

    def connect(self):
        """Open a new SQLite connection with a 2-second busy timeout."""
        return sqlite3.connect(self.db_path, timeout=2)

    def get_product(self, sku):
        """Look up a single product by SKU. Returns None if it doesn't exist."""
        with closing(self.connect()) as conn:
            row = conn.execute(
                'SELECT sku, name, price, stock FROM products WHERE sku = ?',
                (sku,),
            ).fetchone()
        return Product(*row) if row else None

    def get_saved_cart(self, user_id):
        """Fetch all saved (sku, quantity) pairs for a specific user."""
        with closing(self.connect()) as conn:
            rows = conn.execute(
                'SELECT sku, quantity FROM saved_cart WHERE user_id = ?',
                (user_id,),
            ).fetchall()
        return rows

    def save_cart(self, user_id, lines):
        """Replace a user's saved cart in the database with the current cart lines."""
        with closing(self.connect()) as conn:
            with conn:
                conn.execute('DELETE FROM saved_cart WHERE user_id = ?', (user_id,))
                for line in lines:
                    conn.execute(
                        'INSERT INTO saved_cart (user_id, sku, quantity) VALUES (?, ?, ?)',
                        (user_id, line.sku, line.quantity),
                    )

    def update_stock(self, sku, quantity):
        """
        Deduct stock for a single product if enough inventory is available.
        Returns True if the update succeeded, or False if stock was too low.
        """
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            return False
        with closing(self.connect()) as conn:
            with conn:
                cur = conn.execute(
                    'UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?',
                    (quantity, sku, quantity),
                )
                return cur.rowcount == 1

    def deduct_stock_for_lines(self, lines):
        """
        Atomically deduct stock for every line in a cart inside one transaction.
        If any item doesn't have enough stock, the whole transaction rolls back
        and returns False.
        """
        with closing(self.connect()) as conn:
            try:
                with conn:
                    for line in lines:
                        cur = conn.execute(
                            'UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?',
                            (line.quantity, line.sku, line.quantity),
                        )
                        if cur.rowcount != 1:
                            raise ValueError(f'Insufficient stock for {line.sku}')
                return True
            except ValueError:
                return False

    def save_order(self, user_id, amount, status, request_id):
        """Insert a new order record and return its generated order ID."""
        with closing(self.connect()) as conn:
            with conn:
                cur = conn.execute(
                    'INSERT INTO orders(user_id, amount, status, request_id) VALUES (?, ?, ?, ?)',
                    (user_id, amount, status, request_id),
                )
                return cur.lastrowid

    def get_order_by_request_id(self, request_id):
        """Look up an existing order by its idempotency request_id, or return None."""
        if not request_id:
            return None
        with closing(self.connect()) as conn:
            row = conn.execute(
                'SELECT id, user_id, amount, status, request_id FROM orders WHERE request_id = ?',
                (request_id,),
            ).fetchone()
        return row

    def list_orders(self, user_id):
        """Return all orders belonging to a specific user, newest first."""
        with closing(self.connect()) as conn:
            rows = conn.execute(
                'SELECT id, user_id, amount, status FROM orders WHERE user_id = ? ORDER BY id DESC',
                (user_id,),
            ).fetchall()
        return rows