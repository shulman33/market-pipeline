package com.portfolio.matching.sim;

import com.portfolio.matching.book.OrderBook;
import com.portfolio.matching.book.Side;
import com.portfolio.matching.engine.Engine;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Random;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Produces plausible synthetic order flow for one symbol: 70% limit orders
 * normally distributed around a reference price, 20% market orders alternating
 * sides, 10% cancels of a random resting order. One thread per generator so
 * the OrderBook's coarse synchronization is uncontended on the producer side.
 * Deterministic given the seed.
 */
public final class SyntheticOrderGenerator {

    private static final Logger log = LoggerFactory.getLogger(SyntheticOrderGenerator.class);
    private static final long TICK_MILLIS = 50L;
    private static final double PRICE_STDDEV = 0.50;
    private static final int MAX_LIMIT_QTY = 10;
    private static final int MAX_MARKET_QTY = 5;

    private final Engine engine;
    private final String symbol;
    private final BigDecimal basePrice;
    private final Random rng;
    private final ScheduledExecutorService scheduler;

    public SyntheticOrderGenerator(Engine engine, String symbol, BigDecimal basePrice, long seed) {
        this.engine = engine;
        this.symbol = symbol;
        this.basePrice = basePrice;
        this.rng = new Random(seed);
        this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "gen-" + symbol);
            t.setDaemon(true);
            return t;
        });
    }

    public void start() {
        scheduler.scheduleAtFixedRate(this::tickQuietly, 100L, TICK_MILLIS, TimeUnit.MILLISECONDS);
        log.info("generator started for {} (base={})", symbol, basePrice);
    }

    public void stop() {
        scheduler.shutdownNow();
    }

    private void tickQuietly() {
        try {
            tick();
        } catch (RuntimeException e) {
            log.warn("generator tick failed for {}: {}", symbol, e.getMessage());
        }
    }

    void tick() {
        int roll = rng.nextInt(100);
        if (roll < 70) {
            submitLimit();
        } else if (roll < 90) {
            submitMarket();
        } else {
            cancelRandom();
        }
    }

    private void submitLimit() {
        Side side = rng.nextBoolean() ? Side.BUY : Side.SELL;
        double offset = rng.nextGaussian() * PRICE_STDDEV;
        BigDecimal price = basePrice
                .add(BigDecimal.valueOf(offset))
                .setScale(2, RoundingMode.HALF_UP);
        if (price.signum() <= 0) {
            return;
        }
        long qty = 1L + rng.nextInt(MAX_LIMIT_QTY);
        engine.submitLimit(symbol, side, price, qty);
    }

    private void submitMarket() {
        Side side = rng.nextBoolean() ? Side.BUY : Side.SELL;
        long qty = 1L + rng.nextInt(MAX_MARKET_QTY);
        engine.submitMarket(symbol, side, qty);
    }

    private void cancelRandom() {
        OrderBook book = engine.book(symbol);
        if (book == null) {
            return;
        }
        Long id = book.pickRestingOrderId(rng.nextInt());
        if (id != null) {
            engine.cancel(id);
        }
    }
}
