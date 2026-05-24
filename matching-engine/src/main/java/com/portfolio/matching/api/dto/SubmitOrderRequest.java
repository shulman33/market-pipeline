package com.portfolio.matching.api.dto;

import com.portfolio.matching.book.OrderType;
import com.portfolio.matching.book.Side;
import java.math.BigDecimal;

/**
 * Request body for POST /orders. Price is required for LIMIT, ignored for
 * MARKET. Jackson parses BigDecimal from JSON number or string.
 */
public record SubmitOrderRequest(
        String symbol,
        Side side,
        OrderType type,
        BigDecimal price,
        long quantity) {
}
