FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /build

# Resolve dependencies first so subsequent code-only changes hit the cache.
COPY matching-engine/pom.xml ./pom.xml
RUN mvn -B -q dependency:go-offline

COPY matching-engine/src ./src
RUN mvn -B -q -DskipTests package


FROM amazoncorretto:17-alpine

WORKDIR /app
COPY --from=builder /build/target/matching-engine-0.1.0-shaded.jar /app/app.jar

EXPOSE 8080
CMD ["java", "-jar", "/app/app.jar"]
