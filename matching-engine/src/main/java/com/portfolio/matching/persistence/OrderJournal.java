package com.portfolio.matching.persistence;

/**
 * Append-only audit of every submitted order. Persistence is best-effort:
 * the engine calls through synchronously, but a DB hiccup logs a warning
 * rather than propagating, so matching itself never throws on a journal
 * failure.
 */
public interface OrderJournal {

    void record(OrderEvent event);

    OrderJournal NOOP = event -> {};
}
