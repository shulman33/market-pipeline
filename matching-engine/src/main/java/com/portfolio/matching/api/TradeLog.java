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
 * Per-symbol bounded ring buffer of recent trades. Newest first so a
 * "recent N" query is the first N elements without any reverse step.
 */
public final class TradeLog {

    private static final int CAPACITY_PER_SYMBOL = 1000;

    private final Map<String, Deque<Trade>> bySymbol = new HashMap<>();

    public synchronized void append(Trade t) {
        appendOne(t);
    }

    public synchronized void appendAll(Collection<Trade> trades) {
        for (Trade t : trades) {
            appendOne(t);
        }
    }

    private void appendOne(Trade t) {
        Deque<Trade> q = bySymbol.computeIfAbsent(t.symbol(), s -> new ArrayDeque<>(CAPACITY_PER_SYMBOL));
        q.addFirst(t);
        if (q.size() > CAPACITY_PER_SYMBOL) {
            q.removeLast();
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
