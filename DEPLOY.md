# Despliegue de ODRL Translator

Esta guía explica cómo ejecutar **ODRL Translator** mediante Docker Compose, Kubernetes local con Minikube y un clúster Kubernetes externo utilizando las imágenes publicadas por GitHub Actions.

Para la descripción funcional, arquitectura y uso de la aplicación, consulta `[README.md](README.md)`.

## Modalidades disponibles


| Modalidad                 | Entorno        | Origen de las imágenes           | Comando principal                       |
| ------------------------- | -------------- | -------------------------------- | --------------------------------------- |
| Docker Compose            | Máquina local  | Construidas desde el repositorio | `docker compose up --build`             |
| Kubernetes local          | Minikube       | Construidas localmente           | `./deploy.sh --local`                   |
| Kubernetes local con GHCR | Minikube       | Publicadas por GitHub Actions    | `GH_USER='juliiosp' ./deploy.sh`        |
| Kubernetes externo        | Clúster remoto | Publicadas por GitHub Actions    | Aplicación de manifiestos con `kubectl` |


## Configuración común

La API necesita una clave válida de OpenAI. No la escribas en el repositorio ni en los manifiestos versionados.

Variables principales:


| Variable                 | Obligatoria  | Valor predeterminado | Uso                                     |
| ------------------------ | ------------ | -------------------- | --------------------------------------- |
| `OPENAI_API_KEY`         | Sí           | —                    | Acceso al modelo de lenguaje            |
| `OPENAI_MODEL`           | No           | `gpt-4.1-mini`       | Modelo utilizado                        |
| `OPENAI_TIMEOUT`         | No           | `30`                 | Timeout por llamada al modelo           |
| `MAX_REPAIR_ATTEMPTS`    | No           | `3`                  | Intentos de reparación automática       |
| `POSTGRES_PASSWORD`      | Recomendable | `odrl`               | Contraseña de PostgreSQL                |
| `API_REQUEST_TIMEOUT`    | No           | `300`                | Timeout de peticiones desde la interfaz |
| `API_EVALUATION_TIMEOUT` | No           | `3600`               | Timeout de evaluaciones completas       |


---

# 1. Ejecución local con Docker Compose

## Requisitos

- Docker Desktop o Docker Engine con Docker Compose.
- Puertos `7860` y `8000` disponibles.
- Una clave válida de OpenAI.

## Preparar el entorno

Desde la raíz del repositorio:

```bash
cp .env.example .env
```

Edita `.env` y configura al menos:

```dotenv
OPENAI_API_KEY=tu_clave
POSTGRES_PASSWORD=una_contraseña_segura
```

El archivo `.env` está excluido de Git y no debe compartirse.

## Iniciar la aplicación

En primer plano:

```bash
docker compose up --build
```

En segundo plano:

```bash
docker compose up --build -d
```

Comprueba el estado:

```bash
docker compose ps
```

## Acceso


| Recurso         | Dirección                      |
| --------------- | ------------------------------ |
| Interfaz Gradio | `http://localhost:7860`        |
| API FastAPI     | `http://localhost:8000`        |
| Swagger UI      | `http://localhost:8000/docs`   |
| Liveness        | `http://localhost:8000/health` |
| Readiness       | `http://localhost:8000/ready`  |


Comprobación rápida:

```bash
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/ready
```

## Registros y actualización

```bash
docker compose logs -f
docker compose up --build -d
```

Para consultar un servicio concreto:

```bash
docker compose logs -f api
docker compose logs -f ui
docker compose logs -f db
```

## Detener o eliminar

Conservar la base de datos:

```bash
docker compose down
```

Eliminar también el volumen de PostgreSQL:

```bash
docker compose down -v
```

> [!WARNING]
> `docker compose down -v` elimina permanentemente el historial almacenado en PostgreSQL.

---

# 2. Kubernetes local con Minikube

El script `[deploy.sh](deploy.sh)` admite dos modos:

- `--local`: construye las imágenes en el equipo y las carga en Minikube.
- modo predeterminado: descarga desde GHCR las imágenes publicadas por GitHub Actions.

## Requisitos

- Docker en funcionamiento.
- `kubectl`.
- `minikube`.
- Una clave válida de OpenAI.

En macOS:

```bash
brew install kubectl minikube
chmod +x deploy.sh teardown.sh
```

Exporta los secretos en la terminal:

```bash
export OPENAI_API_KEY='tu_clave'
export POSTGRES_PASSWORD='una_contraseña_segura'
```

## 2.1 Imágenes construidas localmente

Este modo es el recomendado para probar cambios todavía no publicados:

```bash
./deploy.sh --local
```

El script:

