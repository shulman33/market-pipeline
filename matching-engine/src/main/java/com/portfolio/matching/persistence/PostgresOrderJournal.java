package com.portfolio.matching.persistence;

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
    public void record(OrderEvent e) {
        try (Connection c = ds.getConnection();
                PreparedStatement ps = c.prepareStatement(SQL)) {
            ps.setLong(1, e.orderId());
            ps.setString(2, e.symbol());
            ps.setString(3, e.side().name());
            ps.setString(4, e.type().name());
            if (e.price() != null) {
                ps.setBigDecimal(5, e.price());
            } else {
                ps.setNull(5, Types.NUMERIC);
            }
            ps.setLong(6, e.quantity());
            ps.setTimestamp(7, new Timestamp(e.timestampMillis()));
            ps.setLong(8, e.remainingQuantity());
            ps.setBoolean(9, e.resting());
            ps.executeUpdate();
        } catch (SQLException ex) {
            log.warn("order journal insert failed for {}: {}", e.orderId(), ex.getMessage());
        }
    }
}
