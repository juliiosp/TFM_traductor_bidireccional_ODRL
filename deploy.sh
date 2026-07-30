#!/usr/bin/env bash
#
# Despliega la herramienta ODRL en un clúster Minikube local.
#
# Modos:
#   GHCR, por defecto:
#     Utiliza imágenes publicadas por GitHub Actions en GHCR.
#
#   --local:
#     Construye las imágenes en el equipo y las carga en Minikube.
#
# La clave de OpenAI nunca se escribe en disco ni se almacena en Git.
# Se obtiene exclusivamente de la variable de entorno OPENAI_API_KEY.
#
# Uso:
#   export OPENAI_API_KEY='sk-...'
#
#   GH_USER='juliiosp' ./deploy.sh
#   ./deploy.sh --user juliiosp
#   ./deploy.sh --user juliiosp --tag sha-abc1234
#   ./deploy.sh --local
#
# Variables opcionales:
#   POSTGRES_PASSWORD  Contraseña de PostgreSQL. Por defecto: odrl
#   IMAGE_TAG          Etiqueta de las imágenes de GHCR. Por defecto: latest
#
set -euo pipefail

# --- Parámetros ------------------------------------------------------------

MODE="ghcr"
GH_USER="${GH_USER:-}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-odrl}"

NAMESPACE="odrl"
K8S_DIR="k8s"
LOCAL_PORT="8080"

die() {
  echo "❌ $*" >&2
  exit 1
}

info() {
  echo "▶ $*"
}

ok() {
  echo "✅ $*"
}

usage() {
  cat <<'EOF'
Uso:
  export OPENAI_API_KEY='sk-...'

  GH_USER='tu_usuario' ./deploy.sh
  ./deploy.sh --user tu_usuario
  ./deploy.sh --user tu_usuario --tag sha-abc1234
  ./deploy.sh --local

Modos:
  Por defecto         Despliega las imágenes publicadas en GHCR.
  --local             Construye las imágenes localmente y las carga en Minikube.

Opciones:
  --local             Utiliza imágenes construidas localmente.
  --user <usuario>    Usuario de GitHub. Equivale a GH_USER.
  --tag <etiqueta>    Etiqueta de las imágenes de GHCR.
  -h, --help          Muestra esta ayuda.

Variables opcionales:
  IMAGE_TAG           Etiqueta de GHCR. Por defecto: latest.
  POSTGRES_PASSWORD   Contraseña de PostgreSQL. Por defecto: odrl.
EOF
}

# --- Funciones auxiliares --------------------------------------------------

cluster_healthy() {
  kubectl --context=minikube get nodes >/dev/null 2>&1 || return 1

  # Comprueba que exista una StorageClass marcada como predeterminada.
  kubectl --context=minikube get storageclass \
    -o jsonpath='{range .items[*]}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{" "}{.metadata.annotations.storageclass\.beta\.kubernetes\.io/is-default-class}{"\n"}{end}' \
    2>/dev/null |
    grep -Eq '(^|[[:space:]])true($|[[:space:]])'
}

wait_for_apiserver() {
  local attempt

  info "Esperando a que el API server de Kubernetes esté preparado..."

  for attempt in $(seq 1 60); do
    if kubectl --context=minikube get --raw='/readyz' >/dev/null 2>&1; then
      ok "API server preparado."
      return 0
    fi

    sleep 2
  done

  die "El API server de Minikube no está preparado."
}

enable_addon() {
  local addon="$1"
  local attempt

  for attempt in 1 2 3; do
    if minikube addons enable "$addon"; then
      ok "Addon '$addon' activado."
      return 0
    fi

    info "No se pudo activar '$addon'. Reintentando en 5 segundos ($attempt/3)..."
    sleep 5
  done

  die "No se pudo activar el addon '$addon'."
}

wait_for_deployment() {
  local namespace="$1"
  local deployment="$2"
  local timeout="${3:-300}"
  local attempt

  info "Esperando al deployment '$deployment'..."

  for attempt in $(seq 1 60); do
    if kubectl -n "$namespace" get deployment "$deployment" >/dev/null 2>&1; then
      kubectl -n "$namespace" rollout status \
        "deployment/$deployment" \
        --timeout="${timeout}s"
      return 0
    fi

    sleep 2
  done

  die "No apareció el deployment '$deployment' en el namespace '$namespace'."
}

