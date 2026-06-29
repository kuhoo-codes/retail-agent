PRAGMA foreign_keys = ON;

CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('apparel', 'goods'))
) STRICT;

CREATE TABLE product_variants (
    sku TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(product_id),
    color TEXT,
    size TEXT,
    retail_price_cents INTEGER NOT NULL CHECK (retail_price_cents >= 0),
    UNIQUE (product_id, color, size)
) STRICT;

CREATE TABLE inventory (
    sku TEXT PRIMARY KEY REFERENCES product_variants(sku),
    on_hand_qty INTEGER NOT NULL CHECK (on_hand_qty >= 0),
    reorder_point INTEGER NOT NULL CHECK (reorder_point >= 0),
    reorder_qty INTEGER NOT NULL CHECK (reorder_qty > 0)
) STRICT;

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    joined_date TEXT NOT NULL
) STRICT;

CREATE TABLE suppliers (
    supplier_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
) STRICT;

CREATE TABLE supplier_catalog (
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    unit_cost_cents INTEGER NOT NULL CHECK (unit_cost_cents >= 0),
    lead_time_days INTEGER NOT NULL CHECK (lead_time_days >= 0),
    PRIMARY KEY (supplier_id, product_id)
) STRICT;

CREATE TABLE purchase_orders (
    po_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    quantity_ordered INTEGER NOT NULL CHECK (quantity_ordered > 0),
    quantity_received INTEGER NOT NULL DEFAULT 0 CHECK (quantity_received >= 0),
    status TEXT NOT NULL
        CHECK (status IN ('open', 'partial', 'received', 'cancelled')),
    created_date TEXT NOT NULL,
    CHECK (quantity_received <= quantity_ordered)
) STRICT;

CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    order_date TEXT NOT NULL,
    customer_id TEXT REFERENCES customers(customer_id),
    order_discount_pct INTEGER NOT NULL
        CHECK (order_discount_pct BETWEEN 0 AND 100),
    payment_method TEXT NOT NULL CHECK (payment_method IN ('cash', 'card'))
) STRICT;

CREATE TABLE order_lines (
    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    sku TEXT NOT NULL REFERENCES product_variants(sku),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    PRIMARY KEY (order_id, line_no),
    UNIQUE (order_id, line_no, sku)
) STRICT;

CREATE INDEX order_lines_sku_idx ON order_lines(sku);

CREATE TABLE returns (
    return_id TEXT PRIMARY KEY,
    return_date TEXT NOT NULL,
    order_id TEXT NOT NULL,
    order_line_no INTEGER NOT NULL,
    sku TEXT NOT NULL REFERENCES product_variants(sku),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    condition TEXT NOT NULL CHECK (condition IN ('good', 'damaged')),
    refund_amount_cents INTEGER NOT NULL CHECK (refund_amount_cents >= 0),
    FOREIGN KEY (order_id, order_line_no, sku)
        REFERENCES order_lines(order_id, line_no, sku)
) STRICT;

CREATE TABLE promotions (
    promo_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type = 'percent_off'),
    value_pct INTEGER NOT NULL CHECK (value_pct BETWEEN 0 AND 100),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('product', 'category')),
    scope_ref TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    CHECK (start_date <= end_date)
) STRICT;

CREATE INDEX promotions_window_idx ON promotions(start_date, end_date);
