package com.portfolio.matching.persistence;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.net.URI;
import javax.sql.DataSource;

/**
 * Builds a Hikari connection pool from a libpq-style DATABASE_URL like
 * {@code postgresql://app:app@postgres:5432/market}. The rest of the repo uses
 * that URL shape for psycopg, so accepting the same shape here keeps the
 * single env var working across the Python and Java services.
 */
public final class Db {

    private Db() {}

    public static DataSource fromUrl(String databaseUrl) {
        if (databaseUrl == null || databaseUrl.isBlank()) {
            throw new IllegalArgumentException("DATABASE_URL is required");
        }
        URI uri = URI.create(databaseUrl);
        String userInfo = uri.getUserInfo();
        if (userInfo == null) {
            throw new IllegalArgumentException("DATABASE_URL must include user:password");
        }
        String[] parts = userInfo.split(":", 2);
        String user = parts[0];
        String password = parts.length > 1 ? parts[1] : "";
        int port = uri.getPort() > 0 ? uri.getPort() : 5432;
        String jdbcUrl = String.format("jdbc:postgresql://%s:%d%s", uri.getHost(), port, uri.getPath());

        HikariConfig cfg = new HikariConfig();
        cfg.setJdbcUrl(jdbcUrl);
        cfg.setUsername(user);
        cfg.setPassword(password);
        cfg.setMaximumPoolSize(8);
        cfg.setPoolName("matching-engine-pool");
        // Switch the pgjdbc driver to named (server-side) prepared statements
        // after the first execute so subsequent writes skip parse + plan.
        cfg.addDataSourceProperty("prepareThreshold", "1");
        return new HikariDataSource(cfg);
    }
}
