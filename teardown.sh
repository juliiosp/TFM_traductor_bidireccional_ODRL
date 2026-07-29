#!/usr/bin/env bash
#
# Elimina el despliegue de la herramienta ODRL.
#
# Por defecto borra el namespace 'odrl' entero (deployments, servicios,
# secretos, base de datos y su volumen). El clúster minikube sigue vivo.
#
# Uso:
#   ./teardown.sh                 # borra el namespace odrl
#   ./teardown.sh --stop          # además, para minikube (conserva el clúster)
#   ./teardown.sh --delete-cluster# además, borra el clúster minikube por completo
#
set -euo pipefail

NAMESPACE="odrl"
ACTION="none"

info() { echo "▶ $*"; }
ok() { echo "✅ $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stop) ACTION="stop"; shift ;;
    --delete-cluster) ACTION="delete"; shift ;;
    -h|--help)
      echo "Uso: ./teardown.sh [--stop | --delete-cluster]"; exit 0 ;;
    *) echo "Opción desconocida: $1"; exit 1 ;;
  esac
done

command -v kubectl >/dev/null || { echo "Falta kubectl"; exit 1; }

info "Borrando el namespace '$NAMESPACE' (esto elimina también la base de datos y su volumen)..."
kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=true
ok "Namespace eliminado."

case "$ACTION" in
  stop)
    info "Parando minikube..."
    minikube stop
    ok "minikube parado (el clúster se conserva; arráncalo de nuevo con 'minikube start')."
    ;;
  delete)
    info "Borrando el clúster minikube por completo..."
    minikube delete
    ok "Clúster eliminado."
    ;;
  none)
    ok "Listo. El clúster minikube sigue en marcha; vuelve a desplegar con ./deploy.sh"
    ;;
esac
