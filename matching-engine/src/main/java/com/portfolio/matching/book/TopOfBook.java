package com.portfolio.matching.book;

import java.math.BigDecimal;

public record TopOfBook(
        String symbol,
        BigDecimal bestBid,
        Long bidSize,
        BigDecimal bestAsk,
        Long askSize,
        BigDecimal spread,
        BigDecimal lastTradePrice) {
}
