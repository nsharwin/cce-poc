# CCE production Kubernetes manifests.
#
# Apply order:
#   1. configmap.yaml
#   2. secret.yaml (populate from .env, not committed)
#   3. api-deployment.yaml + service.yaml
#   4. worker-deployment.yaml
#
# All references use the `cce` namespace.
