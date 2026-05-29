-- Poizon Research DB 초기화
CREATE DATABASE IF NOT EXISTS poizon_research CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE poizon_research;

-- poizon_spu: 상품 기본 정보
CREATE TABLE IF NOT EXISTS poizon_spu (
    spu_id INT NOT NULL PRIMARY KEY,
    style_id VARCHAR(50) NOT NULL,
    item_name VARCHAR(500) NOT NULL,
    brand VARCHAR(100) NOT NULL,
    primary_cat VARCHAR(100) NOT NULL,
    spu_image VARCHAR(500) DEFAULT NULL,
    file_name VARCHAR(200) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- poizon_sku: 사이즈/가격 정보
CREATE TABLE IF NOT EXISTS poizon_sku (
    sku_id BIGINT NOT NULL PRIMARY KEY,
    spu_id INT NOT NULL,
    size_spec VARCHAR(100) DEFAULT NULL,
    Size_KR VARCHAR(10) DEFAULT NULL,
    Size_Apparel VARCHAR(10) DEFAULT NULL,
    sku_image VARCHAR(500) DEFAULT NULL,
    listing_status TINYINT DEFAULT 0,
    avg_30_day INT DEFAULT NULL,
    cn_lowest INT DEFAULT NULL,
    est_payout INT DEFAULT NULL,
    total_sales INT DEFAULT NULL,
    file_name VARCHAR(200) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_spu_id (spu_id),
    CONSTRAINT fk_sku_spu FOREIGN KEY (spu_id) REFERENCES poizon_spu (spu_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- poizon_spu_snapshot: 날짜별 SPU 스냅샷
CREATE TABLE IF NOT EXISTS poizon_spu_snapshot (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    spu_id INT NOT NULL,
    style_id VARCHAR(50) NOT NULL,
    item_name VARCHAR(500) NOT NULL,
    brand VARCHAR(100) NOT NULL,
    primary_cat VARCHAR(100) NOT NULL,
    spu_image VARCHAR(500) DEFAULT NULL,
    file_name VARCHAR(200) DEFAULT NULL,
    load_date DATE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_spu_date (spu_id, load_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- poizon_sku_snapshot: 날짜별 SKU 스냅샷
CREATE TABLE IF NOT EXISTS poizon_sku_snapshot (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sku_id BIGINT NOT NULL,
    spu_id INT NOT NULL,
    size_spec VARCHAR(100) DEFAULT NULL,
    Size_KR VARCHAR(10) DEFAULT NULL,
    Size_Apparel VARCHAR(10) DEFAULT NULL,
    sku_image VARCHAR(500) DEFAULT NULL,
    listing_status TINYINT DEFAULT 0,
    avg_30_day INT DEFAULT NULL,
    cn_lowest INT DEFAULT NULL,
    est_payout INT DEFAULT NULL,
    total_sales INT DEFAULT NULL,
    file_name VARCHAR(200) DEFAULT NULL,
    load_date DATE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sku_date (sku_id, load_date),
    INDEX idx_spu_id (spu_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- musinsa: 무신사 상품 매핑
CREATE TABLE IF NOT EXISTS musinsa (
    id INT AUTO_INCREMENT PRIMARY KEY,
    style_id VARCHAR(50) NOT NULL,
    brand VARCHAR(100) DEFAULT NULL,
    musinsa_link VARCHAR(500) DEFAULT NULL,
    product_name VARCHAR(500) DEFAULT NULL,
    price INT DEFAULT NULL,
    original_price INT DEFAULT NULL,
    discount_rate INT DEFAULT NULL,
    item_id VARCHAR(50) DEFAULT NULL,
    goods_no VARCHAR(50) DEFAULT NULL,
    sizes JSON COMMENT '사이즈별 재고',
    in_stock BOOLEAN DEFAULT FALSE,
    dwSkuid VARCHAR(50) DEFAULT NULL,
    musinsa_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_style_id (style_id),
    INDEX idx_brand (brand),
    INDEX idx_item_id (item_id),
    INDEX idx_musinsa_update (musinsa_update),
    INDEX idx_goods_no (goods_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- price_snapshot: 가격 비교 스냅샷
CREATE TABLE IF NOT EXISTS price_snapshot (
    id INT AUTO_INCREMENT PRIMARY KEY,
    spu_id INT NOT NULL,
    style_id VARCHAR(50) NOT NULL,
    brand VARCHAR(100) DEFAULT NULL,
    item_name VARCHAR(500) DEFAULT NULL,
    size_kr VARCHAR(10) DEFAULT NULL,
    poizon_est_payout INT DEFAULT NULL,
    poizon_cn_lowest INT DEFAULT NULL,
    poizon_avg_30_day INT DEFAULT NULL,
    poizon_total_sales INT DEFAULT NULL,
    musinsa_price INT DEFAULT NULL,
    musinsa_goods_no VARCHAR(50) DEFAULT NULL,
    musinsa_in_stock TINYINT(1) DEFAULT NULL,
    margin INT DEFAULT NULL,
    margin_pct DECIMAL(5,1) DEFAULT NULL,
    cn_margin INT DEFAULT NULL,
    cn_margin_pct DECIMAL(5,1) DEFAULT NULL,
    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_style_id (style_id),
    INDEX idx_spu_id (spu_id),
    INDEX idx_snapshot_at (snapshot_at),
    INDEX idx_brand (brand)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- pick_snapshot: 가격 경쟁력 Pick
CREATE TABLE IF NOT EXISTS pick_snapshot (
    id INT AUTO_INCREMENT PRIMARY KEY,
    spu_id INT NOT NULL,
    style_id VARCHAR(50) NOT NULL,
    brand VARCHAR(100) DEFAULT NULL,
    item_name VARCHAR(500) DEFAULT NULL,
    size_kr VARCHAR(10) DEFAULT NULL,
    poizon_est_payout INT DEFAULT NULL,
    poizon_cn_lowest INT DEFAULT NULL,
    poizon_avg_30_day INT DEFAULT NULL,
    poizon_total_sales INT DEFAULT NULL,
    musinsa_price INT DEFAULT NULL,
    musinsa_goods_no VARCHAR(50) DEFAULT NULL,
    musinsa_in_stock TINYINT(1) DEFAULT NULL,
    margin INT DEFAULT NULL,
    margin_pct DECIMAL(5,1) DEFAULT NULL,
    cn_margin INT DEFAULT NULL,
    cn_margin_pct DECIMAL(5,1) DEFAULT NULL,
    pick_reason VARCHAR(200) DEFAULT 'musinsa_price < cn_lowest * 1.15',
    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_style_id (style_id),
    INDEX idx_spu_id (spu_id),
    INDEX idx_snapshot_at (snapshot_at),
    INDEX idx_brand (brand)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
