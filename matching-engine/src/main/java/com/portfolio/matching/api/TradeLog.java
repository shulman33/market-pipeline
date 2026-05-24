package com.portfolio.matching.api;

import com.portfolio.matching.book.Trade;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Deque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Per-symbol bounded ring buffer of recent trades. Newest at the head so a
 * "recent N" query is the first N elements. Step 4 will swap reads to come
 * from Postgres; this in-memory log is what powers the HTTP /trades endpoint
 * in the meantime.
 */
public final class TradeLog {

    private static final int CAPACITY_PER_SYMBOL = 1000;

    private final Map<String, Deque<Trade>> bySymbol = new HashMap<>();

    public synchronized void append(Trade t) {
        Deque<Trade> q = bySymbol.computeIfAbsent(t.symbol(), s -> new ArrayDeque<>(CAPACITY_PER_SYMBOL));
        q.addFirst(t);
        while (q.size() > CAPACITY_PER_SYMBOL) {
            q.removeLast();
        }
    }

    public synchronized void appendAll(Collection<Trade> trades) {
        for (Trade t : trades) {
            append(t);
        }
    }

    public synchronized List<Trade> recent(String symbol, int limit) {
        Deque<Trade> q = bySymbol.get(symbol);
        if (q == null) {
            return List.of();
        }
        List<Trade> out = new ArrayList<>(Math.min(limit, q.size()));
        int n = 0;
        for (Trade t : q) {
            if (n++ >= limit) {
                break;
            }
            out.add(t);
        }
        return out;
    }
}
