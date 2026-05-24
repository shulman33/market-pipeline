package com.portfolio.matching.engine;

import com.portfolio.matching.api.TradeLog;
import com.portfolio.matching.book.BookSnapshot;
import com.portfolio.matching.book.MatchResult;
import com.portfolio.matching.book.OrderBook;
import com.portfolio.matching.book.OrderType;
import com.portfolio.matching.book.Side;
import com.portfolio.matching.book.TopOfBook;
import com.portfolio.matching.book.Trade;
import com.portfolio.matching.persistence.OrderJournal;
import com.portfolio.matching.persistence.TradeWriter;
import java.math.BigDecimal;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Engine wires submission, in-memory matching, in-memory recent-trade cache,
 * and the optional Postgres writers into a single entry point. HttpServer and
 * SyntheticOrderGenerator both call through here so the journal and trade
 * writer see every fill from either source.
 */
public final class Engine {

    private final Map<String, OrderBook> books;
    private final TradeLog tradeLog;
    private final OrderJournal orderJournal;
    private final TradeWriter tradeWriter;

    public Engine(
            Map<String, OrderBook> books,
            TradeLog tradeLog,
            OrderJournal orderJournal,
            TradeWriter tradeWriter) {
        this.books = books;
        this.tradeLog = tradeLog;
        this.orderJournal = orderJournal;
        this.tradeWriter = tradeWriter;
    }

    public Set<String> symbols() {
        return books.keySet();
    }

    public OrderBook book(String symbol) {
        return books.get(symbol);
    }

    public Collection<OrderBook> books() {
        return books.values();
    }

    public MatchResult submitLimit(String symbol, Side side, BigDecimal price, long quantity) {
        OrderBook b = books.get(symbol);
        if (b == null) {
            return null;
        }
        long ts = System.currentTimeMillis();
        MatchResult r = b.submitLimit(side, price, quantity);
        record(symbol, side, OrderType.LIMIT, price, quantity, ts, r);
        return r;
    }

    public MatchResult submitMarket(String symbol, Side side, long quantity) {
        OrderBook b = books.get(symbol);
        if (b == null) {
            return null;
        }
        long ts = System.currentTimeMillis();
        MatchResult r = b.submitMarket(side, quantity);
        record(symbol, side, OrderType.MARKET, null, quantity, ts, r);
        return r;
    }

    public boolean cancel(long orderId) {
        for (OrderBook b : books.values()) {
            if (b.cancel(orderId)) {
                return true;
            }
        }
        return false;
    }

    public TopOfBook topOfBook(String symbol) {
        OrderBook b = books.get(symbol);
        return b == null ? null : b.topOfBook();
    }

    public BookSnapshot snapshot(String symbol, int depth) {
        OrderBook b = books.get(symbol);
        return b == null ? null : b.snapshot(depth);
    }

    public List<Trade> recentTrades(String symbol, int limit) {
        return tradeLog.recent(symbol, limit);
    }

    private void record(
            String symbol,
            Side side,
            OrderType type,
            BigDecimal price,
            long quantity,
            long ts,
            MatchResult r) {
        tradeLog.appendAll(r.trades());
        orderJournal.record(
                r.orderId(),
                symbol,
                side,
                type,
                price,
                quantity,
                ts,
                r.remainingQuantity(),
                r.isResting());
        tradeWriter.writeAll(r.trades());
    }
}
