# WebQA Agent - Kubernetes Deployment

## Prerequisites

- Kubernetes cluster (1.24+)
- `kubectl` configured
- Container images built and pushed to your registry
- A `ReadWriteMany` PVC provisioner (NFS, EFS, etc.) for shared storage

## Quick Start

### 1. Create namespace and RBAC

```bash
kubectl apply -f namespace.yaml
kubectl apply -f rbac.yaml
```

### 2. Configure secrets

```bash
cp secret.yaml.example secret.yaml
# Edit secret.yaml with your base64-encoded credentials
kubectl apply -f secret.yaml
```

### 3. Update configmap

Edit `configmap.yaml` to set your LLM API endpoint, models, and agent image:

```bash
kubectl apply -f configmap.yaml
```

### 4. Deploy infrastructure

```bash
kubectl apply -f pvc.yaml
kubectl apply -f postgres-statefulset.yaml
kubectl apply -f redis-deployment.yaml
```

### 5. Build and push images

```bash
# Backend
docker build -t your-registry/webqa-be:latest -f backend/Dockerfile .
docker push your-registry/webqa-be:latest

# Frontend
docker build -t your-registry/webqa-fe:latest -f frontend/Dockerfile .
docker push your-registry/webqa-fe:latest

# Agent (for K8s Jobs)
docker build -t your-registry/webqa-agent:latest -f Dockerfile .
docker push your-registry/webqa-agent:latest
```

### 6. Deploy application

Update the image references in `backend-deployment.yaml` and `frontend-deployment.yaml`, then:

```bash
kubectl apply -f backend-deployment.yaml
kubectl apply -f frontend-deployment.yaml
```

### 7. Configure Ingress (optional)

```bash
cp ingress.yaml.example ingress.yaml
# Edit ingress.yaml with your domain
kubectl apply -f ingress.yaml
```

## Using External Database / Redis

If you have existing PostgreSQL or Redis instances:

1. Skip deploying `postgres-statefulset.yaml` and/or `redis-deployment.yaml`
2. Update `configmap.yaml` with your external host/port
3. Update `secret.yaml` with the correct credentials

## File Structure

| File | Description |
|------|-------------|
| `namespace.yaml` | Namespace definition |
| `configmap.yaml` | Non-sensitive configuration |
| `secret.yaml.example` | Template for secrets (copy and fill in) |
| `pvc.yaml` | Shared storage PVC |
| `postgres-statefulset.yaml` | Bundled PostgreSQL (optional) |
| `redis-deployment.yaml` | Bundled Redis (optional) |
| `backend-deployment.yaml` | Backend API server |
| `frontend-deployment.yaml` | Frontend web app |
| `rbac.yaml` | Service accounts and roles |
| `ingress.yaml.example` | Ingress template (copy and configure) |
