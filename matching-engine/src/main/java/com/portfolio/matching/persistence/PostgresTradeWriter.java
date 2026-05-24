package com.portfolio.matching.persistence;

import com.portfolio.matching.book.Trade;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.Collection;
import javax.sql.DataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class PostgresTradeWriter implements TradeWriter {

    private static final Logger log = LoggerFactory.getLogger(PostgresTradeWriter.class);
    private static final String SQL =
            "INSERT INTO me_trades (symbol, maker_order_id, taker_order_id, price, quantity, ts) "
                    + "VALUES (?, ?, ?, ?, ?, ?)";

    private final DataSource ds;

    public PostgresTradeWriter(DataSource ds) {
        this.ds = ds;
    }

    @Override
    public void writeAll(Collection<Trade> trades) {
        if (trades.isEmpty()) {
            return;
        }
        try (Connection c = ds.getConnection();
                PreparedStatement ps = c.prepareStatement(SQL)) {
            for (Trade t : trades) {
                ps.setString(1, t.symbol());
                ps.setLong(2, t.makerOrderId());
                ps.setLong(3, t.takerOrderId());
                ps.setBigDecimal(4, t.price());
                ps.setLong(5, t.quantity());
                ps.setTimestamp(6, new Timestamp(t.timestampMillis()));
                ps.addBatch();
            }
            ps.executeBatch();
        } catch (SQLException e) {
            log.warn("trade batch insert failed ({} trades): {}", trades.size(), e.getMessage());
        }
    }
}
