package com.portfolio.matching.book;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class OrderBookTest {

    private OrderBook book;

    @BeforeEach
    void setUp() {
        book = new OrderBook("AAPL");
    }

    @Test
    @DisplayName("empty book: limit order rests and shows at top")
    void limitRestsOnEmptyBook() {
        MatchResult r = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 10);

        assertThat(r.trades()).isEmpty();
        assertThat(r.remainingQuantity()).isEqualTo(10);
        assertThat(r.isResting()).isTrue();
        assertThat(r.restingOrderId()).isEqualTo(r.orderId());

        TopOfBook top = book.topOfBook();
        assertThat(top.bestBid()).isEqualByComparingTo("100.00");
        assertThat(top.bidSize()).isEqualTo(10);
        assertThat(top.bestAsk()).isNull();
        assertThat(top.spread()).isNull();
    }

    @Test
    @DisplayName("crossing limit fully fills against resting opposite")
    void crossingLimitFullyFills() {
        long sellId = book.submitLimit(Side.SELL, new BigDecimal("100.00"), 10).orderId();
        MatchResult r = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 10);

        assertThat(r.trades()).hasSize(1);
        Trade t = r.trades().get(0);
        assertThat(t.makerOrderId()).isEqualTo(sellId);
        assertThat(t.takerOrderId()).isEqualTo(r.orderId());
        assertThat(t.price()).isEqualByComparingTo("100.00");
        assertThat(t.quantity()).isEqualTo(10);

        assertThat(r.remainingQuantity()).isZero();
        assertThat(r.isResting()).isFalse();
        assertThat(book.topOfBook().bestBid()).isNull();
        assertThat(book.topOfBook().bestAsk()).isNull();
        assertThat(book.topOfBook().lastTradePrice()).isEqualByComparingTo("100.00");
    }

    @Test
    @DisplayName("trade price is the maker's price when limits differ")
    void tradeExecutesAtMakerPrice() {
        book.submitLimit(Side.SELL, new BigDecimal("100.00"), 5);
        MatchResult r = book.submitLimit(Side.BUY, new BigDecimal("101.50"), 5);

        assertThat(r.trades().get(0).price()).isEqualByComparingTo("100.00");
    }

    @Test
    @DisplayName("non-crossing limit does not trade and rests")
    void nonCrossingRests() {
        book.submitLimit(Side.SELL, new BigDecimal("101.00"), 5);
        MatchResult r = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 5);

        assertThat(r.trades()).isEmpty();
        assertThat(r.isResting()).isTrue();
        TopOfBook top = book.topOfBook();
        assertThat(top.bestBid()).isEqualByComparingTo("100.00");
        assertThat(top.bestAsk()).isEqualByComparingTo("101.00");
        assertThat(top.spread()).isEqualByComparingTo("1.00");
    }

    @Test
    @DisplayName("price-time priority: earlier order at same price matches first")
    void priceTimePriority() {
        long first = book.submitLimit(Side.SELL, new BigDecimal("100.00"), 5).orderId();
        long second = book.submitLimit(Side.SELL, new BigDecimal("100.00"), 5).orderId();

        MatchResult r = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 5);

        assertThat(r.trades()).hasSize(1);
        assertThat(r.trades().get(0).makerOrderId()).isEqualTo(first);

        MatchResult r2 = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 5);
        assertThat(r2.trades()).hasSize(1);
        assertThat(r2.trades().get(0).makerOrderId()).isEqualTo(second);
    }

    @Test
    @DisplayName("partial fill of resting maker leaves the rest at the head of the level")
    void partialFillOfMaker() {
        long makerId = book.submitLimit(Side.SELL, new BigDecimal("100.00"), 10).orderId();
        MatchResult r = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 3);

        assertThat(r.trades()).hasSize(1);
        assertThat(r.trades().get(0).quantity()).isEqualTo(3);
        TopOfBook top = book.topOfBook();
        assertThat(top.bestAsk()).isEqualByComparingTo("100.00");
        assertThat(top.askSize()).isEqualTo(7);

        // Next incoming buy matches the same maker again.
        MatchResult r2 = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 5);
        assertThat(r2.trades().get(0).makerOrderId()).isEqualTo(makerId);
        assertThat(book.topOfBook().askSize()).isEqualTo(2);
    }

    @Test
    @DisplayName("incoming larger than top: rests the remainder")
    void incomingExceedsTopAndRests() {
        book.submitLimit(Side.SELL, new BigDecimal("100.00"), 5);
        MatchResult r = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 12);

        assertThat(r.trades()).hasSize(1);
        assertThat(r.trades().get(0).quantity()).isEqualTo(5);
        assertThat(r.remainingQuantity()).isEqualTo(7);
        assertThat(r.isResting()).isTrue();

        TopOfBook top = book.topOfBook();
        assertThat(top.bestAsk()).isNull();
        assertThat(top.bestBid()).isEqualByComparingTo("100.00");
        assertThat(top.bidSize()).isEqualTo(7);
    }

    @Test
    @DisplayName("multi-level sweep: one incoming consumes the top two ask levels")
    void multiLevelSweep() {
        book.submitLimit(Side.SELL, new BigDecimal("100.00"), 3);
        book.submitLimit(Side.SELL, new BigDecimal("100.50"), 4);
        book.submitLimit(Side.SELL, new BigDecimal("101.00"), 10);

        MatchResult r = book.submitLimit(Side.BUY, new BigDecimal("100.50"), 7);

        assertThat(r.trades()).hasSize(2);
        assertThat(r.trades().get(0).price()).isEqualByComparingTo("100.00");
        assertThat(r.trades().get(0).quantity()).isEqualTo(3);
        assertThat(r.trades().get(1).price()).isEqualByComparingTo("100.50");
        assertThat(r.trades().get(1).quantity()).isEqualTo(4);
        assertThat(r.remainingQuantity()).isZero();
        assertThat(book.topOfBook().bestAsk()).isEqualByComparingTo("101.00");
    }

    @Test
    @DisplayName("market buy sweeps best asks ignoring price")
    void marketBuySweeps() {
        book.submitLimit(Side.SELL, new BigDecimal("100.00"), 5);
        book.submitLimit(Side.SELL, new BigDecimal("105.00"), 5);

        MatchResult r = book.submitMarket(Side.BUY, 8);

        assertThat(r.trades()).hasSize(2);
        assertThat(r.trades().get(0).price()).isEqualByComparingTo("100.00");
        assertThat(r.trades().get(0).quantity()).isEqualTo(5);
        assertThat(r.trades().get(1).price()).isEqualByComparingTo("105.00");
        assertThat(r.trades().get(1).quantity()).isEqualTo(3);
        assertThat(r.remainingQuantity()).isZero();
        assertThat(r.isResting()).isFalse();
    }

    @Test
    @DisplayName("market against empty book returns remaining qty, no trades")
    void marketAgainstEmptyBook() {
        MatchResult r = book.submitMarket(Side.BUY, 10);

        assertThat(r.trades()).isEmpty();
        assertThat(r.remainingQuantity()).isEqualTo(10);
        assertThat(r.isResting()).isFalse();
    }

    @Test
    @DisplayName("cancel removes resting order and frees the level if last")
    void cancelRemovesAndFreesLevel() {
        long id = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 5).orderId();
        assertThat(book.topOfBook().bestBid()).isEqualByComparingTo("100.00");

        boolean ok = book.cancel(id);
        assertThat(ok).isTrue();
        assertThat(book.topOfBook().bestBid()).isNull();
        assertThat(book.restingOrderCount()).isZero();
    }

    @Test
    @DisplayName("cancel of middle order preserves FIFO of others at same level")
    void cancelMiddlePreservesFifo() {
        long a = book.submitLimit(Side.SELL, new BigDecimal("100.00"), 1).orderId();
        long b = book.submitLimit(Side.SELL, new BigDecimal("100.00"), 1).orderId();
        long c = book.submitLimit(Side.SELL, new BigDecimal("100.00"), 1).orderId();

        assertThat(book.cancel(b)).isTrue();
        assertThat(book.topOfBook().askSize()).isEqualTo(2);

        MatchResult r1 = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 1);
        assertThat(r1.trades().get(0).makerOrderId()).isEqualTo(a);

        MatchResult r2 = book.submitLimit(Side.BUY, new BigDecimal("100.00"), 1);
        assertThat(r2.trades().get(0).makerOrderId()).isEqualTo(c);
    }

    @Test
    @DisplayName("cancel of unknown id returns false")
    void cancelUnknown() {
        assertThat(book.cancel(99999L)).isFalse();
    }

    @Test
    @DisplayName("snapshot returns top N levels ordered correctly per side")
    void snapshotOrdering() {
        book.submitLimit(Side.BUY, new BigDecimal("99.00"), 1);
        book.submitLimit(Side.BUY, new BigDecimal("100.00"), 2);
        book.submitLimit(Side.BUY, new BigDecimal("98.00"), 3);
        book.submitLimit(Side.SELL, new BigDecimal("101.00"), 4);
        book.submitLimit(Side.SELL, new BigDecimal("102.00"), 5);
        book.submitLimit(Side.SELL, new BigDecimal("103.00"), 6);

        BookSnapshot snap = book.snapshot(2);

        assertThat(snap.bids()).hasSize(2);
        assertThat(snap.bids().get(0).price()).isEqualByComparingTo("100.00");
        assertThat(snap.bids().get(1).price()).isEqualByComparingTo("99.00");
        assertThat(snap.asks()).hasSize(2);
        assertThat(snap.asks().get(0).price()).isEqualByComparingTo("101.00");
        assertThat(snap.asks().get(1).price()).isEqualByComparingTo("102.00");
    }

    @Test
    @DisplayName("scale-equivalent prices coalesce into one level")
    void scaleEquivalentPricesCoalesce() {
        book.submitLimit(Side.SELL, new BigDecimal("100.0"), 5);
        book.submitLimit(Side.SELL, new BigDecimal("100.00"), 5);
        book.submitLimit(Side.SELL, new BigDecimal("100.000"), 5);

        assertThat(book.snapshot(10).asks()).hasSize(1);
        assertThat(book.topOfBook().askSize()).isEqualTo(15);
    }

    @Test
    @DisplayName("rejects non-positive quantity")
    void rejectsNonPositiveQuantity() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> book.submitLimit(Side.BUY, new BigDecimal("100.00"), 0));
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> book.submitMarket(Side.SELL, -5));
    }

    @Test
    @DisplayName("symmetric: sell crosses into resting bids")
    void sellCrossesBids() {
        book.submitLimit(Side.BUY, new BigDecimal("100.00"), 10);
        book.submitLimit(Side.BUY, new BigDecimal("99.00"), 10);

        MatchResult r = book.submitLimit(Side.SELL, new BigDecimal("99.50"), 7);
        assertThat(r.trades()).hasSize(1);
        assertThat(r.trades().get(0).price()).isEqualByComparingTo("100.00");
        assertThat(r.trades().get(0).quantity()).isEqualTo(7);
        assertThat(book.topOfBook().bestBid()).isEqualByComparingTo("100.00");
        assertThat(book.topOfBook().bidSize()).isEqualTo(3);
    }

    @Test
    @DisplayName("orderIds are unique and monotonically increasing")
    void orderIdsAreUnique() {
        List<Long> ids = List.of(
                book.submitLimit(Side.BUY, new BigDecimal("100.00"), 1).orderId(),
                book.submitLimit(Side.SELL, new BigDecimal("101.00"), 1).orderId(),
                book.submitMarket(Side.BUY, 1).orderId(),
                book.submitLimit(Side.SELL, new BigDecimal("102.00"), 1).orderId());
        assertThat(ids).doesNotHaveDuplicates().isSorted();
    }
}
