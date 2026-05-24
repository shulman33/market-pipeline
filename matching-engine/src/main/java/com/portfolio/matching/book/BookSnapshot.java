package com.portfolio.matching.book;

import java.math.BigDecimal;
import java.util.List;

public record BookSnapshot(
        String symbol,
        List<BookLevel> bids,
        List<BookLevel> asks,
        BigDecimal lastTradePrice) {
}
