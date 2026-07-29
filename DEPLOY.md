# Guía de despliegue de ODRL Translator

Este documento describe cómo desplegar, verificar, actualizar y retirar **ODRL Translator** utilizando los recursos incluidos en el repositorio.

La aplicación está formada por tres servicios:

- **Interfaz Gradio**, expuesta en el puerto `7860`.
- **API FastAPI**, expuesta en el puerto `8000`.
- **PostgreSQL**, utilizado para persistir el historial de traducciones.

La guía cubre dos entornos soportados directamente por el proyecto:

1. **Docker Compose**, recomendado para desarrollo, demostraciones y ejecución en una única máquina.
2. **Kubernetes con Minikube**, recomendado para validar el despliegue distribuido, las probes, la persistencia, el Ingress y el escalado horizontal.

---

## 1. Arquitectura de despliegue

```mermaid
flowchart LR
    U[Usuario] --> UI[Gradio UI\nPuerto 7860]
    UI -->|HTTP interno| API[FastAPI\nPuerto 8000]
    API --> DB[(PostgreSQL\nPuerto 5432)]
    API --> OAI[OpenAI API]

    subgraph Plataforma de ejecución
        UI
        API
        DB
    end
```



La interfaz no accede directamente al modelo ni a la base de datos. Todas las operaciones pasan por la API FastAPI mediante la variable `API_BASE_URL`.

En Kubernetes:

- la API se despliega inicialmente con **dos réplicas**;
- el HPA puede escalarla entre **dos y seis réplicas** según el uso de CPU;
- PostgreSQL se ejecuta mediante un `StatefulSet` con almacenamiento persistente;
- la interfaz y la API se exponen internamente mediante servicios `ClusterIP`;
- el Ingress de demostración utiliza el host `odrl.local`.

---

## 2. Métodos de despliegue


| Método            | Uso recomendado                   | Imágenes                           | Persistencia                 | Acceso principal                    |
| ----------------- | --------------------------------- | ---------------------------------- | ---------------------------- | ----------------------------------- |
| Docker Compose    | Desarrollo y demostración local   | Construidas localmente             | Volumen Docker               | `localhost:7860` y `localhost:8000` |
| Minikube local    | Validación integral de Kubernetes | Construidas y cargadas en Minikube | PVC de Kubernetes            | `kubectl port-forward`              |
| Minikube con GHCR | Validación de imágenes publicadas | Descargadas de GHCR                | PVC de Kubernetes            | `kubectl port-forward`              |
| Clúster remoto    | Entorno controlado o producción   | Registro de contenedores           | StorageClass o BD gestionada | Ingress con dominio y TLS           |


El script `deploy.sh` automatiza los dos modos de Minikube. GitHub Actions prueba el proyecto, construye las imágenes y las publica en GHCR, pero **no despliega automáticamente en ningún clúster**.

---

## 3. Archivos relacionados con el despliegue

```text
.
├── Dockerfile.api
├── Dockerfile.ui
├── docker-compose.yml
├── deploy.sh
├── teardown.sh
├── .env.example
├── .dockerignore
├── .github/
│   └── workflows/
│       └── ci-cd.yml
└── k8s/
    ├── 00-namespace.yaml
    ├── 10-configmap.yaml
    ├── 20-secret.example.yaml
    ├── 30-postgres.yaml
    ├── 40-api-deployment.yaml
    ├── 41-api-service.yaml
    ├── 50-ui-deployment.yaml
    ├── 51-ui-service.yaml
    ├── 60-hpa.yaml
    ├── 70-ingress.yaml
    └── kustomization.yaml
```

`20-secret.example.yaml` es únicamente una plantilla documental. No forma parte de `kustomization.yaml` y no debe contener credenciales reales.

---

## 4. Configuración y secretos

### 4.1 Variables principales


