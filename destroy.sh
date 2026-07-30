#!/usr/bin/env bash
#
# Elimina el despliegue de la herramienta ODRL.
#
# Por defecto elimina el namespace 'odrl' completo, incluidos deployments,
# servicios, secretos, PostgreSQL y su volumen persistente.
# El clúster Minikube permanece activo.
#
# Uso:
#   ./destroy.sh                   # elimina el namespace odrl
#   ./destroy.sh --stop            # además, detiene Minikube
#   ./destroy.sh --delete-cluster  # elimina completamente el clúster
#   ./destroy.sh --yes             # omite la confirmación
#
set -euo pipefail

NAMESPACE="${NAMESPACE:-odrl}"
MINIKUBE_PROFILE="${MINIKUBE_PROFILE:-minikube}"

ACTION="none"
ASSUME_YES=false

info() {
  echo "▶ $*"
}

ok() {
  echo "✅ $*"
}

die() {
  echo "❌ $*" >&2
  exit 1
}

usage() {
  cat <<EOF
Uso:
  ./destroy.sh [opciones]

Opciones:
  --stop            Elimina el namespace y detiene Minikube.
  --delete-cluster  Elimina completamente el clúster Minikube.
  --yes             Omite la confirmación.
  -h, --help        Muestra esta ayuda.

Variables opcionales:
  NAMESPACE          Namespace que se eliminará. Por defecto: odrl
  MINIKUBE_PROFILE   Perfil de Minikube. Por defecto: minikube
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stop)
      [[ "$ACTION" == "none" ]] ||
        die "No puedes combinar --stop y --delete-cluster."
      ACTION="stop"
      shift
      ;;

    --delete-cluster)
      [[ "$ACTION" == "none" ]] ||
        die "No puedes combinar --stop y --delete-cluster."
      ACTION="delete"
      shift
      ;;

    --yes)
      ASSUME_YES=true
      shift
      ;;

    -h|--help)
      usage
      exit 0
      ;;

    *)
      die "Opción desconocida: $1. Usa --help."
      ;;
  esac
done

command -v kubectl >/dev/null ||
  die "Falta kubectl."

command -v minikube >/dev/null ||
  die "Falta Minikube."

# Evita ejecutar el borrado sobre otro clúster configurado en kubectl.
minikube -p "$MINIKUBE_PROFILE" status >/dev/null 2>&1 ||
  die "El perfil de Minikube '$MINIKUBE_PROFILE' no está disponible o no está iniciado."

minikube -p "$MINIKUBE_PROFILE" update-context >/dev/null
kubectl config use-context "$MINIKUBE_PROFILE" >/dev/null

if [[ "$ASSUME_YES" != "true" ]]; then
  echo
  echo "⚠️  Se eliminará el namespace '$NAMESPACE'."
  echo "   Esto borrará también PostgreSQL, sus secretos y su volumen persistente."

  if [[ "$ACTION" == "stop" ]]; then
    echo "   Después se detendrá Minikube."
  elif [[ "$ACTION" == "delete" ]]; then
    echo "   Después se eliminará completamente el clúster Minikube."
  fi

  echo
  read -r -p "¿Continuar? [y/N]: " confirmation

  case "$confirmation" in
    y|Y|yes|YES|s|S|si|SI|sí|SÍ)
      ;;
    *)
      info "Operación cancelada."
      exit 0
      ;;
  esac
fi

info "Eliminando el namespace '$NAMESPACE'..."

kubectl --context="$MINIKUBE_PROFILE" delete namespace "$NAMESPACE" \
  --ignore-not-found \
  --wait=true \
  --timeout=180s

ok "Namespace eliminado."

case "$ACTION" in
  stop)
    info "Deteniendo Minikube..."
    minikube -p "$MINIKUBE_PROFILE" stop
    ok "Minikube detenido. El clúster y sus recursos restantes se conservan."
    ;;

  delete)
    info "Eliminando completamente el clúster Minikube..."
    minikube -p "$MINIKUBE_PROFILE" delete
    ok "Clúster Minikube eliminado."
    ;;

  none)
    ok "El clúster Minikube continúa en funcionamiento."
    echo "   Puedes volver a desplegar con: ./deploy.sh"
    ;;
esac