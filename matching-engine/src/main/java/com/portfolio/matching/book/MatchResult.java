package com.portfolio.matching.book;

import java.util.List;

/**
 * Outcome of a single submit. orderId is always assigned (even for fully-filled
 * or fully-rejected market orders). restingOrderId is non-null only when the
 * order is a limit order that did not fully execute and now rests on the book.
 */
public record MatchResult(
        long orderId,
        List<Trade> trades,
        long remainingQuantity,
        Long restingOrderId) {

    public boolean isFullyFilled() {
        return remainingQuantity == 0;
    }

    public boolean isResting() {
        return restingOrderId != null;
    }
}