| Variable                 | Componente | Obligatoria                         | Valor predeterminado              | Descripción                                                |
| ------------------------ | ---------- | ----------------------------------- | --------------------------------- | ---------------------------------------------------------- |
| `OPENAI_API_KEY`         | API        | Sí para traducción y evaluación LLM | —                                 | Credencial del proveedor de modelos.                       |
| `OPENAI_MODEL`           | API        | No                                  | `gpt-4.1-mini`                    | Modelo utilizado por defecto.                              |
| `OPENAI_TIMEOUT`         | API        | No                                  | `30`                              | Timeout de cada llamada individual al modelo, en segundos. |
| `MAX_REPAIR_ATTEMPTS`    | API        | No                                  | `3`                               | Límite de iteraciones de reparación automática.            |
| `DATABASE_URL`           | API        | Sí en los despliegues incluidos     | Generada por el despliegue        | Cadena de conexión de SQLAlchemy.                          |
| `API_CORS_ORIGINS`       | API        | No                                  | `*` en Kubernetes                 | Orígenes CORS separados por comas.                         |
| `API_BASE_URL`           | UI         | Sí en contenedores                  | Configurada por el despliegue     | URL interna de FastAPI.                                    |
| `API_REQUEST_TIMEOUT`    | UI         | No                                  | `300`                             | Timeout de las peticiones normales.                        |
| `API_EVALUATION_TIMEOUT` | UI         | No                                  | `3600`                            | Timeout de la evaluación completa.                         |
| `POSTGRES_USER`          | PostgreSQL | No                                  | `odrl`                            | Usuario de la base de datos.                               |
| `POSTGRES_PASSWORD`      | PostgreSQL | Sí fuera de desarrollo              | `odrl` en Compose si no se cambia | Contraseña de PostgreSQL.                                  |
| `POSTGRES_DB`            | PostgreSQL | No                                  | `odrl`                            | Nombre de la base de datos.                                |


# Parte I. Despliegue con Docker Compose

## 5. Requisitos

- Docker Desktop, o Docker Engine con el plugin Docker Compose.
- Una clave válida de OpenAI.
- Puertos libres:
  - `7860` para Gradio;
  - `8000` para FastAPI.

Comprueba la instalación:

```bash
docker --version
docker compose version
```

---

## 6. Preparar la configuración

Desde la raíz del proyecto:

```bash
cp .env.example .env
```

Edita `.env` y configura al menos:

```dotenv
OPENAI_API_KEY=tu_clave
POSTGRES_PASSWORD=una_contraseña_segura
```

Configuración completa de ejemplo:

```dotenv
OPENAI_API_KEY=tu_clave
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT=30
MAX_REPAIR_ATTEMPTS=3

POSTGRES_USER=odrl
POSTGRES_PASSWORD=una_contraseña_segura
POSTGRES_DB=odrl

API_REQUEST_TIMEOUT=300
API_EVALUATION_TIMEOUT=3600
```

Valida la resolución del archivo Compose sin imprimir la configuración completa:

```bash
docker compose config --quiet
```

---

## 7. Construir e iniciar los servicios

### Ejecución en primer plano

```bash
docker compose up --build
```

Este modo muestra los registros de todos los servicios y puede detenerse con `Ctrl+C`.

### Ejecución en segundo plano

```bash
docker compose up --build -d
```

Consulta el estado:

```bash
docker compose ps
```

Los servicios deberían terminar en estado `healthy` después del arranque.

---

## 8. Acceso a la aplicación


| Recurso         | URL                                  |
| --------------- | ------------------------------------ |
| Interfaz Gradio | `http://localhost:7860`              |
| API FastAPI     | `http://localhost:8000`              |
| Swagger UI      | `http://localhost:8000/docs`         |
| Esquema OpenAPI | `http://localhost:8000/openapi.json` |
| Liveness        | `http://localhost:8000/health`       |
| Readiness       | `http://localhost:8000/ready`        |


Comprobaciones rápidas:

```bash
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/ready
```

`/health` confirma que el proceso de la API está activo. `/ready` comprueba además la conexión con PostgreSQL.

---

## 9. Registros y diagnóstico

Todos los servicios:

```bash
docker compose logs -f
```

Solo la API:

```bash
docker compose logs -f api
```

Solo la interfaz:

