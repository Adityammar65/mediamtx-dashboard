FROM golang:alpine AS builder
WORKDIR /app
COPY main.go ./
RUN go mod init mediamtx-agent && go mod tidy && go build -o mediamtx-agent main.go

FROM scratch AS local
COPY --from=builder /app/mediamtx-agent /mediamtx-agent
