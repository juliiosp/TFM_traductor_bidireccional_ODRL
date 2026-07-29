# Recursos Kubernetes

Los manifiestos incluyen:

- PostgreSQL mediante `StatefulSet` y `PersistentVolumeClaim`.
- FastAPI mediante `Deployment`, `Service`, probes y HPA.
- Gradio mediante `Deployment`, `Service` y probes.
- Ingress para la interfaz y la API.

Los secretos no forman parte de `kustomization.yaml`. `20-secret.example.yaml` es únicamente documental y no debe contener valores reales.

## Método recomendado para Minikube

Desde la raíz del proyecto:

```bash
export OPENAI_API_KEY='...'
./deploy.sh --local
```

O para usar las imágenes públicas publicadas por GitHub Actions:

```bash
export OPENAI_API_KEY='...'
GH_USER='tu_usuario' ./deploy.sh
```

El script trabaja con una copia temporal de los manifiestos, por lo que no modifica `kustomization.yaml` al cambiar las imágenes.

## Aplicación manual

Crea primero el namespace y los secretos:

```bash
kubectl apply -f 00-namespace.yaml
kubectl -n odrl create secret generic odrl-postgres-secret \
  --from-literal=POSTGRES_USER=odrl \
  --from-literal=POSTGRES_PASSWORD='replace_me' \
  --from-literal=POSTGRES_DB=odrl

kubectl -n odrl create secret generic odrl-api-secrets \
  --from-literal=OPENAI_API_KEY='replace_me' \
  --from-literal=DATABASE_URL='postgresql+psycopg2://odrl:replace_me@odrl-postgres:5432/odrl'
```

Después ajusta el bloque `images` de `kustomization.yaml` y ejecuta:

```bash
kubectl apply -k .
```

GitHub Actions no ejecuta este comando ni accede al clúster; solo prueba, construye y publica las imágenes.
