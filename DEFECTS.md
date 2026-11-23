# Defects Found and Fixed

Below are the 10 defects identified in the starter order-processing app, what could go wrong with each one, and how they were fixed.

## 1. SQL Injection in `repository.py` (`get_product`, `get_saved_cart`)
- **What went wrong:** Both queries built SQL strings using f-strings (`WHERE sku = '{sku}'` and `WHERE user_id = '{user_id}'`). A crafted input could bypass the filter or inject arbitrary SQL.
- **Fix:** Replaced string formatting with parameterized queries (`?`).

## 2. `list_orders` Returned All Users' Orders (`repository.py`)
- **What went wrong:** `list_orders(user_id)` accepted a `user_id` parameter but never used it in the SQL query, returning every customer's orders instead of just the requested user's.
- **Fix:** Added `WHERE user_id = ?` to the query.

## 3. No Quantity Validation in Cart (`cart.py`)
- **What went wrong:** `add_item` and `remove_item` didn't check if `quantity` was a positive integer. Passing `0` or a negative number could add negative quantities (lowering the cart total) or actually *increase* item counts when calling `remove_item`.
- **Fix:** Added a `_is_valid_quantity` helper to reject non-integers, booleans, zero, and negative numbers.

## 4. Duplicate Adds Bypassed Stock Limits (`cart.py`)
- **What went wrong:** `add_item` only checked `product.stock < quantity` for the incoming call, ignoring how many of that item were already in the cart. A user could add 3 of an item with 5 in stock, then add 3 more to end up with 6.
- **Fix:** Checked `existing_quantity + quantity > product.stock` before updating the cart.

## 5. Stale Discounts, Stacking, and Negative Totals (`cart.py`)
- **What went wrong:** `apply_discount` saved a static `discounted_total` based on `self.total()`. Editing the cart afterward left the total stale, applying a code twice stacked the discount, and `SAVE15` could push the total below `$0.00`.
- **Fix:** Removed `discounted_total` and made `total()` calculate dynamically from `subtotal()` and `self.discount_code`, clamped at `0.0` and rounded to 2 decimal places.

## 6. Repeated `load()` Calls Duplicated Cart Items (`cart.py`)
- **What went wrong:** `ShoppingCart.load()` called `add_item` for every row in `saved_cart` without clearing `self.lines` first, so loading a cart twice doubled every quantity.
- **Fix:** Cleared `self.lines` and `self.discount_code` at the start of `load()`.

## 7. Stock Deducted Before Payment and Cart Cleared on Failure (`checkout.py`, `repository.py`)
- **What went wrong:** `checkout()` deducted inventory before calling the payment gateway, and still cleared the user's cart even if the payment was declined or threw an exception. Inventory was permanently lost on failed checkouts.
- **Fix:** Moved stock deduction to happen only *after* payment is approved, inside a single atomic SQLite transaction (`deduct_stock_for_lines`) that checks `stock >= quantity`. If payment fails or errors out, stock is untouched and the cart stays intact.

## 8. No Stock Re-Validation at Checkout (`checkout.py`)
- **What went wrong:** Stock was only checked when adding an item to the cart. If stock dropped before checkout, the user would still be charged and inventory could go negative.
- **Fix:** Re-checked live stock for every cart line before charging the payment gateway. If any item is short, checkout returns `out_of_stock` without charging.

## 9. No Duplicate Request Protection / Idempotency (`checkout.py`, `repository.py`)
- **What went wrong:** Submitting the same `request_id` twice charged the payment gateway twice, deducted stock twice, and created duplicate orders.
- **Fix:** Added `get_order_by_request_id` in `repository.py` and checked it at the start of `checkout()`. Repeated requests with the same `request_id` return the original `OrderResult` without charging again. Missing/blank `request_id` values are rejected with `invalid_request`.

## 10. Payment Token Logged to Stdout (`checkout.py`)
- **What went wrong:** `checkout()` ran `print(f'Charging payment token: {payment_token}')`, exposing sensitive payment tokens in console output/logs.
- **Fix:** Removed the print statement.

## Assumptions
- If a payment is declined or raises an exception, we still record the failed order attempt in the `orders` table (with status `declined` or `payment_error`), keep the user's cart intact so they can retry, and do not deduct stock.
- Only one discount code can be active at a time; applying a new valid code replaces the previous one.
- A non-empty `request_id` is required for checkout so duplicate submissions can be detected reliably.

## Test Results
Run locally with:
```bash
python -m pytest -q