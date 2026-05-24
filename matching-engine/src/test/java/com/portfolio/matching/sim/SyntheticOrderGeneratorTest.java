package com.portfolio.matching.sim;

import static org.assertj.core.api.Assertions.assertThat;

import com.portfolio.matching.api.TradeLog;
import com.portfolio.matching.book.OrderBook;
import com.portfolio.matching.book.TopOfBook;
import com.portfolio.matching.engine.Engine;
import com.portfolio.matching.persistence.OrderJournal;
import com.portfolio.matching.persistence.TradeWriter;
import java.math.BigDecimal;
import java.util.Map;
import org.junit.jupiter.api.Test;

class SyntheticOrderGeneratorTest {

    private static final BigDecimal BASE = new BigDecimal("100.00");
    private static final int TICKS = 500;
    private static final String SYMBOL = "X";

    private static Engine newEngine(OrderBook book, TradeLog tradeLog) {
        return new Engine(Map.of(SYMBOL, book), tradeLog, OrderJournal.NOOP, TradeWriter.NOOP);
    }

    @Test
    void deterministicGivenSameSeed() {
        OrderBook bookA = new OrderBook(SYMBOL);
        OrderBook bookB = new OrderBook(SYMBOL);
        TradeLog logA = new TradeLog();
        TradeLog logB = new TradeLog();
        SyntheticOrderGenerator a = new SyntheticOrderGenerator(newEngine(bookA, logA), SYMBOL, BASE, 42L);
        SyntheticOrderGenerator b = new SyntheticOrderGenerator(newEngine(bookB, logB), SYMBOL, BASE, 42L);

        for (int i = 0; i < TICKS; i++) {
            a.tick();
            b.tick();
        }

        TopOfBook tobA = bookA.topOfBook();
        TopOfBook tobB = bookB.topOfBook();
        assertThat(tobA.bestBid()).isEqualByComparingTo(tobB.bestBid());
        assertThat(tobA.bestAsk()).isEqualByComparingTo(tobB.bestAsk());
        assertThat(tobA.bidSize()).isEqualTo(tobB.bidSize());
        assertThat(tobA.askSize()).isEqualTo(tobB.askSize());
        assertThat(logA.recent(SYMBOL, 10000)).hasSameSizeAs(logB.recent(SYMBOL, 10000));
    }

    @Test
    void producesBookActivityAndTrades() {
        OrderBook book = new OrderBook(SYMBOL);
        TradeLog log = new TradeLog();
        SyntheticOrderGenerator gen = new SyntheticOrderGenerator(newEngine(book, log), SYMBOL, BASE, 42L);

        for (int i = 0; i < TICKS; i++) {
            gen.tick();
        }

        assertThat(book.restingOrderCount()).isPositive();
        assertThat(log.recent(SYMBOL, 10000)).isNotEmpty();
        TopOfBook top = book.topOfBook();
        assertThat(top.lastTradePrice()).isNotNull();
    }
}
