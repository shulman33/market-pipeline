package com.portfolio.matching.book;

import java.math.BigDecimal;

/**
 * A resting limit order. Carries intrusive doubly-linked-list pointers so the
 * book can unlink an order in O(1) once it has been located via the order-id
 * hashmap. Only limit orders are ever stored in an Order instance; market
 * orders are consumed transiently during matching and never rest.
 */
public final class Order {

    private final long id;
    private final Side side;
    private final BigDecimal price;
    private long remainingQuantity;
    private final long timestampMillis;

    Order prev;
    Order next;
    PriceLevel level;

    public Order(long id, Side side, BigDecimal price, long quantity, long timestampMillis) {
        this.id = id;
        this.side = side;
        this.price = price;
        this.remainingQuantity = quantity;
        this.timestampMillis = timestampMillis;
    }

    public long id() {
        return id;
    }

    public Side side() {
        return side;
    }

    public BigDecimal price() {
        return price;
    }

    public long remainingQuantity() {
        return remainingQuantity;
    }

    public long timestampMillis() {
        return timestampMillis;
    }

    void decreaseQuantity(long n) {
        this.remainingQuantity -= n;
    }
}
