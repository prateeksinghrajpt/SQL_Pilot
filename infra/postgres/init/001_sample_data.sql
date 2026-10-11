CREATE TABLE IF NOT EXISTS customers (
    id BIGSERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    city TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    order_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'shipped', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0)
);

CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);

INSERT INTO customers (full_name, email, city) VALUES
    ('Aarav Sharma', 'aarav@example.com', 'Pune'),
    ('Diya Patel', 'diya@example.com', 'Mumbai'),
    ('Kabir Verma', 'kabir@example.com', 'Delhi'),
    ('Meera Iyer', 'meera@example.com', 'Bengaluru')
ON CONFLICT (email) DO NOTHING;

INSERT INTO products (name, category, unit_price) VALUES
    ('Wireless Mouse', 'Accessories', 799.00),
    ('Mechanical Keyboard', 'Accessories', 3499.00),
    ('USB-C Hub', 'Accessories', 1899.00),
    ('27-inch Monitor', 'Displays', 15999.00),
    ('Laptop Stand', 'Accessories', 1299.00)
ON CONFLICT DO NOTHING;

INSERT INTO orders (customer_id, order_date, status)
SELECT c.id, v.order_date::date, v.status
FROM (VALUES
    ('aarav@example.com', '2026-01-12', 'paid'),
    ('aarav@example.com', '2026-03-05', 'shipped'),
    ('diya@example.com', '2026-02-18', 'paid'),
    ('kabir@example.com', '2026-04-09', 'pending'),
    ('meera@example.com', '2026-05-21', 'shipped')
) AS v(email, order_date, status)
JOIN customers c ON c.email = v.email
WHERE NOT EXISTS (
    SELECT 1 FROM orders o
    WHERE o.customer_id = c.id
      AND o.order_date = v.order_date::date
      AND o.status = v.status
);

INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT o.id, p.id, v.quantity, p.unit_price
FROM (VALUES
    ('aarav@example.com', '2026-01-12', 'Wireless Mouse', 2),
    ('aarav@example.com', '2026-01-12', 'Laptop Stand', 1),
    ('aarav@example.com', '2026-03-05', '27-inch Monitor', 1),
    ('diya@example.com', '2026-02-18', 'Mechanical Keyboard', 1),
    ('kabir@example.com', '2026-04-09', 'USB-C Hub', 2),
    ('meera@example.com', '2026-05-21', 'Wireless Mouse', 1)
) AS v(email, order_date, product_name, quantity)
JOIN customers c ON c.email = v.email
JOIN orders o ON o.customer_id = c.id AND o.order_date = v.order_date::date
JOIN products p ON p.name = v.product_name
WHERE NOT EXISTS (
    SELECT 1 FROM order_items oi
    WHERE oi.order_id = o.id AND oi.product_id = p.id
);
