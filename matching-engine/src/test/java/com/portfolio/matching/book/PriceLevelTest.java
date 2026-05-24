package com.portfolio.matching.book;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class PriceLevelTest {

    @Test
    void appendBuildsFifoAndTracksTotal() {
        PriceLevel level = new PriceLevel(new BigDecimal("100.00"));
        Order a = new Order(1, Side.BUY, level.price, 5, 0);
        Order b = new Order(2, Side.BUY, level.price, 3, 0);

        level.append(a);
        level.append(b);

        assertThat(level.head).isSameAs(a);
        assertThat(level.tail).isSameAs(b);
        assertThat(a.next).isSameAs(b);
        assertThat(b.prev).isSameAs(a);
        assertThat(level.totalQuantity).isEqualTo(8);
    }

    @Test
    void unlinkHeadAdvancesHead() {
        PriceLevel level = new PriceLevel(new BigDecimal("100.00"));
        Order a = new Order(1, Side.BUY, level.price, 5, 0);
        Order b = new Order(2, Side.BUY, level.price, 3, 0);
        level.append(a);
        level.append(b);

        level.unlink(a);

        assertThat(level.head).isSameAs(b);
        assertThat(b.prev).isNull();
        assertThat(level.totalQuantity).isEqualTo(3);
    }

    @Test
    void unlinkTailRetreatsTail() {
        PriceLevel level = new PriceLevel(new BigDecimal("100.00"));
        Order a = new Order(1, Side.BUY, level.price, 5, 0);
        Order b = new Order(2, Side.BUY, level.price, 3, 0);
        level.append(a);
        level.append(b);

        level.unlink(b);

        assertThat(level.tail).isSameAs(a);
        assertThat(a.next).isNull();
        assertThat(level.totalQuantity).isEqualTo(5);
    }

    @Test
    void unlinkMiddleStitchesNeighbours() {
        PriceLevel level = new PriceLevel(new BigDecimal("100.00"));
        Order a = new Order(1, Side.BUY, level.price, 1, 0);
        Order b = new Order(2, Side.BUY, level.price, 1, 0);
        Order c = new Order(3, Side.BUY, level.price, 1, 0);
        level.append(a);
        level.append(b);
        level.append(c);

        level.unlink(b);

        assertThat(a.next).isSameAs(c);
        assertThat(c.prev).isSameAs(a);
        assertThat(level.totalQuantity).isEqualTo(2);
    }

    @Test
    void unlinkOnlyMemberLeavesEmpty() {
        PriceLevel level = new PriceLevel(new BigDecimal("100.00"));
        Order a = new Order(1, Side.BUY, level.price, 5, 0);
        level.append(a);

        level.unlink(a);

        assertThat(level.isEmpty()).isTrue();
        assertThat(level.head).isNull();
        assertThat(level.tail).isNull();
        assertThat(level.totalQuantity).isZero();
    }
}
