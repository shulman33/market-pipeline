package com.portfolio.matching.persistence;

import com.portfolio.matching.book.OrderType;
import com.portfolio.matching.book.Side;
import java.math.BigDecimal;

/**
 * Append-only audit of every submitted order. Implementations should be cheap
 * and non-blocking from the engine's perspective; a database hiccup must not
 * stall matching.
 */
public interface OrderJournal {

    void record(
            long orderId,
            String symbol,
            Side side,
            OrderType type,
            BigDecimal price,
            long quantity,
            long timestampMillis,
            long remainingQuantity,
            boolean resting);

    OrderJournal NOOP = (id, sym, side, type, price, qty, ts, remaining, resting) -> {};
}