# --- Argumentos ------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)
      MODE="local"
      shift
      ;;

    --user)
      [[ $# -ge 2 ]] || die "Falta el valor de --user."
      GH_USER="$2"
      shift 2
      ;;

    --tag)
      [[ $# -ge 2 ]] || die "Falta el valor de --tag."
      IMAGE_TAG="$2"
      shift 2
      ;;

    -h | --help)
      usage
      exit 0
      ;;

    *)
      die "Opción desconocida: $1. Usa --help para consultar las opciones."
      ;;
  esac
done

# --- Comprobaciones previas ------------------------------------------------

info "Comprobando herramientas..."

command -v docker >/dev/null ||
  die "Falta Docker. Instala o abre Docker Desktop."

command -v kubectl >/dev/null ||
  die "Falta kubectl. Puedes instalarlo con: brew install kubectl"

command -v minikube >/dev/null ||
  die "Falta Minikube. Puedes instalarlo con: brew install minikube"

docker info >/dev/null 2>&1 ||
  die "El daemon de Docker no responde. Abre Docker Desktop y espera a que arranque."

[[ -n "${OPENAI_API_KEY:-}" ]] ||
  die "Exporta tu clave antes de desplegar: export OPENAI_API_KEY='sk-...'"

[[ -d "$K8S_DIR" ]] ||
  die "No encuentro la carpeta '$K8S_DIR/'. Ejecuta el script desde la raíz del proyecto."

[[ -f "Dockerfile.api" ]] ||
  die "No encuentro Dockerfile.api."

[[ -f "Dockerfile.ui" ]] ||
  die "No encuentro Dockerfile.ui."

[[ -f "$K8S_DIR/kustomization.yaml" ]] ||
  die "No encuentro $K8S_DIR/kustomization.yaml."

if [[ "$MODE" == "ghcr" ]]; then
  [[ -n "$GH_USER" ]] ||
    die "Indica el usuario de GitHub: GH_USER='tu_usuario' ./deploy.sh"

  GH_USER="$(printf '%s' "$GH_USER" | tr '[:upper:]' '[:lower:]')"

  [[ -n "$IMAGE_TAG" ]] ||
    die "La etiqueta de imagen no puede estar vacía."
fi

# --- Clúster Minikube ------------------------------------------------------

info "Iniciando o comprobando el clúster Minikube..."

minikube start \
  --driver=docker \
  --wait=all \
  --wait-timeout=6m

info "Seleccionando el contexto de Minikube..."

minikube update-context >/dev/null
kubectl config use-context minikube >/dev/null

wait_for_apiserver

cluster_healthy ||
  die "Minikube no está sano o no dispone de una StorageClass predeterminada.

Prueba a ejecutar:
  minikube stop
  minikube start --driver=docker --wait=all --wait-timeout=6m

Para recrear deliberadamente el clúster:
  minikube delete
  minikube start --driver=docker --wait=all --wait-timeout=6m"

ok "Clúster sano: API server accesible y almacenamiento disponible."

# --- Addons ----------------------------------------------------------------

info "Activando addons de Minikube..."

enable_addon ingress
enable_addon metrics-server

wait_for_deployment "ingress-nginx" "ingress-nginx-controller" 300
wait_for_deployment "kube-system" "metrics-server" 300

# --- Imágenes --------------------------------------------------------------

if [[ "$MODE" == "local" ]]; then
  API_IMG="odrl-translator-api:local"
  UI_IMG="odrl-translator-ui:local"

  info "Construyendo la imagen de la API..."
  docker build \
    -t "$API_IMG" \
    -f Dockerfile.api \
    .

  info "Construyendo la imagen de la interfaz..."
  docker build \
    -t "$UI_IMG" \
    -f Dockerfile.ui \
    .

  info "Eliminando posibles versiones anteriores de las imágenes en Minikube..."

  minikube image rm "$API_IMG" >/dev/null 2>&1 || true
  minikube image rm "$UI_IMG" >/dev/null 2>&1 || true

  info "Cargando las imágenes nuevas en Minikube..."

  minikube image load "$API_IMG"
  minikube image load "$UI_IMG"

  ok "Imágenes locales cargadas."
else
  API_IMG="ghcr.io/$GH_USER/tfm-traductor-bidireccional-odrl-api:$IMAGE_TAG"
  UI_IMG="ghcr.io/$GH_USER/tfm-traductor-bidireccional-odrl-ui:$IMAGE_TAG"

  info "Utilizando imágenes publicadas en GHCR:"
  echo "   API: $API_IMG"
  echo "   UI:  $UI_IMG"
  echo
  info "Las imágenes deben ser públicas o el clúster debe disponer de imagePullSecrets."
fi

# --- Renderizado temporal de Kustomize -------------------------------------

info "Preparando los manifiestos de despliegue..."

api_new_name="${API_IMG%:*}"
api_new_tag="${API_IMG##*:}"

ui_new_name="${UI_IMG%:*}"
ui_new_tag="${UI_IMG##*:}"

RENDER_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$RENDER_DIR"
}

