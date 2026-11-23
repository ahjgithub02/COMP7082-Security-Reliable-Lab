"""Shopping cart management, discount calculation, and persistence."""
from models import CartLine


class ShoppingCart:
    """Manages items, quantities, and discount codes for a user's cart."""

    VALID_DISCOUNTS = {'WELCOME10', 'STUDENT20', 'SAVE15', 'FREESHIP'}

    def __init__(self, user_id, repository):
        """Create an empty shopping cart tied to a user and a repository."""
        self.user_id = user_id
        self.repository = repository
        self.lines = []
        self.discount_code = None

    @staticmethod
    def _is_valid_quantity(quantity):
        """Check that a quantity is a positive integer (and not a bool)."""
        return isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0

    def add_item(self, sku, quantity):
        """
        Add a product to the cart if it exists, the quantity is valid, and
        the combined quantity in the cart doesn't exceed available stock.
        """
        if not self._is_valid_quantity(quantity):
            return False

        product = self.repository.get_product(sku)
        if not product:
            return False

        existing = next((x for x in self.lines if x.sku == sku), None)
        new_quantity = (existing.quantity if existing else 0) + quantity
        if product.stock < new_quantity:
            return False

        if existing:
            existing.quantity = new_quantity
        else:
            self.lines.append(CartLine(sku, product.name, product.price, quantity))
        return True

    def remove_item(self, sku, quantity=None):
        """
        Remove an item from the cart, or reduce its quantity.
        If quantity is None or >= current quantity, the whole line is removed.
        """
        if quantity is not None and not self._is_valid_quantity(quantity):
            return False

        for line in self.lines:
            if line.sku == sku:
                if quantity is None or quantity >= line.quantity:
                    self.lines.remove(line)
                else:
                    line.quantity -= quantity
                return True
        return False

    def subtotal(self):
        """Calculate the pre-discount subtotal, rounded to 2 decimal places."""
        return round(sum(line.unit_price * line.quantity for line in self.lines), 2)

    def total(self):
        """
        Calculate the final cart total dynamically using the active discount code.
        Always clamps the result at 0.00 so discounts can never produce a negative total.
        """
        amount = self.subtotal()
        if self.discount_code == 'WELCOME10':
            amount *= 0.9
        elif self.discount_code == 'STUDENT20':
            amount *= 0.8
        elif self.discount_code == 'SAVE15':
            amount -= 15.0
        elif self.discount_code == 'FREESHIP':
            pass
        return round(max(amount, 0.0), 2)

    def apply_discount(self, code):
        """Apply a valid discount code to the cart. Replaces any previous code."""
        if code not in self.VALID_DISCOUNTS:
            return False
        self.discount_code = code
        return True

    def clear(self):
        """Empty the cart and reset any active discount code."""
        self.lines.clear()
        self.discount_code = None

    def load(self):
        """
        Reload the user's saved cart from the database.
        Clears current in-memory lines first so repeated loads don't double items.
        """
        self.clear()
        for sku, quantity in self.repository.get_saved_cart(self.user_id):
            self.add_item(sku, quantity)

    def save(self):
        """Persist the current cart lines to the database."""
        self.repository.save_cart(self.user_id, self.lines)