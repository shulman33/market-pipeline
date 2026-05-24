package com.portfolio.matching.book;

import java.math.BigDecimal;

/**
 * A single executed fill. Price is always the resting (maker) order's price,
 * which is the standard rule for price-time priority matching.
 */
public record Trade(
        long makerOrderId,
        long takerOrderId,
        String symbol,
        BigDecimal price,
        long quantity,
        long timestampMillis) {
}
