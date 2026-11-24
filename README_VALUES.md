# DLA speed settings

The J745 AFS module controls the headlamp shutters using data from the front camera. Its dataset contains speed thresholds that you can edit in DLA Dataset Editor.

## Activation and shutoff

### DLA activation speed

Factory value **60 km/h**. At or above this speed, the module permits DLA to activate when the other conditions are met.

### DLA off speed (either lamp outside full high beam)

Factory value **55 km/h**. Active DLA switches off below this speed if either headlamp is outside full high beam.

### DLA off speed (both lamps at full high beam)

Factory value **30 km/h**. With both headlamps at full high beam, active DLA stays on down to the lower threshold.

### Street lighting inhibit speed

Factory value **85 km/h**. Some datasets use **250 km/h**. When the camera reports qualifying street lighting, the module inhibits DLA below this speed. Once active, the inhibit persists regardless of speed. It clears after the camera stops reporting qualifying street lighting and the release delay expires.

## Beam modes

- **Object masking.** Each headlamp independently creates dark zones around detected vehicles to avoid dazzling other drivers.
- **Dynamic beam range.** Both headlamps receive the same command and use a shared beam cutoff. It rises smoothly to just below the vehicle ahead that appears highest in the camera’s field of view.

DLA can switch to dynamic beam range in dense traffic, on winding roads, or after prolonged wiper operation.

### DLA object indicator min speed

Factory value **50 km/h**. The traffic-density indicator can increase only at or above this speed. When it reaches its switching threshold, DLA changes from object masking to dynamic beam range.

### Curve detection gain axis start (0%)

Factory value **30 km/h**. Some datasets use **40 km/h**.

### Curve detection gain axis full (100%)

Factory value **40 km/h**. Some datasets use **60 km/h**.

The module accumulates steering activity to detect a winding road. The speed-dependent gain is 0% at or below the first point and reaches 100% at the second point. Below the first point, steering activity contributes nothing to this accumulator. When the accumulated value reaches its switching threshold, DLA changes from object masking to dynamic beam range.
