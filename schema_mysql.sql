CREATE TABLE IF NOT EXISTS settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS categories (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(200) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS suppliers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(200) NOT NULL,
    address VARCHAR(500) NOT NULL DEFAULT '',
    phone VARCHAR(50) NOT NULL DEFAULT '',
    active TINYINT NOT NULL DEFAULT 1 CHECK (active IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS customers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(200) NOT NULL,
    address VARCHAR(500) NOT NULL DEFAULT '',
    phone VARCHAR(50) NOT NULL DEFAULT '',
    active TINYINT NOT NULL DEFAULT 1 CHECK (active IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS employees (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(200) NOT NULL,
    hire_date DATE NULL,
    phone VARCHAR(50) NOT NULL DEFAULT '',
    active TINYINT NOT NULL DEFAULT 1 CHECK (active IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(200) NOT NULL,
    sku VARCHAR(200) NOT NULL UNIQUE,
    category_id INT NOT NULL,
    supplier_id INT NOT NULL,
    price BIGINT NOT NULL CHECK (price >= 0),
    stock INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
    reorder_level INT NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    active TINYINT NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    CONSTRAINT products_category_fk FOREIGN KEY (category_id) REFERENCES categories(id),
    CONSTRAINT products_supplier_fk FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS orders (
    id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT NULL,
    employee_id INT NOT NULL,
    created_at DATETIME NOT NULL,
    total BIGINT NOT NULL CHECK (total >= 0),
    payment VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','void')),
    source VARCHAR(20) NOT NULL DEFAULT 'live',
    void_reason VARCHAR(200) NULL,
    CONSTRAINT orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers(id),
    CONSTRAINT orders_employee_fk FOREIGN KEY (employee_id) REFERENCES employees(id),
    INDEX orders_date (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS order_items (
    id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    name VARCHAR(200) NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price BIGINT NOT NULL CHECK (unit_price >= 0),
    CONSTRAINT items_order_fk FOREIGN KEY (order_id) REFERENCES orders(id),
    CONSTRAINT items_product_fk FOREIGN KEY (product_id) REFERENCES products(id),
    INDEX items_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS stock_movements (
    id INT PRIMARY KEY AUTO_INCREMENT,
    product_id INT NOT NULL,
    quantity INT NOT NULL CHECK (quantity <> 0),
    reason VARCHAR(200) NOT NULL,
    created_at DATETIME NOT NULL,
    order_id INT NULL,
    CONSTRAINT movements_product_fk FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT movements_order_fk FOREIGN KEY (order_id) REFERENCES orders(id),
    INDEX movements_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
