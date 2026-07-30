#!/usr/bin/env bash
#
# Despliega la herramienta ODRL en un clúster minikube local.
#
# Dos modos:
#   (por defecto) GHCR  -> usa las imágenes ya publicadas por GitHub Actions.
#   --local             -> construye las imágenes en tu Mac y las carga en minikube
#                          (no necesita GitHub ni internet para las imágenes).
#
# La clave de OpenAI NUNCA se escribe en disco ni en git: se lee del entorno.
#
# Uso:
#   export OPENAI_API_KEY='sk-...'
#   GH_USER='juliiosp' ./deploy.sh              # modo GHCR
#   OPENAI_API_KEY='sk-...' ./deploy.sh --local # modo build local (no necesita GH_USER)
#
# Variables opcionales:
#   POSTGRES_PASSWORD  contraseña de Postgres (por defecto: odrl)
#
set -euo pipefail

# --- Parámetros ------------------------------------------------------------
MODE="ghcr"
GH_USER="${GH_USER:-}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-odrl}"
NAMESPACE="odrl"
K8S_DIR="k8s"
LOCAL_PORT="8080"

die() { echo "❌ $*" >&2; exit 1; }
info() { echo "▶ $*"; }
ok() { echo "✅ $*"; }

usage() {
  cat <<EOF
Uso:
  export OPENAI_API_KEY='sk-...'
  GH_USER='tu_usuario' ./deploy.sh          # imágenes desde GHCR (recomendado)
  ./deploy.sh --local                       # construye las imágenes en local

Opciones:
  --local            Construye las imágenes y las carga en minikube (sin GHCR).
  --user <usuario>   Tu usuario de GitHub (equivale a GH_USER). Solo modo GHCR.
  -h, --help         Muestra esta ayuda.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) MODE="local"; shift ;;
    --user) GH_USER="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Opción desconocida: $1 (usa --help)" ;;
  esac
done

# --- Comprobaciones previas ------------------------------------------------
info "Comprobando herramientas..."
command -v docker >/dev/null   || die "Falta docker. Instala/abre Docker Desktop."
command -v kubectl >/dev/null  || die "Falta kubectl. Instálalo: brew install kubectl"
command -v minikube >/dev/null || die "Falta minikube. Instálalo: brew install minikube"
docker info >/dev/null 2>&1     || die "El daemon de Docker no responde. Abre Docker Desktop y espera a que arranque."

[[ -n "${OPENAI_API_KEY:-}" ]] || die "Exporta tu clave: export OPENAI_API_KEY='sk-...'"

if [[ "$MODE" == "ghcr" ]]; then
  [[ -n "$GH_USER" ]] || die "Indica tu usuario de GitHub: GH_USER='tu_usuario' ./deploy.sh  (o usa --local)"
  GH_USER="$(printf '%s' "$GH_USER" | tr '[:upper:]' '[:lower:]')"
fi
[[ -d "$K8S_DIR" ]] || die "No encuentro la carpeta '$K8S_DIR/'. Ejecuta el script desde la raíz del proyecto."

# --- Clúster ---------------------------------------------------------------
# Un clúster sano = kubectl llega al apiserver Y existe una StorageClass por
# defecto (sin ella, el disco de Postgres se queda en Pending).
cluster_healthy() {
  kubectl get nodes >/dev/null 2>&1 \
    && [[ -n "$(kubectl get storageclass -o name 2>/dev/null)" ]]
}

if minikube status >/dev/null 2>&1 && cluster_healthy; then
  ok "minikube ya está en marcha y sano."
else
  info "Arrancando minikube..."
  minikube start --driver=docker || true   # tolerante: si arranca roto, lo recreamos abajo
fi

# Si Docker reinició y recreó el contenedor sobre un perfil viejo, el clúster
# puede quedar a medias (apiserver caído, sin StorageClass). En ese caso, en
# vez de desplegar sobre un clúster roto, lo recreamos limpio una sola vez.
if ! cluster_healthy; then
  info "El clúster arrancó en mal estado; recreándolo limpio (minikube delete)..."
  minikube delete || true
  minikube start --driver=docker
  cluster_healthy || die "No consigo un clúster sano. Abre Docker Desktop del todo (icono estable) y reintenta."
fi
ok "Clúster sano: apiserver accesible y StorageClass por defecto presente."

info "Activando addons (ingress, metrics-server)..."
minikube addons enable ingress >/dev/null 2>&1 || true
minikube addons enable metrics-server >/dev/null 2>&1 || true

# --- Imágenes --------------------------------------------------------------
if [[ "$MODE" == "local" ]]; then
  API_IMG="odrl-translator-api:local"
  UI_IMG="odrl-translator-ui:local"
  info "Construyendo imágenes en local (esto también valida requirements.txt)..."
  docker build -t "$API_IMG" -f Dockerfile.api .
  docker build -t "$UI_IMG"  -f Dockerfile.ui  .
  info "Cargando imágenes en minikube..."
  minikube image load "$API_IMG"
  minikube image load "$UI_IMG"