```bash
docker compose logs -f ui
```

Solo PostgreSQL:

```bash
docker compose logs -f db
```

Últimas 100 líneas:

```bash
docker compose logs --tail=100 api ui db
```

---

## 10. Reinicio y actualización

Reiniciar un servicio sin reconstruir la imagen:

```bash
docker compose restart api
```

Reconstruir después de modificar el código o las dependencias:

```bash
docker compose up --build -d
```

Forzar una reconstrucción completa:

```bash
docker compose build --no-cache
docker compose up -d
```

La tabla `translations` se crea automáticamente al iniciar la API. El proyecto no incorpora actualmente un sistema de migraciones como Alembic; cualquier evolución compleja del esquema debe planificarse antes de actualizar un entorno con datos persistentes.

---

## 11. Copias de seguridad de PostgreSQL

Crear una copia lógica:

```bash
docker compose exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > odrl_backup.sql
```

Restaurarla en una base de datos vacía o compatible:

```bash
cat odrl_backup.sql | docker compose exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
```

Comprueba siempre el contenido y la restauración de las copias antes de depender de ellas.

---

## 12. Detener o eliminar el entorno Compose

Detener y retirar los contenedores conservando los datos:

```bash
docker compose down
```

Eliminar también el volumen de PostgreSQL:

```bash
docker compose down -v
```

> [!WARNING]
> `docker compose down -v` elimina de forma permanente el historial almacenado en el volumen `pgdata`.

---



# Parte II. Despliegue automatizado en Minikube

## 13. Requisitos

- Docker en funcionamiento.
- `kubectl`.
- `minikube`.
- Una clave válida de OpenAI.
- Recursos suficientes para ejecutar PostgreSQL, dos réplicas de la API y una réplica de la interfaz.

Comprobación:

```bash
docker info
kubectl version --client
minikube version
```

En macOS con Homebrew:

```bash
brew install kubectl minikube
```

Asegura permisos de ejecución para los scripts:

```bash
chmod +x deploy.sh teardown.sh
```

---

## 14. Opción A: construir las imágenes localmente

Este es el modo más directo para probar cambios sin publicar imágenes en un registro.

```bash
export OPENAI_API_KEY='tu_clave'
export POSTGRES_PASSWORD='una_contraseña_segura'
./deploy.sh --local
```

El script realiza las siguientes operaciones:

1. verifica `docker`, `kubectl` y `minikube`;
2. inicia Minikube con el driver Docker cuando es necesario;
3. activa los complementos `ingress` y `metrics-server`;
4. construye `odrl-translator-api:local` y `odrl-translator-ui:local`;
5. carga ambas imágenes en Minikube;
6. crea el namespace y los secretos requeridos;
7. prepara una copia temporal de los recursos Kustomize;
8. cambia `imagePullPolicy` a `IfNotPresent` para utilizar las imágenes locales;
9. aplica los manifiestos;
10. espera a los rollouts de PostgreSQL, FastAPI y Gradio;
11. abre un `port-forward` de la interfaz en `http://localhost:8080`.

El comando permanece activo mientras mantiene el túnel. `Ctrl+C` cierra el `port-forward`, pero **no elimina el despliegue**.

---

## 15. Opción B: utilizar imágenes publicadas en GHCR

El workflow `.github/workflows/ci-cd.yml` publica, después de un push válido a `main`, estas imágenes:

```text
ghcr.io/<propietario>/odrl-translator-api:latest
ghcr.io/<propietario>/odrl-translator-ui:latest
```

También publica etiquetas inmutables con el formato:

```text
sha-<commit-completo>
```

Para desplegar la etiqueta `latest` mediante el script:

```bash
export OPENAI_API_KEY='tu_clave'
export POSTGRES_PASSWORD='una_contraseña_segura'
GH_USER='tu_usuario_o_organizacion' ./deploy.sh
```

También puede indicarse el usuario mediante una opción:

```bash
./deploy.sh --user tu_usuario_o_organizacion
```

Las imágenes deben ser públicas o el clúster debe disponer de credenciales para GHCR.