1. inicia Minikube cuando es necesario;
2. construye `odrl-translator-api:local` y `odrl-translator-ui:local`;
3. carga las imágenes en Minikube;
4. crea el namespace y los secretos;
5. aplica los manifiestos de `k8s/`;
6. espera a PostgreSQL, FastAPI y Gradio;
7. abre la interfaz en `http://localhost:8080`.

## 2.2 Imágenes publicadas por GitHub Actions

Las imágenes publicadas son:

```text
ghcr.io/juliiosp/tfm-traductor-bidireccional-odrl-api:latest
ghcr.io/juliiosp/tfm-traductor-bidireccional-odrl-ui:latest
```

Para desplegarlas en Minikube:

```bash
GH_USER='juliiosp' ./deploy.sh
```

También puede utilizarse:

```bash
./deploy.sh --user juliiosp
```

Los paquetes de GHCR deben ser públicos. Si son privados, el clúster necesita un `imagePullSecret`.

## Acceso

El script mantiene un `port-forward` abierto:

```text
http://localhost:8080
```

`Ctrl+C` cierra el túnel, pero no elimina el despliegue. Para abrirlo otra vez:

```bash
kubectl -n odrl port-forward service/odrl-ui 8080:7860
```

Para acceder a Swagger desde otra terminal:

```bash
kubectl -n odrl port-forward service/odrl-api 8000:8000
```

Después abre `http://localhost:8000/docs`.

## Verificación

```bash
kubectl -n odrl get pods,services,ingress,hpa,pvc
```

El estado esperado es:

- PostgreSQL: `1/1 Running`.
- API: réplicas disponibles y `Running`.
- UI: `1/1 Running`.

Consulta de imágenes utilizadas:

```bash
kubectl -n odrl get deployments \
  -o custom-columns='DEPLOYMENT:.metadata.name,IMAGE:.spec.template.spec.containers[*].image'
```

Registros:

```bash
kubectl logs -n odrl deployment/odrl-api --all-pods=true --tail=200
kubectl logs -n odrl deployment/odrl-ui --tail=200
kubectl logs -n odrl statefulset/odrl-postgres --tail=200
```

## Retirar el despliegue

Eliminar el namespace `odrl`, incluidos la base de datos y su volumen, manteniendo Minikube:

```bash
./teardown.sh
```

Eliminar el despliegue y detener Minikube:

```bash
./teardown.sh --stop
```

Eliminar completamente el clúster:

```bash
./teardown.sh --delete-cluster
```

---

# 3. Kubernetes externo con imágenes de GitHub Actions

`deploy.sh` está diseñado para Minikube. Para un clúster Kubernetes externo se utilizan los mismos manifiestos y las imágenes publicadas en GHCR, pero la aplicación se realiza con `kubectl`.

## Requisitos

- Acceso configurado al clúster mediante `kubectl`.
- Una `StorageClass` predeterminada para el PVC de PostgreSQL.
- Un controlador Ingress compatible con `ingressClassName: nginx`, o la adaptación de `k8s/70-ingress.yaml`.
- Imágenes GHCR públicas o credenciales para descargarlas.

Comprueba el contexto antes de aplicar recursos:

```bash
kubectl config current-context
kubectl get nodes
kubectl get storageclass
```

## Crear los secretos

```bash
export OPENAI_API_KEY='tu_clave'
export POSTGRES_PASSWORD='una_contraseña_segura'

kubectl apply -f k8s/00-namespace.yaml

kubectl -n odrl create secret generic odrl-api-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=DATABASE_URL="postgresql+psycopg2://odrl:${POSTGRES_PASSWORD}@odrl-postgres:5432/odrl" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n odrl create secret generic odrl-postgres-secret \
  --from-literal=POSTGRES_USER=odrl \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=POSTGRES_DB=odrl \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Renderizar con las imágenes de GHCR

Define el propietario y la etiqueta. Para despliegues reproducibles se recomienda `sha-<commit>` en lugar de `latest`:

```bash
export GH_USER='juliiosp'
export IMAGE_TAG='latest'
```

Renderiza los manifiestos sustituyendo las imágenes locales definidas por Kustomize:

```bash
kubectl kustomize k8s \
  | sed \
      -e "s#odrl-translator-api:local#ghcr.io/${GH_USER}/tfm-traductor-bidireccional-odrl-api:${IMAGE_TAG}#g" \
      -e "s#odrl-translator-ui:local#ghcr.io/${GH_USER}/tfm-traductor-bidireccional-odrl-ui:${IMAGE_TAG}#g" \
  | kubectl apply -f -
