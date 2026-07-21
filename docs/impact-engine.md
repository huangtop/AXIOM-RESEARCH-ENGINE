# Impact Engine

v0.7 adds deterministic causal propagation over the Industry Graph.

## Direction convention

Every propagating edge follows **cause → effect**. A shock starts at an entity and moves only through outgoing active edges.

## Formula

For each edge:

`downstream impact = upstream impact × edge strength × elasticity × attenuation`

Confidence is multiplied by edge confidence. Lead/lag months accumulate along the path. Cycles are rejected per path, and only the strongest discovered path to a node is retained.

## Financial mapping

The v0.7 foundation uses transparent demonstration coefficients:

- company revenue impact = company-node impact
- EPS impact = revenue impact × 1.15
- fair-value impact = EPS impact × 1.10
- ETF impact = sum(holding weight × company fair-value impact)

These coefficients are deliberately explicit and should later be replaced by calibrated DriverImpact and estimate elasticities.