> [!IMPORTANT]
> El script automatizado no crea un `imagePullSecret` para paquetes privados. Para un registro privado debe configurarse el secreto de acceso y asociarlo a los pods o a la cuenta de servicio.

En entornos estables debe evitarse `latest` y utilizarse una etiqueta inmutable `sha-<commit>`.

---

## 16. Acceso después del despliegue

El script abre automáticamente la interfaz mediante:

```text
http://localhost:8080
```

Para recuperar el acceso si se ha cerrado el túnel:

```bash
kubectl -n odrl port-forward service/odrl-ui 8080:7860
```

En otra terminal, expón la API:

```bash
kubectl -n odrl port-forward service/odrl-api 8000:8000
```

Después estarán disponibles:


| Recurso    | URL                            |
| ---------- | ------------------------------ |
| Interfaz   | `http://localhost:8080`        |
| API        | `http://localhost:8000`        |
| Swagger UI | `http://localhost:8000/docs`   |
| Liveness   | `http://localhost:8000/health` |
| Readiness  | `http://localhost:8000/ready`  |


---

## 17. Comprobar el estado del clúster

Vista general:

```bash
kubectl get pods,services,ingress,hpa,pvc -n odrl
```

Rollouts:

```bash
kubectl rollout status statefulset/odrl-postgres -n odrl
kubectl rollout status deployment/odrl-api -n odrl
kubectl rollout status deployment/odrl-ui -n odrl
```

Eventos recientes:

```bash
kubectl get events -n odrl --sort-by=.metadata.creationTimestamp
```

Descripción de un pod:

```bash
kubectl describe pod <nombre-del-pod> -n odrl
```

Registros de la API:

```bash
kubectl logs -n odrl deployment/odrl-api --all-pods=true --tail=200
```

Registros de la interfaz:

```bash
kubectl logs -n odrl deployment/odrl-ui --tail=200
```

Registros de PostgreSQL:

```bash
kubectl logs -n odrl statefulset/odrl-postgres --tail=200
```

Comprobar las métricas utilizadas por el HPA:

```bash
kubectl top pods -n odrl
kubectl get hpa odrl-api -n odrl
```

`kubectl top` necesita que `metrics-server` esté operativo. Puede tardar unos minutos en disponer de métricas tras iniciar Minikube.

---

## 18. Ingress de demostración

El manifiesto `k8s/70-ingress.yaml` utiliza el host:

```text
odrl.local
```

Rutas principales:


| Ruta            | Servicio        |
| --------------- | --------------- |
| `/`             | Interfaz Gradio |
| `/api`          | API FastAPI     |
| `/docs`         | Swagger UI      |
| `/openapi.json` | Esquema OpenAPI |
| `/health`       | Liveness        |
| `/ready`        | Readiness       |


Comprueba el controlador:

```bash
minikube addons enable ingress
kubectl get pods -n ingress-nginx
kubectl get ingress -n odrl
```

En entornos donde la IP de Minikube sea accesible desde el host, añade una entrada local:

```bash
echo "$(minikube ip) odrl.local" | sudo tee -a /etc/hosts
```

Después prueba:

```text
http://odrl.local
```

La conectividad del Ingress puede variar según el sistema operativo y el driver de Minikube. En macOS o Windows con el driver Docker puede ser necesario utilizar `minikube tunnel` o recurrir al `port-forward`, que es el método de acceso más predecible para este proyecto.

---

## 19. Actualizar un despliegue de Minikube

### Con imágenes locales

Después de cambiar el código:

```bash
./deploy.sh --local
```

El script reconstruye y vuelve a cargar las imágenes. Si los pods conservan una imagen anterior con la misma etiqueta, fuerza su recreación:

```bash
kubectl rollout restart deployment/odrl-api -n odrl
kubectl rollout restart deployment/odrl-ui -n odrl
```

### Con GHCR

Tras publicar una imagen nueva:

```bash
GH_USER='tu_usuario' ./deploy.sh
```