```

Comprueba los rollouts:

```bash
kubectl rollout status statefulset/odrl-postgres -n odrl --timeout=300s
kubectl rollout status deployment/odrl-api -n odrl --timeout=300s
kubectl rollout status deployment/odrl-ui -n odrl --timeout=300s
```

Verifica el resultado:

```bash
kubectl get pods,services,ingress,hpa,pvc -n odrl
```

## GHCR privado

Crea un token de GitHub con permiso de lectura de paquetes y ejecuta:

```bash
kubectl -n odrl create secret docker-registry ghcr-credentials \
  --docker-server=ghcr.io \
  --docker-username='tu_usuario' \
  --docker-password='tu_token' \
  --docker-email='tu_correo'

kubectl -n odrl patch serviceaccount default \
  -p '{"imagePullSecrets":[{"name":"ghcr-credentials"}]}'
```

No guardes el token en Git ni en archivos versionados.

## Acceso externo

El manifiesto incluido usa el host de demostración:

```text
odrl.local
```

En un clúster externo debes adaptar `k8s/70-ingress.yaml` con:

- el dominio real;
- el controlador Ingress disponible;
- TLS y su certificado;
- las políticas de seguridad requeridas.

No expongas públicamente el prototipo sin autenticación, control de acceso, límites de consumo, protección de secretos y una política de retención de datos.

---

# 4. GitHub Actions y GHCR

El workflow `.github/workflows/ci-cd.yml` se ejecuta en pull requests, pushes a `main` y ejecuciones manuales.

Realiza tres trabajos:

1. instala dependencias y ejecuta las pruebas;
2. construye las imágenes de API y UI;
3. en `main`, publica las imágenes para `linux/amd64` y `linux/arm64`.

Etiquetas publicadas:

- `latest`;
- `sha-<commit-completo>`.

El workflow necesita:

```yaml
permissions:
  contents: read
  packages: write
```

Para un entorno estable, utiliza la etiqueta `sha-<commit>` que corresponda a la versión validada.

---

# 5. Diagnóstico rápido

## `ImagePullBackOff` o `ErrImagePull`

Comprueba la imagen configurada y los eventos del pod:

```bash
kubectl -n odrl get deployments \
  -o custom-columns='DEPLOYMENT:.metadata.name,IMAGE:.spec.template.spec.containers[*].image'

kubectl describe pod <nombre-del-pod> -n odrl
```

Causas habituales:

- nombre o etiqueta incorrectos;
- paquete GHCR privado sin credenciales;
- imagen local no cargada en Minikube;
- política `Always` aplicada a una imagen local.

En Minikube con imágenes locales, utiliza siempre:

```bash
./deploy.sh --local
```

## La API no alcanza `ready`

```bash
kubectl get pods -n odrl
kubectl logs -n odrl statefulset/odrl-postgres --tail=200
kubectl logs -n odrl deployment/odrl-api --all-pods=true --tail=200
kubectl get secret odrl-api-secrets odrl-postgres-secret -n odrl
```

`/ready` devuelve error cuando la API no puede conectarse con PostgreSQL.

## La interfaz no conecta con la API

```bash
kubectl get configmap odrl-ui-config -n odrl -o yaml
kubectl get service,endpoints odrl-api -n odrl
kubectl logs -n odrl deployment/odrl-ui --tail=200
```

`API_BASE_URL` debe apuntar a:

```text
http://odrl-api:8000
```

## El Ingress falla durante el despliegue

Espera a que el controlador NGINX esté operativo y vuelve a aplicar el manifiesto:

```bash
kubectl rollout status deployment/ingress-nginx-controller \
  -n ingress-nginx \
  --timeout=300s

kubectl apply -f k8s/70-ingress.yaml
```

Los pods `ingress-nginx-admission-create` y `ingress-nginx-admission-patch` pueden permanecer en estado `Completed`; es el comportamiento esperado.

## El HPA no muestra métricas

```bash
minikube addons enable metrics-server
kubectl get deployment metrics-server -n kube-system
kubectl top pods -n odrl
```

Las métricas pueden tardar unos minutos en aparecer.

## El PVC permanece en `Pending`

```bash
kubectl get storageclass
kubectl describe pvc -n odrl
```

El clúster necesita una `StorageClass` predeterminada o una clase configurada explícitamente en el manifiesto.

---

# 6. Alcance operativo

Los recursos incluidos permiten demostrar:

- separación entre interfaz, API y base de datos;
- persistencia con PostgreSQL;
- probes de salud;
- escalado horizontal de la API;
- Ingress;
- publicación multiarquitectura de imágenes mediante GitHub Actions.

El despliegue no constituye por sí solo una configuración de producción. Un entorno público debe incorporar, como mínimo, autenticación, autorización, TLS, gestión externa de secretos, observabilidad, copias de seguridad y políticas de privacidad y retención.