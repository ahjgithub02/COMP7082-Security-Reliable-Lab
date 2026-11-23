"""Two simple smoke tests"""
import sqlite3
from setup_db import initialize
from repository import StoreRepository
from cart import ShoppingCart


def test_seed_product(tmp_path):
    db = tmp_path / 'test.db'
    initialize(str(db))
    assert StoreRepository(str(db)).get_product('MOU-01').name == 'Wireless mouse'


def test_cart_adds_valid_item(tmp_path):
    db = tmp_path / 'test.db'
    initialize(str(db))
    cart = ShoppingCart('student', StoreRepository(str(db)))
    assert cart.add_item('USB-01', 2)
    assert len(cart.lines) == 1

"""Unit tests covering cart logic, discounts, repository safety, and checkout."""
import pytest
from setup_db import initialize
from repository import StoreRepository
from cart import ShoppingCart
from checkout import CheckoutService
from payments import FakePaymentGateway


@pytest.fixture
def repo(tmp_path):
    """Create a fresh temporary SQLite database for each test."""
    db_file = tmp_path / 'test_shop.db'
    initialize(str(db_file))
    return StoreRepository(str(db_file))


class ExplodingPaymentGateway:
    """Fake payment gateway that raises an unexpected error when charged."""

    def __init__(self):
        self.calls = []

    def charge(self, amount, payment_token):
        self.calls.append((amount, payment_token))
        raise RuntimeError('Gateway timeout')


def test_add_item_rejects_invalid_quantities(repo):
    cart = ShoppingCart('u1', repo)
    assert cart.add_item('USB-01', 0) is False
    assert cart.add_item('USB-01', -3) is False
    assert cart.add_item('USB-01', 1.5) is False
    assert cart.add_item('USB-01', True) is False
    assert len(cart.lines) == 0


def test_add_duplicate_item_respects_total_stock(repo):
    # LAP-01 starts with stock = 5
    cart = ShoppingCart('u1', repo)
    assert cart.add_item('LAP-01', 3) is True
    assert cart.add_item('LAP-01', 3) is False
    assert cart.lines[0].quantity == 3
    assert cart.add_item('LAP-01', 2) is True
    assert cart.lines[0].quantity == 5


def test_remove_item_partial_full_and_invalid(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('USB-01', 4)

    assert cart.remove_item('USB-01', -1) is False
    assert cart.remove_item('USB-01', 0) is False
    assert cart.remove_item('USB-01', 1) is True
    assert cart.lines[0].quantity == 3

    assert cart.remove_item('USB-01', 10) is True
    assert len(cart.lines) == 0
    assert cart.remove_item('USB-01') is False


def test_discount_updates_when_cart_changes(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('MOU-01', 1)  # 29.95
    assert cart.apply_discount('WELCOME10') is True
    assert cart.total() == 26.95

    # Adding another item should recalculate the 10% discount on the new subtotal
    cart.add_item('MOU-01', 1)  # 59.90
    assert cart.total() == 53.91


def test_discount_does_not_stack_or_go_negative(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('USB-01', 1)  # 9.99

    assert cart.apply_discount('WELCOME10') is True
    assert cart.apply_discount('WELCOME10') is True
    assert cart.total() == 8.99  # Not discounted twice

    assert cart.apply_discount('SAVE15') is True
    assert cart.total() == 0.0  # Clamped at 0.00, not -5.01


def test_repeated_cart_load_does_not_duplicate_items(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('USB-01', 2)
    cart.save()

    cart.load()
    cart.load()
    assert len(cart.lines) == 1
    assert cart.lines[0].quantity == 2


def test_sql_injection_blocked_in_repository(repo):
    assert repo.get_product("' OR '1'='1") is None
    assert repo.get_saved_cart("' OR '1'='1") == []


def test_list_orders_only_returns_requested_user(repo):
    repo.save_order('alice', 50.0, 'paid', 'req-a1')
    repo.save_order('bob', 75.0, 'paid', 'req-b1')

    alice_orders = repo.list_orders('alice')
    assert len(alice_orders) == 1
    assert alice_orders[0][1] == 'alice'


def test_checkout_empty_cart(repo):
    cart = ShoppingCart('u1', repo)
    gateway = FakePaymentGateway(should_approve=True)
    result = CheckoutService(repo, gateway).checkout(cart, 'TOK', 'req-empty')

    assert result.status == 'empty'
    assert result.order_id is None
    assert len(gateway.calls) == 0


def test_checkout_success_deducts_stock_and_clears_cart(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('MOU-01', 2)
    cart.save()

    gateway = FakePaymentGateway(should_approve=True)
    result = CheckoutService(repo, gateway).checkout(cart, 'TOK', 'req-ok')

    assert result.status == 'paid'
    assert result.order_id is not None
    assert result.total == 59.90
    assert repo.get_product('MOU-01').stock == 18
    assert len(cart.lines) == 0
    assert repo.get_saved_cart('u1') == []


def test_checkout_declined_preserves_stock_and_cart(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('LAP-01', 2)

    gateway = FakePaymentGateway(should_approve=False)
    result = CheckoutService(repo, gateway).checkout(cart, 'TOK', 'req-declined')

    assert result.status == 'declined'
    assert repo.get_product('LAP-01').stock == 5
    assert len(cart.lines) == 1
    assert cart.lines[0].quantity == 2


def test_checkout_payment_error_preserves_stock_and_cart(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('LAP-01', 1)

    gateway = ExplodingPaymentGateway()
    result = CheckoutService(repo, gateway).checkout(cart, 'TOK', 'req-err')

    assert result.status == 'payment_error'
    assert repo.get_product('LAP-01').stock == 5
    assert len(cart.lines) == 1


def test_checkout_detects_stock_change_before_charging(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('LAP-01', 4)  # Stock is 5 at add time

    # Another order buys 3 laptops before this user checks out
    assert repo.update_stock('LAP-01', 3) is True

    gateway = FakePaymentGateway(should_approve=True)
    result = CheckoutService(repo, gateway).checkout(cart, 'TOK', 'req-oos')

    assert result.status == 'out_of_stock'
    assert result.order_id is None
    assert len(gateway.calls) == 0
    assert repo.get_product('LAP-01').stock == 2


def test_checkout_idempotency_prevents_double_charge(repo):
    cart = ShoppingCart('u1', repo)
    cart.add_item('MOU-01', 2)

    gateway = FakePaymentGateway(should_approve=True)
    service = CheckoutService(repo, gateway)

    first = service.checkout(cart, 'TOK', 'req-dup-1')
    # Re-add item and retry with the exact same request_id
    cart.add_item('MOU-01', 2)
    second = service.checkout(cart, 'TOK', 'req-dup-1')

    assert first.order_id == second.order_id
    assert second.status == 'paid'
    assert len(gateway.calls) == 1
    assert repo.get_product('MOU-01').stock == 18