Para un proceso reproducible, utiliza etiquetas inmutables y actualiza explícitamente los manifiestos del entorno en lugar de depender de `latest`.

---

## 20. Retirar el despliegue

Eliminar el namespace `odrl` y todos sus recursos:

```bash
./teardown.sh
```

Eliminar el despliegue y detener Minikube, conservando el clúster:

```bash
./teardown.sh --stop
```

Eliminar también el clúster Minikube:

```bash
./teardown.sh --delete-cluster
```

> [!WARNING]
> El script elimina el namespace completo. Esto incluye el `PersistentVolumeClaim` de PostgreSQL y, según la política de reclamación del almacenamiento, puede eliminar también sus datos.

---

# Parte III. Aplicación manual de los manifiestos

## 21. Cuándo utilizar el proceso manual

El proceso manual resulta útil cuando:

- se despliega en un clúster distinto de Minikube;
- se necesita una etiqueta concreta de las imágenes;
- el registro es privado;
- se integran secretos gestionados externamente;
- se modifican dominio, TLS, almacenamiento, recursos o número de réplicas.

---

## 22. Requisitos del clúster

El clúster debe disponer de:

- una versión de Kubernetes compatible con `autoscaling/v2`;
- un `StorageClass` predeterminado para el PVC de PostgreSQL;
- un proveedor de métricas si se desea utilizar el HPA;
- un controlador compatible con `ingressClassName: nginx` si se aplica el Ingress;
- acceso al registro que contiene las imágenes;
- capacidad para ejecutar los recursos solicitados por los pods.

Recursos declarados actualmente:


| Componente | Réplicas | CPU solicitada | CPU límite      | Memoria solicitada | Memoria límite |
| ---------- | -------- | -------------- | --------------- | ------------------ | -------------- |
| API        | 2–6      | `100m` por pod | `1000m` por pod | `256Mi` por pod    | `1Gi` por pod  |
| UI         | 1        | `100m`         | `500m`          | `256Mi`            | `768Mi`        |
| PostgreSQL | 1        | `100m`         | `500m`          | `128Mi`            | `512Mi`        |


PostgreSQL solicita un volumen `ReadWriteOnce` de `1Gi`.

---

## 23. Preparar imágenes y Kustomize

Crea una copia de trabajo para no modificar accidentalmente los recursos versionados:

```bash
DEPLOY_DIR="$(mktemp -d)"
cp -R k8s/. "$DEPLOY_DIR/"
```

Edita el bloque `images` de `$DEPLOY_DIR/kustomization.yaml`:

```yaml
images:
  - name: ghcr.io/OWNER/odrl-translator-api
    newName: ghcr.io/tu_usuario/odrl-translator-api
    newTag: sha-commit_inmutable
  - name: ghcr.io/OWNER/odrl-translator-ui
    newName: ghcr.io/tu_usuario/odrl-translator-ui
    newTag: sha-commit_inmutable
```

Revisa el resultado antes de aplicarlo:

```bash
kubectl kustomize "$DEPLOY_DIR" > rendered.yaml
```

No añadas `rendered.yaml` al repositorio si contiene datos o modificaciones específicas del entorno.

---

## 24. Crear namespace y secretos

Crea primero el namespace:

```bash
kubectl apply -f k8s/00-namespace.yaml
```

Crea el secreto de PostgreSQL:

```bash
kubectl -n odrl create secret generic odrl-postgres-secret \
  --from-literal=POSTGRES_USER='odrl' \
  --from-literal=POSTGRES_PASSWORD='una_contraseña_segura' \
  --from-literal=POSTGRES_DB='odrl'
```

Crea el secreto de la API:

```bash
kubectl -n odrl create secret generic odrl-api-secrets \
  --from-literal=OPENAI_API_KEY='tu_clave' \
  --from-literal=DATABASE_URL='postgresql+psycopg2://odrl:una_contraseña_segura@odrl-postgres:5432/odrl'
```

Para que el proceso sea repetible sin fallar cuando el secreto ya existe:

```bash
kubectl -n odrl create secret generic odrl-api-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=DATABASE_URL="$DATABASE_URL" \
  --dry-run=client -o yaml | kubectl apply -f -
```

