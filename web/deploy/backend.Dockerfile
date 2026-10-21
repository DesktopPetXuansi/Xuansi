FROM golang:1.26.10-alpine AS build
WORKDIR /src
COPY backend/go.mod backend/go.sum ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 go build -trimpath -o /out/api ./cmd/api && \
    CGO_ENABLED=0 go build -trimpath -o /out/worker ./cmd/worker && \
    CGO_ENABLED=0 go build -trimpath -o /out/admin ./cmd/admin

FROM alpine:3.23
RUN apk add --no-cache ca-certificates tzdata && addgroup -S xuansi && adduser -S -G xuansi xuansi
WORKDIR /app
COPY --from=build /out/ ./
COPY backend/migrations ./migrations
RUN mkdir -p /app/data && chown -R xuansi:xuansi /app
USER xuansi
EXPOSE 8080
ENTRYPOINT ["/app/api"]
CMD ["-migrate"]
