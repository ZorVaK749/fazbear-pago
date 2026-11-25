#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 3 || $(id -u) != 0 ]]; then
  echo "Uso: sudo bash $0 IPv4_PUBLICA_EC2 IPv4_PRIVADA_EC2 IPv4_PUBLICA_DEL_NAVEGADOR" >&2
  exit 2
fi

python3 - "$@" <<'PY'
import ipaddress
import sys

public, private, client = map(ipaddress.IPv4Address, sys.argv[1:])
if not (public.is_global and client.is_global and private.is_private and not private.is_loopback):
    sys.exit("Usa las IPv4 pública y privada de la EC2 y una IPv4 pública de cliente.")
PY

proxy_dir=$(cd -- "$(dirname -- "$0")" && pwd)
proxy_name=pedidos360-ev3-kafka-ui-proxy
proxy_label=cl.pedidos360.service=kafka-ui-proxy
image=caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0

curl --noproxy '*' --max-time 10 -fsS -H 'Accept: application/json' http://127.0.0.1:18090/topic >/dev/null
existing=$(docker container ls --all --quiet --filter "name=^/${proxy_name}$")
if [[ -n "$existing" ]] && [[ $(docker inspect --format '{{index .Config.Labels "cl.pedidos360.service"}}' "$existing") != kafka-ui-proxy ]]; then
  echo "El nombre del proxy está ocupado por otro contenedor." >&2
  exit 1
fi

read -rsp 'Contraseña de demo para el usuario demo: ' password
printf '\n'
if [[ -z "$password" ]]; then
  echo "La contraseña de demo es obligatoria." >&2
  exit 1
fi
password_hash=$(printf '%s\n' "$password" | docker run --rm -i "$image" caddy hash-password --bcrypt-cost 10)
unset password
if [[ ! "$password_hash" =~ ^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$ ]]; then
  echo "Caddy devolvió un hash inesperado." >&2
  exit 1
fi

umask 077
credentials=$(mktemp "$proxy_dir/.kafka-ui.credentials.XXXXXX")
trap 'rm -f -- "$credentials"' EXIT
printf 'demo %s\n' "$password_hash" > "$credentials"
unset password_hash
mv -f -- "$credentials" "$proxy_dir/kafka-ui.credentials"

if [[ -n "$existing" ]]; then
  docker rm -f "$existing" >/dev/null
fi
docker run --detach --name "$proxy_name" --label "$proxy_label" --network host \
  --restart unless-stopped --memory 96m --cpus 0.25 \
  --cap-drop ALL --cap-add NET_BIND_SERVICE --security-opt no-new-privileges \
  --log-opt max-size=5m --log-opt max-file=2 \
  --env "KAFKA_UI_PUBLIC_IPV4=$1" --env "KAFKA_UI_PRIVATE_IPV4=$2" --env "KAFKA_UI_CLIENT_IPV4=$3" \
  --mount "type=bind,source=$proxy_dir/Caddyfile.kafka-ui,destination=/etc/caddy/Caddyfile,readonly" \
  --mount "type=bind,source=$proxy_dir/kafka-ui.credentials,destination=/etc/caddy/kafka-ui.credentials,readonly" \
  --mount type=volume,source=pedidos360-ev3-kafka-ui-certificates,destination=/data \
  "$image"
printf 'Proxy iniciado. Revisa la emisión del certificado con docker logs --tail 40 %s\n' "$proxy_name"
printf 'Entrada de demo: http://%s:80/\n' "$1"