En producción, sustituye estos comandos por la integración con el sistema de secretos de la plataforma.

---

## 25. Aplicar y verificar

Aplica los recursos:

```bash
kubectl apply -k "$DEPLOY_DIR"
```

Espera a que estén disponibles:

```bash
kubectl rollout status statefulset/odrl-postgres -n odrl --timeout=300s
kubectl rollout status deployment/odrl-api -n odrl --timeout=300s
kubectl rollout status deployment/odrl-ui -n odrl --timeout=300s
```

Comprueba el estado:

```bash
kubectl get all,ingress,hpa,pvc -n odrl
```

Prueba la API desde el propio clúster:

```bash
kubectl run curl-check \
  --namespace odrl \
  --rm -it \
  --restart=Never \
  --image=curlimages/curl \
  -- http://odrl-api:8000/ready
```

---

## 26. Registro privado de contenedores

Ejemplo para GHCR privado:

```bash
kubectl -n odrl create secret docker-registry ghcr-credentials \
  --docker-server=ghcr.io \
  --docker-username='tu_usuario' \
  --docker-password='tu_token' \
  --docker-email='tu_correo'
```

Después añade a las especificaciones de los pods:

```yaml
spec:
  imagePullSecrets:
    - name: ghcr-credentials
```

Puede añadirse tanto en `40-api-deployment.yaml` como en `50-ui-deployment.yaml`, preferiblemente mediante un overlay específico del entorno.

El token debe disponer únicamente de los permisos mínimos necesarios para descargar paquetes.

---

# Parte IV. CI/CD y publicación de imágenes

## 27. Flujo de GitHub Actions

El workflow se activa en:

- pull requests dirigidas a `main`;
- pushes a `main`;
- ejecuciones manuales mediante `workflow_dispatch`.

El flujo contiene tres trabajos:

1. **Test application**
  - instala Python 3.12 y las dependencias;
  - compila `app` y `tests`;
  - ejecuta Pytest con SQLite temporal.
2. **Build container images**
  - construye las imágenes API y UI;
  - verifica que ambos Dockerfiles pueden compilarse.
3. **Publish images to GHCR**
  - se ejecuta solo fuera de pull requests y sobre `main`;
  - publica imágenes para `linux/amd64` y `linux/arm64`;
  - genera la etiqueta `latest`;
  - genera una etiqueta inmutable `sha-<GITHUB_SHA>`.

El workflow utiliza `GITHUB_TOKEN` y requiere:

```yaml
permissions:
  contents: read
  packages: write
```

No necesita una clave de OpenAI para ejecutar las pruebas actuales, ya que estas no realizan llamadas reales al proveedor.

---

## 28. Estrategia recomendada de promoción

Para un entorno estable:

1. fusiona el cambio en `main`;
2. espera a que pruebas, compilación y publicación terminen correctamente;
3. identifica la etiqueta `sha-<commit>` publicada;
4. actualiza el entorno de destino para utilizar esa etiqueta;
5. revisa el render de Kustomize;
6. aplica el despliegue;
7. comprueba rollouts, probes, logs y una traducción de prueba;
8. conserva la etiqueta anterior para facilitar una reversión.

No utilices `latest` como única referencia en un entorno donde sea necesario reproducir o auditar una versión concreta.

---

# Parte V. Operación y resolución de problemas

## 29. La API no alcanza el estado `ready`

Comprueba PostgreSQL:

```bash
kubectl get pod -n odrl -l app.kubernetes.io/name=odrl-postgres
kubectl logs -n odrl statefulset/odrl-postgres
```

Verifica que los secretos existen:

```bash
kubectl get secret odrl-api-secrets odrl-postgres-secret -n odrl
```

Revisa los eventos y la API:

```bash
kubectl describe deployment odrl-api -n odrl
kubectl logs -n odrl deployment/odrl-api --all-pods=true
```

La probe `/ready` devuelve `503` cuando no puede ejecutar `SELECT 1` sobre la base de datos.



