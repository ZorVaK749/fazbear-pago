FROM maven:3.9.16-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
COPY src ./src
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S pago && adduser -S pago -G pago
WORKDIR /app
COPY --from=build --chown=pago:pago /build/target/ms-pago-0.1.0-SNAPSHOT.jar app.jar
USER pago
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70", "-jar", "/app/app.jar"]