else
  API_IMG="ghcr.io/$GH_USER/tfm-traductor-bidireccional-odrl-api:latest"
  UI_IMG="ghcr.io/$GH_USER/tfm-traductor-bidireccional-odrl-ui:latest" 
  info "Usando imágenes de GHCR: $API_IMG y $UI_IMG"
  info "  (recuerda que deben estar PÚBLICAS en la pestaña Packages)"
fi

# --- Preparar una copia temporal de Kustomize -------------------------------
# No se modifica ningún fichero versionado durante el despliegue.
info "Preparando las imágenes de despliegue..."
api_new_name="${API_IMG%:*}"; api_new_tag="${API_IMG##*:}"
ui_new_name="${UI_IMG%:*}";   ui_new_tag="${UI_IMG##*:}"

RENDER_DIR="$(mktemp -d)"
trap 'rm -rf "$RENDER_DIR"' EXIT
cp -R "$K8S_DIR"/. "$RENDER_DIR"/
kfile="$RENDER_DIR/kustomization.yaml"
awk '/^images:/{exit} {print}' "$kfile" > "$kfile.tmp"
cat >> "$kfile.tmp" <<EOF

images:
  - name: ghcr.io/OWNER/tfm-traductor-bidireccional-odrl-api
    newName: $api_new_name
    newTag: $api_new_tag
  - name: ghcr.io/OWNER/tfm-traductor-bidireccional-odrl-ui
    newName: $ui_new_name
    newTag: $ui_new_tag
EOF
mv "$kfile.tmp" "$kfile"

# --- Namespace y secretos (nunca en git) -----------------------------------
info "Creando namespace y secretos..."
kubectl apply -f "$K8S_DIR/00-namespace.yaml"

kubectl -n "$NAMESPACE" create secret generic odrl-api-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=DATABASE_URL="postgresql+psycopg2://odrl:${POSTGRES_PASSWORD}@odrl-postgres:5432/odrl" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "$NAMESPACE" create secret generic odrl-postgres-secret \
  --from-literal=POSTGRES_USER=odrl \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=POSTGRES_DB=odrl \
  --dry-run=client -o yaml | kubectl apply -f -

# --- Esperar al controlador de Ingress -------------------------------------
# minikube tarda en levantar el controlador nginx. Si se aplica el Ingress
# antes de que su webhook de admisión responda, kubectl falla con
# "connect: connection refused". Esperamos a que el controlador esté Ready.
info "Esperando a que el controlador de Ingress esté listo..."
for _ in $(seq 1 60); do
  kubectl -n ingress-nginx get deploy ingress-nginx-controller >/dev/null 2>&1 && break
  sleep 2
done
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s || true
kubectl -n ingress-nginx wait --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=180s || true

# --- Desplegar -------------------------------------------------------------
# El apply es idempotente: si el webhook del Ingress aún no responde en el
# primer intento, se reintenta (el resto de recursos saldrá como "unchanged").
apply_manifests() {
  if [[ "$MODE" == "local" ]]; then
    # Con imágenes locales hay que evitar que k8s intente descargarlas.
    kubectl kustomize "$RENDER_DIR" \
      | sed 's/imagePullPolicy: Always/imagePullPolicy: IfNotPresent/' \
      | kubectl apply -f -
  else
    kubectl apply -k "$RENDER_DIR"
  fi
}

info "Aplicando manifiestos..."
attempt=0
until apply_manifests; do
  attempt=$((attempt + 1))
  [[ $attempt -ge 10 ]] && die "No se pudieron aplicar los manifiestos tras varios intentos."
  info "El webhook del Ingress aún no responde; reintentando ($attempt/10)..."
  sleep 10
done

# --- Esperar a que esté listo ----------------------------------------------
info "Esperando a que los pods estén listos (puede tardar mientras descarga imágenes)..."
kubectl -n "$NAMESPACE" rollout status statefulset/odrl-postgres --timeout=300s || true
kubectl -n "$NAMESPACE" rollout status deployment/odrl-api --timeout=300s
kubectl -n "$NAMESPACE" rollout status deployment/odrl-ui --timeout=300s

ok "Despliegue completado."
echo
kubectl -n "$NAMESPACE" get pods
echo
ok "Abriendo la interfaz en http://localhost:$LOCAL_PORT  (Ctrl-C para cerrar el túnel)"
echo "   La API/Swagger: ejecuta en otra terminal ->  kubectl -n $NAMESPACE port-forward svc/odrl-api 8000:8000"
echo
exec kubectl -n "$NAMESPACE" port-forward "svc/odrl-ui" "${LOCAL_PORT}:7860"