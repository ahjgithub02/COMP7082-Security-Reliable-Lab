"""Checkout workflow coordinating inventory checks, payments, and order saving."""
from models import OrderResult


class CheckoutService:
    """Handles end-to-end checkout with stock validation and idempotency."""

    def __init__(self, repository, payment_gateway):
        """Initialize checkout with a data repository and a payment gateway."""
        self.repository = repository
        self.payment_gateway = payment_gateway

    def checkout(self, cart, payment_token, request_id):
        """
        Process a checkout for the given cart.
        - Returns the existing order if request_id was already processed.
        - Validates that the cart is non-empty and all items are in stock.
        - Only deducts stock and clears the cart if payment is approved.
        """
        if not request_id or not str(request_id).strip():
            return OrderResult(None, 'invalid_request', 0.0)

        existing = self.repository.get_order_by_request_id(request_id)
        if existing:
            order_id, _, existing_amount, existing_status, _ = existing
            return OrderResult(order_id, existing_status, existing_amount)

        if len(cart.lines) == 0:
            return OrderResult(None, 'empty', 0.0)

        # Re-check live stock before charging the payment gateway.
        for line in cart.lines:
            product = self.repository.get_product(line.sku)
            if not product or product.stock < line.quantity:
                return OrderResult(None, 'out_of_stock', 0.0)

        amount = cart.total()

        try:
            response = self.payment_gateway.charge(amount, payment_token)
            approved = bool(response and response.get('approved'))
            status = 'paid' if approved else 'declined'
        except Exception:
            status = 'payment_error'

        if status != 'paid':
            order_id = self.repository.save_order(cart.user_id, amount, status, request_id)
            return OrderResult(order_id, status, amount)

        # Payment succeeded; deduct stock atomically.
        if not self.repository.deduct_stock_for_lines(cart.lines):
            order_id = self.repository.save_order(cart.user_id, amount, 'out_of_stock', request_id)
            return OrderResult(order_id, 'out_of_stock', amount)

        order_id = self.repository.save_order(cart.user_id, amount, 'paid', request_id)
        cart.clear()
        cart.save()
        return OrderResult(order_id, 'paid', amount)