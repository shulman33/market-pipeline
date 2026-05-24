package com.portfolio.matching.config;

import java.math.BigDecimal;
import java.util.Arrays;
import java.util.List;

public final class Config {

    private Config() {}

    public static int httpPort() {
        return parseInt("HTTP_PORT", 8080);
    }

    public static List<String> symbols() {
        String raw = envOrDefault("ME_SYMBOLS", "SYNTH1,SYNTH2");
        return Arrays.stream(raw.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
    }

    public static long seed() {
        return parseLong("ME_SEED", 42L);
    }

    public static BigDecimal basePrice() {
        return new BigDecimal(envOrDefault("ME_BASE_PRICE", "100.00"));
    }

    public static String databaseUrl() {
        return envOrDefault("DATABASE_URL", null);
    }

    private static String envOrDefault(String name, String fallback) {
        String v = System.getenv(name);
        return (v == null || v.isBlank()) ? fallback : v;
    }

    private static int parseInt(String name, int fallback) {
        String v = System.getenv(name);
        if (v == null || v.isBlank()) {
            return fallback;
        }
        return Integer.parseInt(v);
    }

    private static long parseLong(String name, long fallback) {
        String v = System.getenv(name);
        if (v == null || v.isBlank()) {
            return fallback;
        }
        return Long.parseLong(v);
    }
}
