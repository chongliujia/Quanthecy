FROM rust:1.91.1-slim-bookworm AS builder
WORKDIR /build
COPY services/market-data services/market-data
COPY contracts contracts
COPY tests/fixtures tests/fixtures
RUN cargo build --locked --release --manifest-path services/market-data/Cargo.toml

FROM builder AS checks
RUN rustup component add rustfmt clippy \
    && cargo fmt --manifest-path services/market-data/Cargo.toml --check \
    && cargo clippy --locked --manifest-path services/market-data/Cargo.toml --all-targets --all-features -- -D warnings \
    && cargo test --locked --manifest-path services/market-data/Cargo.toml

FROM debian:bookworm-slim AS production
RUN mkdir -p /var/lib/quanthecy && chown 10001:10001 /var/lib/quanthecy
COPY --from=builder /build/services/market-data/target/release/quanthecy-market-data /usr/local/bin/quanthecy-market-data
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["quanthecy-market-data"]
