package com.portfolio.matching.book;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.NavigableMap;
import java.util.TreeMap;

/**
 * A price-time-priority limit order book for one symbol.
 *
 * Internals:
 *   bids:         TreeMap<BigDecimal, PriceLevel> sorted descending (best bid first)
 *   asks:         TreeMap<BigDecimal, PriceLevel> sorted ascending  (best ask first)
 *   ordersById:   HashMap<Long, Order> for O(1) cancel
 *   each level:   a doubly-linked FIFO of orders, so cancel is O(1) once located
 *
 * Complexities:
 *   submitLimit / submitMarket: O(k log n) where k is the number of price
 *                               levels swept and n is the number of resting levels.
 *   cancel:                     O(1) lookup + O(1) unlink + O(log n) tree-remove
 *                               (only if the level becomes empty).
 *   topOfBook:                  O(1).
 *
 * All public methods are synchronized; the engine is single-threaded with respect
 * to its own state, which is intentional because matching must be linearizable.
 */
public final class OrderBook {

    private final String symbol;
    private final NavigableMap<BigDecimal, PriceLevel> bids;
    private final NavigableMap<BigDecimal, PriceLevel> asks;
    private final Map<Long, Order> ordersById;
    private long nextOrderId = 1L;
    private BigDecimal lastTradePrice;

    public OrderBook(String symbol) {
        this.symbol = symbol;
        this.bids = new TreeMap<>(Comparator.reverseOrder());
        this.asks = new TreeMap<>();
        this.ordersById = new HashMap<>();
    }

    public String symbol() {
        return symbol;
    }

    public synchronized MatchResult submitLimit(Side side, BigDecimal price, long quantity) {
        if (price == null) {
            throw new IllegalArgumentException("limit order requires a price");
        }
        if (quantity <= 0) {
            throw new IllegalArgumentException("quantity must be positive");
        }
        long takerId = nextOrderId++;
        long ts = System.currentTimeMillis();
        List<Trade> trades = new ArrayList<>();
        long remaining = match(takerId, side, price, quantity, ts, trades);

        Long restingId = null;
        if (remaining > 0) {
            Order resting = new Order(takerId, side, price, remaining, ts);
            NavigableMap<BigDecimal, PriceLevel> sameSide = (side == Side.BUY) ? bids : asks;
            PriceLevel level = sameSide.computeIfAbsent(price, PriceLevel::new);
            level.append(resting);
            ordersById.put(takerId, resting);
            restingId = takerId;
        }
        return new MatchResult(takerId, List.copyOf(trades), remaining, restingId);
    }

    public synchronized MatchResult submitMarket(Side side, long quantity) {
        if (quantity <= 0) {
            throw new IllegalArgumentException("quantity must be positive");
        }
        long takerId = nextOrderId++;
        long ts = System.currentTimeMillis();
        List<Trade> trades = new ArrayList<>();
        long remaining = match(takerId, side, null, quantity, ts, trades);
        return new MatchResult(takerId, List.copyOf(trades), remaining, null);
    }

    public synchronized boolean cancel(long orderId) {
        Order o = ordersById.remove(orderId);
        if (o == null) {
            return false;
        }
        PriceLevel level = o.level;
        BigDecimal levelPrice = level.price;
        Side side = o.side();
        level.unlink(o);
        if (level.isEmpty()) {
            NavigableMap<BigDecimal, PriceLevel> book = (side == Side.BUY) ? bids : asks;
            book.remove(levelPrice);
        }
        return true;
    }

    public synchronized TopOfBook topOfBook() {
        BigDecimal bestBid = null;
        Long bidSize = null;
        if (!bids.isEmpty()) {
            Map.Entry<BigDecimal, PriceLevel> e = bids.firstEntry();
            bestBid = e.getKey();
            bidSize = e.getValue().totalQuantity;
        }
        BigDecimal bestAsk = null;
        Long askSize = null;
        if (!asks.isEmpty()) {
            Map.Entry<BigDecimal, PriceLevel> e = asks.firstEntry();
            bestAsk = e.getKey();
            askSize = e.getValue().totalQuantity;
        }
        BigDecimal spread = (bestBid != null && bestAsk != null)
                ? bestAsk.subtract(bestBid)
                : null;
        return new TopOfBook(symbol, bestBid, bidSize, bestAsk, askSize, spread, lastTradePrice);
    }

    public synchronized BookSnapshot snapshot(int depth) {
        if (depth <= 0) {
            throw new IllegalArgumentException("depth must be positive");
        }
        return new BookSnapshot(symbol, topN(bids, depth), topN(asks, depth), lastTradePrice);
    }

    public synchronized int restingOrderCount() {
        return ordersById.size();
    }

    /**
     * Returns a random resting order id, or null if the book is empty. Used by
     * the simulation driver to pick a cancel target; uses the caller-provided
     * random index to keep the engine deterministic when the caller is seeded.
     */
    public synchronized Long pickRestingOrderId(int randomIndex) {
        if (ordersById.isEmpty()) {
            return null;
        }
        int idx = Math.floorMod(randomIndex, ordersById.size());
        int i = 0;
        for (Long id : ordersById.keySet()) {
            if (i++ == idx) {
                return id;
            }
        }
        return null;
    }

    /**
     * Sweeps the opposite side until the incoming order is exhausted or no
     * acceptable price remains. Pass {@code limitPrice == null} for market
     * orders, which accept any price.
     */
    private long match(
            long takerId,
            Side takerSide,
            BigDecimal limitPrice,
            long quantity,
            long ts,
            List<Trade> out) {
        NavigableMap<BigDecimal, PriceLevel> opposite =
                (takerSide == Side.BUY) ? asks : bids;
        long remaining = quantity;

        while (remaining > 0 && !opposite.isEmpty()) {
            Map.Entry<BigDecimal, PriceLevel> bestEntry = opposite.firstEntry();
            BigDecimal restingPrice = bestEntry.getKey();

            if (limitPrice != null) {
                int cmp = restingPrice.compareTo(limitPrice);
                boolean acceptable = (takerSide == Side.BUY) ? cmp <= 0 : cmp >= 0;
                if (!acceptable) {
                    break;
                }
            }

            PriceLevel level = bestEntry.getValue();
            while (remaining > 0 && level.head != null) {
                Order maker = level.head;
                long fillQty = Math.min(remaining, maker.remainingQuantity());
                out.add(new Trade(maker.id(), takerId, symbol, restingPrice, fillQty, ts));
                remaining -= fillQty;
                maker.decreaseQuantity(fillQty);
                level.recordFill(fillQty);
                lastTradePrice = restingPrice;
                if (maker.remainingQuantity() == 0) {
                    // recordFill already debited totalQuantity, so unlink's
                    // totalQuantity -= maker.remainingQuantity() subtracts 0.
                    level.unlink(maker);
                    ordersById.remove(maker.id());
                }
            }
            if (level.isEmpty()) {
                opposite.remove(restingPrice);
            }
        }
        return remaining;
    }

    private static List<BookLevel> topN(NavigableMap<BigDecimal, PriceLevel> side, int depth) {
        List<BookLevel> out = new ArrayList<>(depth);
        int n = 0;
        for (Map.Entry<BigDecimal, PriceLevel> e : side.entrySet()) {
            if (n++ >= depth) {
                break;
            }
            out.add(new BookLevel(e.getKey(), e.getValue().totalQuantity));
        }
        return out;
    }
}
