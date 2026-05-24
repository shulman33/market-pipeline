package com.portfolio.matching.persistence;

import com.portfolio.matching.book.OrderType;
import com.portfolio.matching.book.Side;
import java.math.BigDecimal;

public record OrderEvent(
        long orderId,
        String symbol,
        Side side,
        OrderType type,
        BigDecimal price,
        long quantity,
        long timestampMillis,
        long remainingQuantity,
        boolean resting) {
}
