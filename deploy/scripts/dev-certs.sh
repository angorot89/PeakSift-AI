#!/bin/sh
# A self-signed certificate for LOCAL testing of the production stack only.
# Production uses a real certificate (e.g. from your load balancer or Let's Encrypt).
set -eu
dir="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$dir"
host="${1:-localhost}"
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=$host" \
  -addext "subjectAltName=DNS:$host,IP:127.0.0.1" \
  -keyout "$dir/tls.key" -out "$dir/tls.crt" 2>/dev/null
chmod 600 "$dir/tls.key"
echo "wrote $dir/tls.crt and tls.key for $host (self-signed, 30 days)"
