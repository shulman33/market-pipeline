package com.portfolio.matching.persistence;

import com.portfolio.matching.book.Trade;
import java.util.Collection;

public interface TradeWriter {

    void writeAll(Collection<Trade> trades);

    TradeWriter NOOP = trades -> {};
}
