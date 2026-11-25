FROM golang:alpine AS builder
WORKDIR /app
COPY main2.go ./
RUN go mod init mediamtx-agent && go mod tidy && go build -o mediamtx-agent main2.go

FROM scratch AS local
COPY --from=builder /app/mediamtx-agent /mediamtx-agent
