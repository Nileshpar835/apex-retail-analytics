# Store Intelligence System Design

## Architecture Overview

The system is built as an **event-driven pipeline** that separates heavy computer vision from low-latency API serving:

1. **Vision Node (GPU-bound)**
   - Runs YOLOv8 tracking and zone/event generation from CCTV streams.
   - Performs staff detection and zone assignment per tracked person.
   - Publishes normalized events to Redis Pub/Sub (`store_events`).

2. **Realtime/Event Bus (Redis Pub/Sub)**
   - Works as the decoupling layer between producers (vision) and consumers (API/dashboard).
   - Buffers flow via asynchronous publish/subscribe patterns.
   - Allows independent scaling of vision workers and API/websocket workers.

3. **FastAPI Intelligence Layer (CPU/lightweight)**
   - Consumes event stream and ingests validated records.
   - Computes metrics/funnel/heatmap/anomalies.
   - Serves dashboards and APIs without waiting on GPU inference.

This separation ensures the API remains responsive even when vision inference load spikes, while GPU nodes can process frames at their own throughput.

---

## Engineering Trade-offs

### Why HSV color masking for staff classification (instead of a separate NN classifier)

Staff identification uses HSV-based masking plus contextual rules because:

- **Compute efficiency:** HSV thresholding is extremely cheap compared with running a second neural network per detection.
- **Deterministic behavior:** The uniform policy is strict (black apparel), and the HSV mask is calibrated to the observed hue band in footage (including purple-tinted appearance under lighting), yielding predictable and auditable outcomes.
- **Operational simplicity:** No labelled staff dataset, retraining pipeline, or model version management is required.
- **Real-time suitability:** Keeps latency low on edge hardware where YOLO already consumes most inference budget.

A dedicated classifier could improve generalization in varied uniforms, but for the current black-uniform constraint, HSV heuristics provide the best speed-to-reliability trade-off.

### Why normalized polygon coordinates

Zone polygons are stored in normalized coordinates (`0.0–1.0`) instead of raw pixels because:

- **Resolution independence:** The same layout works across 720p/1080p/4K inputs.
- **Camera portability:** Geometry remains valid when stream dimensions or transcoding settings change.
- **Config reuse:** One zone definition can be shared across environments and devices.

At runtime, normalized vertices are converted to frame pixels for point-in-polygon checks.

---

## Edge Case Handling

### Occlusion mitigation

Occlusions (people partially/temporarily hidden) are reduced using:

- Persistent multi-object tracking IDs from the detector tracker.
- Short lost-track grace windows before finalizing disappearance.
- Zone transition logic driven by trajectory history instead of single-frame state.

This avoids excessive entry/exit churn when a shopper is briefly blocked by fixtures or crowds.

### ID switching mitigation

Cross-frame ID instability is mitigated by:

- Track aliasing/merge logic using spatial proximity and short temporal windows.
- Lightweight appearance signatures for re-identification continuity.
- Overlap-camera entry deduplication to prevent duplicate ENTRY/REENTRY inflation.

Together, these controls reduce duplicate visitors caused by tracker identity swaps.

### Mathematical exclusion of staff from conversion metrics

Staff exclusion is explicit in metric math:

- Sessions where `is_staff=True` are removed from visitor denominator sets.
- Billing/queue/buy-intent events with `is_staff=True` are ignored for conversion attribution.
- Funnel, heatmap, queue depth, abandonment, and occupancy calculations apply the same filter.

So the conversion formula is effectively:

`conversion_rate = converted_customers / unique_customers`

where both numerator and denominator are computed on **customer-only** sessions.

---

## Scalability to 40 Stores

The architecture scales horizontally by splitting control-plane and edge inference responsibilities.

### Cloud-side scaling

- Move Redis from local deployment to a **managed cloud cache** (e.g., Redis service with high availability (HA), persistence options, monitoring, and autoscaling).
- Run multiple FastAPI replicas behind a load balancer, all consuming/publishing through managed Redis.
- Keep APIs stateless; persist historical events/analytics in centralized data storage.

### Edge-side scaling (Surat and Bangalore)

- Deploy vision workers on store-local edge devices in Surat/Bangalore for low-latency video access.
- Each edge node performs YOLO inference locally and publishes compact event messages upstream.
- WAN traffic stays lightweight (events, not raw video), reducing bandwidth and central GPU cost.

### Multi-store operation model

- Namespace event streams by `store_id` and camera IDs.
- Use per-store consumer groups/services for isolation and fault containment.
- Add observability (lag, dropped events, per-store throughput, stale feed alerts).

With this model, scaling from 1 to 40 stores is mostly operational (more edge workers + managed Redis/API replicas), without redesigning core application logic.
