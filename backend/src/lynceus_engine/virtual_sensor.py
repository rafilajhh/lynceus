"""Deterministic, hardware-neutral virtual gas sensor response models."""

from __future__ import annotations

import math
from dataclasses import dataclass


SENSOR_FAMILIES = ("PID", "MOX", "Electrochemical", "NDIR", "Pellistor")


@dataclass(frozen=True)
class VirtualSensorConfig:
    """Measurement-chain parameters shared by physical gas-sensor families."""

    family: str = "PID"
    range_ppm: float = 1000.0
    detection_limit_ppm: float = 0.01
    response_time_s: float = 2.0
    recovery_time_s: float = 5.0
    sensitivity: float = 1.0
    cross_sensitivity: float = 0.0
    noise_ppm: float = 0.01
    drift_ppm_h: float = 0.0
    baseline_ppm: float = 0.0
    temperature_coefficient_per_c: float = 0.0
    humidity_coefficient_per_rh: float = 0.0

    def __post_init__(self) -> None:
        if self.family not in SENSOR_FAMILIES:
            raise ValueError(f"family must be one of {SENSOR_FAMILIES}")
        if self.range_ppm <= 0 or self.response_time_s <= 0 or self.recovery_time_s <= 0:
            raise ValueError("range and response/recovery times must be positive")
        if self.detection_limit_ppm < 0 or self.noise_ppm < 0:
            raise ValueError("detection limit and noise must not be negative")


@dataclass(frozen=True)
class VirtualReading:
    elapsed_s: float
    ground_truth_ppm: float
    indicated_ppm: float
    saturated: bool
    below_detection: bool


def step_response(
    config: VirtualSensorConfig,
    *,
    ground_truth_ppm: float,
    previous_ppm: float,
    elapsed_s: float,
    step_s: float,
    temperature_c: float = 25.0,
    humidity_rh: float = 50.0,
    cross_gas_ppm: float = 0.0,
    sample_index: int = 0,
) -> VirtualReading:
    """Advance one deterministic sample through lag, compensation, drift, and noise."""
    if step_s <= 0 or elapsed_s < 0:
        raise ValueError("step_s must be positive and elapsed_s must not be negative")
    target = max(0.0, ground_truth_ppm) * config.sensitivity
    target += max(0.0, cross_gas_ppm) * config.cross_sensitivity
    target += config.baseline_ppm
    target *= 1.0 + config.temperature_coefficient_per_c * (temperature_c - 25.0)
    target *= 1.0 + config.humidity_coefficient_per_rh * (humidity_rh - 50.0)
    target += config.drift_ppm_h * elapsed_s / 3600.0
    tau = config.response_time_s if target >= previous_ppm else config.recovery_time_s
    alpha = 1.0 - math.exp(-step_s / tau)
    indicated = previous_ppm + alpha * (target - previous_ppm)
    # Deterministic pseudo-noise makes scenarios reproducible and testable.
    indicated += config.noise_ppm * math.sin(sample_index * 2.399963229728653)
    indicated = max(0.0, indicated)
    below = indicated < config.detection_limit_ppm
    saturated = indicated > config.range_ppm
    if below:
        indicated = 0.0
    elif saturated:
        indicated = config.range_ppm
    return VirtualReading(elapsed_s, ground_truth_ppm, indicated, saturated, below)
