-- Events
CREATE TABLE events (
    event_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    event_name VARCHAR(255) NOT NULL,
    event_date DATETIME NOT NULL,
    venue_name VARCHAR(255),
    total_seats INT NOT NULL,
    available_seats INT NOT NULL,
    status ENUM('UPCOMING', 'ON_SALE', 'SOLD_OUT', 'CANCELLED') DEFAULT 'UPCOMING',
    sale_start_time DATETIME,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sale_start_time (sale_start_time),
    INDEX idx_status (status)
);

-- Seats
CREATE TABLE seats (
    seat_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    event_id BIGINT NOT NULL,
    seat_number VARCHAR(20) NOT NULL,  -- e.g., "A1", "B5"
    section VARCHAR(50),                -- e.g., "VIP", "Balcony"
    row_number VARCHAR(10),
    seat_type ENUM('REGULAR', 'VIP', 'PREMIUM') DEFAULT 'REGULAR',
    price DECIMAL(10, 2) NOT NULL,
    status ENUM('AVAILABLE', 'RESERVED', 'BOOKED', 'BLOCKED') DEFAULT 'AVAILABLE',
    version BIGINT DEFAULT 0,  -- For optimistic locking
    reserved_by VARCHAR(50),   -- User ID or session ID
    reserved_until DATETIME,   -- Expiration time for reservation
    booking_id BIGINT,         -- Foreign key to bookings
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id) REFERENCES events(event_id),
    UNIQUE KEY uk_event_seat (event_id, seat_number),
    INDEX idx_event_status (event_id, status),
    INDEX idx_reserved_until (reserved_until)
);

-- Bookings (Confirmed)
CREATE TABLE bookings (
    booking_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    event_id BIGINT NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    total_amount DECIMAL(10, 2) NOT NULL,
    status ENUM('PENDING', 'CONFIRMED', 'CANCELLED', 'FAILED') DEFAULT 'PENDING',
    payment_id VARCHAR(100),
    payment_status ENUM('PENDING', 'SUCCESS', 'FAILED') DEFAULT 'PENDING',
    booking_reference VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP NULL,
    FOREIGN KEY (event_id) REFERENCES events(event_id),
    INDEX idx_user_id (user_id),
    INDEX idx_booking_reference (booking_reference),
    INDEX idx_status (status)
);

-- Booking Seats (Many-to-Many)
CREATE TABLE booking_seats (
    booking_seat_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    booking_id BIGINT NOT NULL,
    seat_id BIGINT NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (booking_id) REFERENCES bookings(booking_id),
    FOREIGN KEY (seat_id) REFERENCES seats(seat_id),
    UNIQUE KEY uk_booking_seat (booking_id, seat_id),
    INDEX idx_seat_id (seat_id)
);

-- Reservations (Temporary holds)
CREATE TABLE reservations (
    reservation_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    seat_id BIGINT NOT NULL,
    event_id BIGINT NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    session_id VARCHAR(100),
    expires_at DATETIME NOT NULL,
    status ENUM('ACTIVE', 'CONFIRMED', 'EXPIRED', 'CANCELLED') DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (seat_id) REFERENCES seats(seat_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id),
    INDEX idx_seat_id (seat_id),
    INDEX idx_expires_at (expires_at),
    INDEX idx_user_id (user_id)
);
