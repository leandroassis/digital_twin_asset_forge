"""Alert dispatching and synchronization with the Web Visualizer REST API (:8000)."""

from typing import Dict, List, Set

import requests
from loguru import logger

from model.rules import AlertPayload


class AlertNotifier:
    """Manages active alert lifecycle with the visualizer (creation and resolution)."""

    def __init__(self, viz_base_url: str = "http://localhost:8000"):
        self.base_url = viz_base_url.rstrip("/")
        self._last_alerted_elements: Set[str] = set()

    def sync_alerts(self, current_alerts: List[AlertPayload]) -> Dict[str, int]:
        """Dispatches active alerts and clears alerts for panels that returned to normal."""
        created_count = 0
        cleared_count = 0
        current_alerted_elements: Set[str] = set()

        # 1. Dispatch all active alerts (POST /api/alerts)
        for alert in current_alerts:
            current_alerted_elements.add(alert.element_id)
            try:
                resp = requests.post(
                    f"{self.base_url}/api/alerts",
                    json=alert.to_dict(),
                    timeout=5,
                )
                if resp.status_code == 200:
                    created_count += 1
                else:
                    logger.warning(f"Failed to post alert for {alert.element_id}: HTTP {resp.status_code}")
            except requests.RequestException as exc:
                logger.warning(f"Visualizer unreachable at {self.base_url}: {exc}")
                return {"created": 0, "cleared": 0, "active": len(current_alerts)}

        # 2. Clear alerts for panels no longer in fault state (DELETE /api/alerts/{id})
        resolved_elements = self._last_alerted_elements - current_alerted_elements
        for element_id in resolved_elements:
            try:
                resp = requests.delete(f"{self.base_url}/api/alerts/{element_id}", timeout=5)
                if resp.status_code in (200, 404):
                    cleared_count += 1
            except requests.RequestException as exc:
                logger.warning(f"Failed to clear resolved alert for {element_id}: {exc}")

        self._last_alerted_elements = current_alerted_elements
        return {
            "created": created_count,
            "cleared": cleared_count,
            "active": len(current_alerts),
        }
