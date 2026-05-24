package com.portfolio.matching.persistence;

import com.portfolio.matching.book.OrderBook;
import com.portfolio.matching.book.TopOfBook;
import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import java.util.Collection;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import javax.sql.DataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Writes a top-of-book row per symbol once a second. Gives the dashboard a
 * time series even on quiet symbols where no trade has happened recently.
 */
public final class SnapshotWriter {

    private static final Logger log = LoggerFactory.getLogger(SnapshotWriter.class);
    private static final String SQL =
            "INSERT INTO me_book_snapshots "
                    + "(symbol, ts, best_bid, bid_size, best_ask, ask_size, spread, last_trade_price) "
                    + "VALUES (?, ?, ?, ?, ?, ?, ?, ?)";

    private final DataSource ds;
    private final Collection<OrderBook> books;
    private final ScheduledExecutorService scheduler;

    public SnapshotWriter(DataSource ds, Collection<OrderBook> books) {
        this.ds = ds;
        this.books = books;
        this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "snapshot-writer");
            t.setDaemon(true);
            return t;
        });
    }

    public void start() {
        scheduler.scheduleAtFixedRate(this::snapshotAllQuietly, 1L, 1L, TimeUnit.SECONDS);
    }

    public void stop() {
        scheduler.shutdownNow();
    }

    private void snapshotAllQuietly() {
        try {
            snapshotAll();
        } catch (RuntimeException e) {
            log.warn("snapshot tick failed: {}", e.getMessage());
        }
    }

    private void snapshotAll() {
        try (Connection c = ds.getConnection();
                PreparedStatement ps = c.prepareStatement(SQL)) {
            Timestamp ts = new Timestamp(System.currentTimeMillis());
            for (OrderBook book : books) {
                TopOfBook t = book.topOfBook();
                ps.setString(1, t.symbol());
                ps.setTimestamp(2, ts);
                setNumeric(ps, 3, t.bestBid());
                setLong(ps, 4, t.bidSize());
                setNumeric(ps, 5, t.bestAsk());
                setLong(ps, 6, t.askSize());
                setNumeric(ps, 7, t.spread());
                setNumeric(ps, 8, t.lastTradePrice());
                ps.addBatch();
            }
            ps.executeBatch();
        } catch (SQLException e) {
            log.warn("snapshot insert failed: {}", e.getMessage());
        }
    }

    private static void setNumeric(PreparedStatement ps, int idx, BigDecimal v) throws SQLException {
        if (v == null) {
            ps.setNull(idx, Types.NUMERIC);
        } else {
            ps.setBigDecimal(idx, v);
        }
    }

    private static void setLong(PreparedStatement ps, int idx, Long v) throws SQLException {
        if (v == null) {
            ps.setNull(idx, Types.BIGINT);
        } else {
            ps.setLong(idx, v);
        }
    }
}
