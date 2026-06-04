FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /corpus-tap ./cmd/corpus-tap

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /corpus-tap /usr/local/bin/corpus-tap
COPY migrations /app/migrations
EXPOSE 8443
ENTRYPOINT ["corpus-tap"]
