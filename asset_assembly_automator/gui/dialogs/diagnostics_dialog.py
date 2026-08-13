from __future__ import annotations

import asyncio

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from asset_assembly_automator.clients.agent_cli import get_agent_cli
from asset_assembly_automator.clients.magnific_client import create_magnific_client
from asset_assembly_automator.clients.meshy_client import MeshyClient
from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.paths import expand_path


class DiagnosticsDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Diagnostics")
        self.resize(520, 220)
        layout = QVBoxLayout(self)

        self.meshy_label = QLabel("Meshy: checking…")
        self.magnific_label = QLabel("Magnific: checking…")
        self.unity_label = QLabel("Unity MCP: checking…")
        for label in (self.meshy_label, self.magnific_label, self.unity_label):
            label.setWordWrap(True)
            layout.addWidget(label)

        row = QHBoxLayout()
        recheck = QPushButton("Recheck")
        recheck.clicked.connect(lambda: asyncio.ensure_future(self._run_checks()))
        row.addWidget(recheck)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        asyncio.ensure_future(self._run_checks())

    def _set_status(self, label: QLabel, ok: bool | None, message: str) -> None:
        if ok is True:
            color = "#22C55E"
            prefix = "●"
        elif ok is False:
            color = "#EF4444"
            prefix = "●"
        else:
            color = "#EAB308"
            prefix = "○"
        label.setText(f'<span style="color:{color}; font-weight:bold">{prefix}</span> {message}')

    async def _run_checks(self) -> None:
        meshy = MeshyClient()
        try:
            result = await meshy.health_check()
        finally:
            await meshy.close()
        self._set_status(
            self.meshy_label,
            result.get("available"),
            f"Meshy — {result.get('reason', 'unknown')}",
        )

        magnific = create_magnific_client(True, expand_path("%TEMP%/aaa_diag"))
        try:
            mag_result = await magnific.health_check()
        finally:
            if hasattr(magnific, "close"):
                await magnific.close()
        self._set_status(
            self.magnific_label,
            mag_result.get("available"),
            f"Magnific — {mag_result.get('reason', 'unknown')}",
        )

        agent = get_agent_cli(dry_run=False)
        agent_health = await agent.health_check()
        unity_ok: bool | None = None
        unity_reason = str(agent_health.get("reason") or "agent unavailable")
        if agent_health.get("available"):
            ping_prompt = (
                "Ping Unity Editor using unity_editor_ping via MCP. "
                "Reply PONG if reachable, else explain."
            )
            repo = expand_path("%LOCALAPPDATA%/AssetAssemblyAutomator/diagnostics")
            repo.mkdir(parents=True, exist_ok=True)
            try:
                ping = await agent.run_workflow(
                    ping_prompt,
                    cwd=str(repo),
                    timeout=60,
                    prompt_file_name="unity_mcp_ping",
                )
                unity_ok = bool(ping.get("success"))
                unity_reason = ping.get("final_text") or unity_reason
            except Exception as exc:
                unity_ok = False
                unity_reason = str(exc)

        self._set_status(
            self.unity_label,
            unity_ok,
            f"Unity MCP (via agent) — {unity_reason[:200]}",
        )
