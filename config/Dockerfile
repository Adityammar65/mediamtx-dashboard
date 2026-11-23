FROM golang:1.24-alpine AS builder
WORKDIR /app
COPY main.go .
RUN go build -o mediamtx-agent main.go

FROM alpine:3.21
RUN apk add --no-cache docker-cli
WORKDIR /app
COPY --from=builder /app/mediamtx-agent .
EXPOSE 8081
CMD ["./mediamtx-agent"]