## 30. `ImagePullBackOff` o `ErrImagePull`

Causas habituales:

- nombre o etiqueta inexistentes;
- paquete privado sin `imagePullSecret`;
- falta de conectividad con el registro;
- imágenes locales no cargadas en Minikube;
- `imagePullPolicy: Always` aplicada por error a una imagen local.

Diagnóstico:

```bash
kubectl describe pod <pod> -n odrl
minikube image ls | grep odrl-translator
```

Para imágenes locales, utiliza `./deploy.sh --local`, que cambia la política a `IfNotPresent` durante el renderizado.

---

## 31. La interfaz no puede conectar con la API

Comprueba la variable configurada:

```bash
kubectl get configmap odrl-ui-config -n odrl -o yaml
```

Debe contener:

```text
API_BASE_URL=http://odrl-api:8000
```

Verifica el servicio y sus endpoints:

```bash
kubectl get service odrl-api -n odrl
kubectl get endpoints odrl-api -n odrl
```

Prueba la conectividad desde el pod de la interfaz:

```bash
kubectl exec -n odrl deployment/odrl-ui -- \
  python -c "import urllib.request; print(urllib.request.urlopen('http://odrl-api:8000/health').read())"
```

---

## 32. El HPA muestra métricas desconocidas

Comprueba `metrics-server`:

```bash
minikube addons enable metrics-server
kubectl get deployment metrics-server -n kube-system
kubectl top pods -n odrl
```

El HPA necesita varios minutos para recibir métricas después del arranque.

## 33. El PVC permanece en estado `Pending`

Comprueba el almacenamiento disponible:

```bash
kubectl get storageclass
kubectl describe pvc -n odrl
```

El manifiesto no fija `storageClassName`, por lo que depende de que el clúster disponga de una clase predeterminada.

En un clúster remoto puede ser necesario configurar explícitamente la clase apropiada.

---

## 34. Las evaluaciones agotan el timeout

La evaluación completa puede realizar numerosas llamadas al modelo. Los valores incluidos son:

```text
API_REQUEST_TIMEOUT=300
API_EVALUATION_TIMEOUT=3600
```

El Ingress configura además:

```text
proxy-read-timeout=3600
proxy-send-timeout=3600
```

Revisa:

- disponibilidad y límites del proveedor LLM;
- registros de la API;
- recursos de CPU y memoria;
- timeouts del proxy o balanceador externo;
- número de casos y evaluación mediante segundo LLM.

No aumentes los timeouts sin investigar primero la causa del bloqueo.

---

## 35. La clave de OpenAI no funciona

Comprueba únicamente que el secreto contiene la clave esperada, sin imprimirla:

```bash
kubectl get secret odrl-api-secrets -n odrl
```

Recréalo desde una variable de entorno:

```bash
kubectl -n odrl create secret generic odrl-api-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=DATABASE_URL="$DATABASE_URL" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Reinicia la API para que los pods reciban el nuevo valor:

```bash
kubectl rollout restart deployment/odrl-api -n odrl
kubectl rollout status deployment/odrl-api -n odrl
```

---

## 36. Reversión

Si se utiliza una etiqueta inmutable, vuelve a la imagen anterior en la copia o overlay de Kustomize y aplica de nuevo:

```bash
kubectl apply -k <directorio-del-entorno>
```

Después verifica:

```bash
kubectl rollout status deployment/odrl-api -n odrl
kubectl rollout status deployment/odrl-ui -n odrl
```

También puede inspeccionarse el historial del Deployment:

```bash
kubectl rollout history deployment/odrl-api -n odrl
kubectl rollout history deployment/odrl-ui -n odrl
```

La reversión de contenedores no revierte automáticamente cambios incompatibles en la base de datos. Debe existir una estrategia separada para los datos y el esquema.

---

## Alcance

Esta guía documenta el estado actual del repositorio. El despliegue incluido permite demostrar separación de componentes, persistencia, health checks, escalado y publicación de imágenes, pero no convierte por sí solo el prototipo en un servicio público endurecido para producción.