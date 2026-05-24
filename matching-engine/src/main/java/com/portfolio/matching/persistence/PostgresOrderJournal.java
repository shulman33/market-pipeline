package com.portfolio.matching.persistence;

import com.portfolio.matching.book.OrderType;
import com.portfolio.matching.book.Side;
import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import javax.sql.DataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class PostgresOrderJournal implements OrderJournal {

    private static final Logger log = LoggerFactory.getLogger(PostgresOrderJournal.class);
    private static final String SQL =
            "INSERT INTO me_orders (id, symbol, side, order_type, price, quantity, ts, remaining, resting) "
                    + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)";

    private final DataSource ds;

    public PostgresOrderJournal(DataSource ds) {
        this.ds = ds;
    }

    @Override
    public void record(
            long orderId,
            String symbol,
            Side side,
            OrderType type,
            BigDecimal price,
            long quantity,
            long timestampMillis,
            long remainingQuantity,
            boolean resting) {
        try (Connection c = ds.getConnection();
                PreparedStatement ps = c.prepareStatement(SQL)) {
            ps.setLong(1, orderId);
            ps.setString(2, symbol);
            ps.setString(3, side.name());
            ps.setString(4, type.name());
            if (price != null) {
                ps.setBigDecimal(5, price);
            } else {
                ps.setNull(5, Types.NUMERIC);
            }
            ps.setLong(6, quantity);
            ps.setTimestamp(7, new Timestamp(timestampMillis));
            ps.setLong(8, remainingQuantity);
            ps.setBoolean(9, resting);
            ps.executeUpdate();
        } catch (SQLException e) {
            log.warn("order journal insert failed for {}: {}", orderId, e.getMessage());
        }
    }
}
