package com.portfolio.matching.book;

import java.math.BigDecimal;

/**
 * All resting orders at a single price, held in a FIFO doubly-linked list so
 * arrival-order priority is preserved and individual orders can be unlinked
 * in O(1) on cancel.
 */
final class PriceLevel {

    final BigDecimal price;
    Order head;
    Order tail;
    long totalQuantity;

    PriceLevel(BigDecimal price) {
        this.price = price;
    }

    void append(Order o) {
        o.level = this;
        if (tail == null) {
            head = o;
            tail = o;
        } else {
            tail.next = o;
            o.prev = tail;
            tail = o;
        }
        totalQuantity += o.remainingQuantity();
    }

    void unlink(Order o) {
        if (o.prev != null) {
            o.prev.next = o.next;
        } else {
            head = o.next;
        }
        if (o.next != null) {
            o.next.prev = o.prev;
        } else {
            tail = o.prev;
        }
        totalQuantity -= o.remainingQuantity();
        o.prev = null;
        o.next = null;
        o.level = null;
    }

    void recordFill(long quantity) {
        totalQuantity -= quantity;
    }

    boolean isEmpty() {
        return head == null;
    }
}
