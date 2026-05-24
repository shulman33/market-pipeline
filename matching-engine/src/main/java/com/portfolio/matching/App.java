package com.portfolio.matching;

import com.portfolio.matching.api.HttpServer;
import com.portfolio.matching.api.TradeLog;
import com.portfolio.matching.book.OrderBook;
import com.portfolio.matching.config.Config;
import com.portfolio.matching.engine.Engine;
import com.portfolio.matching.persistence.Db;
import com.portfolio.matching.persistence.OrderJournal;
import com.portfolio.matching.persistence.PostgresOrderJournal;
import com.portfolio.matching.persistence.PostgresTradeWriter;
import com.portfolio.matching.persistence.SnapshotWriter;
import com.portfolio.matching.persistence.TradeWriter;
import com.portfolio.matching.sim.SyntheticOrderGenerator;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import javax.sql.DataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class App {

    private static final Logger log = LoggerFactory.getLogger(App.class);

    public static void main(String[] args) {
        List<String> symbols = Config.symbols();
        int port = Config.httpPort();
        long seed = Config.seed();
        BigDecimal basePrice = Config.basePrice();
        String databaseUrl = Config.databaseUrl();

        ConcurrentMap<String, OrderBook> books = new ConcurrentHashMap<>();
        for (String s : symbols) {
            books.put(s, new OrderBook(s));
        }

        TradeLog tradeLog = new TradeLog();
        OrderJournal journal = OrderJournal.NOOP;
        TradeWriter tradeWriter = TradeWriter.NOOP;
        SnapshotWriter snapshotWriter = null;
        if (databaseUrl != null) {
            DataSource ds = Db.fromUrl(databaseUrl);
            journal = new PostgresOrderJournal(ds);
            tradeWriter = new PostgresTradeWriter(ds);
            snapshotWriter = new SnapshotWriter(ds, books.values());
            log.info("postgres persistence enabled");
        } else {
            log.info("no DATABASE_URL set; running without persistence");
        }

        Engine engine = new Engine(books, tradeLog, journal, tradeWriter);

        List<SyntheticOrderGenerator> generators = new ArrayList<>(symbols.size());
        for (String s : symbols) {
            generators.add(new SyntheticOrderGenerator(engine, s, basePrice, seed ^ s.hashCode()));
        }

        HttpServer server = new HttpServer(engine, port);
        final SnapshotWriter snapshotRef = snapshotWriter;
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            generators.forEach(SyntheticOrderGenerator::stop);
            if (snapshotRef != null) {
                snapshotRef.stop();
            }
            server.stop();
        }, "shutdown"));

        server.start();
        generators.forEach(SyntheticOrderGenerator::start);
        if (snapshotWriter != null) {
            snapshotWriter.start();
        }

        log.info("matching-engine started on :{} with symbols {}", port, symbols);
    }
}
