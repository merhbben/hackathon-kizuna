"""Pipe hydraulics and pumping energy.

* Hazen-Williams friction loss (SI form): hf = 10.67 L Q^1.852 / (C^1.852 D^4.87)
* Minor losses taken as 10 % of friction losses (common design rule).
* Hydraulic power P = rho g Q H ; electrical = P / eta_wire_to_water.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

RHO_G = 1000 * 9.81
# Standard PE pipe internal diameters (m) for PN10 outer 32..200 mm (approx. internal)
PE_DIAMETERS_M = [0.026, 0.0326, 0.0408, 0.051, 0.0614, 0.0736, 0.090, 0.1022, 0.1146, 0.1308, 0.1472, 0.1636]
HAZEN_C_PE = 140.0
MAX_VELOCITY = 1.5  # m/s


def friction_loss_m(length_m: float, q_m3h: float, d_m: float, c: float = HAZEN_C_PE) -> float:
    q = q_m3h / 3600.0
    if q <= 0 or length_m <= 0:
        return 0.0
    return 10.67 * length_m * q ** 1.852 / (c ** 1.852 * d_m ** 4.87)


def select_diameter(q_m3h: float) -> float:
    q = q_m3h / 3600.0
    for d in PE_DIAMETERS_M:
        if q / (math.pi * d * d / 4) <= MAX_VELOCITY:
            return d
    return PE_DIAMETERS_M[-1]


@dataclass
class PumpingPoint:
    flow_m3h: float
    pipe_length_m: float
    diameter_mm: float
    static_lift_m: float
    elevation_gain_m: float
    friction_m: float
    operating_pressure_m: float
    total_head_m: float
    power_kw: float
    specific_energy_kwh_m3: float


def pumping_point(flow_m3h: float, pipe_length_m: float, pumping_depth_m: float, elevation_gain_m: float,
                  operating_pressure_m: float, efficiency: float = 0.5) -> PumpingPoint:
    d = select_diameter(flow_m3h)
    hf = friction_loss_m(pipe_length_m, flow_m3h, d) * 1.10
    head = max(0.0, pumping_depth_m) + max(0.0, elevation_gain_m) + hf + operating_pressure_m
    p_kw = RHO_G * (flow_m3h / 3600) * head / 1000 / max(0.15, efficiency)
    se = p_kw / flow_m3h if flow_m3h > 0 else 0.0
    return PumpingPoint(flow_m3h, round(pipe_length_m, 1), round(d * 1000, 1), pumping_depth_m,
                        round(elevation_gain_m, 2), round(hf, 2), operating_pressure_m, round(head, 2),
                        round(p_kw, 3), round(se, 4))
