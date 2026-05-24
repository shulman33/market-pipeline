package com.portfolio.matching.api;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.portfolio.matching.api.dto.SubmitOrderRequest;
import com.portfolio.matching.book.BookSnapshot;
import com.portfolio.matching.book.MatchResult;
import com.portfolio.matching.book.OrderType;
import com.portfolio.matching.book.TopOfBook;
import com.portfolio.matching.engine.Engine;
import io.javalin.Javalin;
import io.javalin.http.HttpStatus;
import io.javalin.json.JavalinJackson;
import java.util.Map;

public final class HttpServer {

    private final Engine engine;
    private final int port;
    private final Javalin app;

    public HttpServer(Engine engine, int port) {
        this.engine = engine;
        this.port = port;
        this.app = Javalin.create(config -> {
            ObjectMapper mapper = new ObjectMapper();
            mapper.configure(JsonGenerator.Feature.WRITE_BIGDECIMAL_AS_PLAIN, true);
            config.jsonMapper(new JavalinJackson(mapper, true));
            config.showJavalinBanner = false;
        });
        wireRoutes();
    }

    public void start() {
        app.start(port);
    }

    public void stop() {
        app.stop();
    }

    private void wireRoutes() {
        app.get("/health", ctx -> ctx.json(Map.of("status", "ok")));
        app.post("/orders", this::handleSubmit);
        app.delete("/orders/{id}", this::handleCancel);
        app.get("/book/{symbol}", this::handleSnapshot);
        app.get("/book/{symbol}/top", this::handleTop);
        app.get("/trades", this::handleTrades);
    }

    private void handleSubmit(io.javalin.http.Context ctx) {
        SubmitOrderRequest req = ctx.bodyAsClass(SubmitOrderRequest.class);
        if (req.symbol() == null || req.side() == null || req.type() == null || req.quantity() <= 0) {
            ctx.status(HttpStatus.BAD_REQUEST).json(error("symbol, side, type, and positive quantity required"));
            return;
        }
        if (!engine.symbols().contains(req.symbol())) {
            ctx.status(HttpStatus.NOT_FOUND).json(error("unknown symbol: " + req.symbol()));
            return;
        }

        MatchResult r;
        if (req.type() == OrderType.LIMIT) {
            if (req.price() == null) {
                ctx.status(HttpStatus.BAD_REQUEST).json(error("limit order requires price"));
                return;
            }
            r = engine.submitLimit(req.symbol(), req.side(), req.price(), req.quantity());
        } else {
            r = engine.submitMarket(req.symbol(), req.side(), req.quantity());
        }
        ctx.json(r);
    }

    private void handleCancel(io.javalin.http.Context ctx) {
        long id;
        try {
            id = Long.parseLong(ctx.pathParam("id"));
        } catch (NumberFormatException e) {
            ctx.status(HttpStatus.BAD_REQUEST).json(error("id must be a long"));
            return;
        }
        boolean ok = engine.cancel(id);
        if (ok) {
            ctx.json(Map.of("cancelled", true, "orderId", id));
        } else {
            ctx.status(HttpStatus.NOT_FOUND).json(Map.of("cancelled", false, "orderId", id));
        }
    }

    private void handleSnapshot(io.javalin.http.Context ctx) {
        String symbol = ctx.pathParam("symbol");
        BookSnapshot snap = engine.snapshot(symbol, parseIntQuery(ctx, "depth", 10));
        if (snap == null) {
            ctx.status(HttpStatus.NOT_FOUND).json(error("unknown symbol: " + symbol));
            return;
        }
        ctx.json(snap);
    }

    private void handleTop(io.javalin.http.Context ctx) {
        String symbol = ctx.pathParam("symbol");
        TopOfBook top = engine.topOfBook(symbol);
        if (top == null) {
            ctx.status(HttpStatus.NOT_FOUND).json(error("unknown symbol: " + symbol));
            return;
        }
        ctx.json(top);
    }

    private void handleTrades(io.javalin.http.Context ctx) {
        String symbol = ctx.queryParam("symbol");
        if (symbol == null || symbol.isBlank()) {
            ctx.status(HttpStatus.BAD_REQUEST).json(error("symbol query param required"));
            return;
        }
        ctx.json(engine.recentTrades(symbol, parseIntQuery(ctx, "limit", 100)));
    }

    private static int parseIntQuery(io.javalin.http.Context ctx, String name, int fallback) {
        String raw = ctx.queryParam(name);
        if (raw == null || raw.isBlank()) {
            return fallback;
        }
        try {
            return Integer.parseInt(raw);
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private static Map<String, String> error(String msg) {
        return Map.of("error", msg);
    }
}