trap cleanup EXIT

cp -R "$K8S_DIR"/. "$RENDER_DIR"/

kfile="$RENDER_DIR/kustomization.yaml"

# Se reemplaza la sección images del kustomization temporal.
# No se modifica ningún archivo versionado.
awk '
  /^images:/ {
    exit
  }
  {
    print
  }
' "$kfile" >"$kfile.tmp"

cat >>"$kfile.tmp" <<EOF

images:
  - name: ghcr.io/OWNER/tfm-traductor-bidireccional-odrl-api
    newName: $api_new_name
    newTag: $api_new_tag
  - name: ghcr.io/OWNER/tfm-traductor-bidireccional-odrl-ui
    newName: $ui_new_name
    newTag: $ui_new_tag
EOF

mv "$kfile.tmp" "$kfile"

# --- Namespace y secretos --------------------------------------------------

info "Creando el namespace..."

kubectl apply -f "$K8S_DIR/00-namespace.yaml"

info "Creando o actualizando los secretos..."

kubectl -n "$NAMESPACE" create secret generic odrl-api-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=DATABASE_URL="postgresql+psycopg2://odrl:${POSTGRES_PASSWORD}@odrl-postgres:5432/odrl" \
  --dry-run=client \
  -o yaml |
  kubectl apply -f -

kubectl -n "$NAMESPACE" create secret generic odrl-postgres-secret \
  --from-literal=POSTGRES_USER="odrl" \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=POSTGRES_DB="odrl" \
  --dry-run=client \
  -o yaml |
  kubectl apply -f -

# --- Aplicación de manifiestos ---------------------------------------------

apply_manifests() {
  if [[ "$MODE" == "local" ]]; then
    # Las imágenes ya están cargadas dentro de Minikube.
    # Kubernetes no debe intentar descargarlas de un registro.
    kubectl kustomize "$RENDER_DIR" |
      sed 's/imagePullPolicy: Always/imagePullPolicy: IfNotPresent/' |
      kubectl apply -f -
  else
    kubectl apply -k "$RENDER_DIR"
  fi
}

info "Aplicando manifiestos..."

attempt=1

until apply_manifests; do
  if [[ "$attempt" -ge 10 ]]; then
    die "No se pudieron aplicar los manifiestos tras 10 intentos."
  fi

  info "La aplicación de manifiestos ha fallado. Reintentando ($attempt/10)..."

  attempt=$((attempt + 1))
  sleep 10
done

# Las etiquetas local y latest pueden mantenerse entre ejecuciones.
# El reinicio garantiza que los pods carguen las imágenes y secretos actuales.
info "Reiniciando API y UI para cargar las imágenes y secretos actuales..."

kubectl -n "$NAMESPACE" rollout restart deployment/odrl-api
kubectl -n "$NAMESPACE" rollout restart deployment/odrl-ui

# --- Comprobación del despliegue -------------------------------------------

info "Esperando a que PostgreSQL esté listo..."

kubectl -n "$NAMESPACE" rollout status \
  statefulset/odrl-postgres \
  --timeout=300s

info "Esperando a que la API esté lista..."

kubectl -n "$NAMESPACE" rollout status \
  deployment/odrl-api \
  --timeout=300s

info "Esperando a que la interfaz esté lista..."

kubectl -n "$NAMESPACE" rollout status \
  deployment/odrl-ui \
  --timeout=300s

ok "Despliegue completado."

echo
kubectl -n "$NAMESPACE" get pods
echo
kubectl -n "$NAMESPACE" get services
echo

ok "Abriendo la interfaz en http://localhost:$LOCAL_PORT"
echo "   Pulsa Ctrl-C para cerrar el port-forward."
echo
echo "   Para acceder a la API y Swagger, ejecuta en otra terminal:"
echo "   kubectl -n $NAMESPACE port-forward svc/odrl-api 8000:8000"
echo

exec kubectl -n "$NAMESPACE" port-forward \
  svc/odrl-ui \
  "${LOCAL_PORT}:7860"