# Carbon-Aware Orchestration for GreenOps

This document outlines the next orchestration layer for the GreenOps platform: migrating or reducing workloads when carbon intensity is high and notifying or enforcing actions when a resource is wasteful or environmentally expensive.

## Goal

The platform should not only detect idle or stale resources, but also decide when to:
- scale down a workload
- stop an ephemeral job
- move a workload to a lower-carbon region or cluster
- notify the owner for approval before destructive action
- enforce a policy via Kubernetes reconciliation

This is the natural evolution from detection to control.

---

## Design Principles

1. Detection remains the first layer
   - identify stale or idle infrastructure
   - estimate energy waste and carbon emissions

2. Policy remains explicit
   - carbon thresholds are declarative
   - actions are safe and auditable
   - resource owners can override with exemption tags

3. Kubernetes is the control plane
   - custom resources represent desired policy
   - controllers reconcile desired state against runtime conditions
   - cloud APIs provide the execution layer

4. Cloud APIs are the execution plane
   - GKE scheduling and node placement
   - cloud migration APIs
   - stop / snapshot / restore / clone flows
   - stateful workload failover patterns

---

## Proposed CRD: CarbonPolicy

```yaml
apiVersion: sustainability.example.io/v1alpha1
kind: CarbonPolicy
metadata:
  name: prod-low-carbon
spec:
  target:
    namespace: prod
    labels:
      app: analytics
  carbonThreshold:
    co2ePerHour: 25
    regionScore: 0.7
  actions:
    - type: migrate
      toRegion: us-east1
      preferLowCarbon: true
    - type: scaleDown
      minReplicas: 1
    - type: stop
      afterMinutes: 120
  exemptions:
    - key: hygiene-status
      value: exempt-from-hygiene
