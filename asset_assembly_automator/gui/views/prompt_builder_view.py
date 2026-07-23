from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from asset_assembly_automator.stages._base import load_template

_DEFAULT_IDENTITY = "cyberpunk street courier NPC"
_DEFAULT_STYLE = "game-ready character concept"


class PromptBuilderView(QWidget):
    promptSaveRequested = pyqtSignal(str, str, dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.pipeline_name = QLabel("—")
        self.identity = QLineEdit(_DEFAULT_IDENTITY)
        self.style = QLineEdit(_DEFAULT_STYLE)
        form.addRow("Pipeline", self.pipeline_name)
        form.addRow("Identity", self.identity)
        form.addRow("Style", self.style)
        layout.addLayout(form)

        self.mj_out = QPlainTextEdit()
        self.hf_out = QPlainTextEdit()
        self.meshy_out = QPlainTextEdit()

        layout.addWidget(QLabel("Midjourney prompt"))
        layout.addWidget(self.mj_out)
        layout.addLayout(self._provider_buttons("midjourney", self.mj_out, self._build_midjourney))

        layout.addWidget(QLabel("Higgsfield prompt"))
        layout.addWidget(self.hf_out)
        layout.addLayout(self._provider_buttons("higgsfield", self.hf_out, self._build_higgsfield))

        layout.addWidget(QLabel("Meshy texture prompt"))
        layout.addWidget(self.meshy_out)
        layout.addLayout(self._provider_buttons("meshy", self.meshy_out, self._build_meshy))

        self.hint = QLabel(
            "Pipeline name is for organization only and is not inserted into prompts. "
            "Build fills a prompt from Identity and Style. Edit the text, then Save to persist "
            "it for this pipeline before Run Next."
        )
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    def _provider_buttons(self, provider: str, editor: QPlainTextEdit, build_fn) -> QHBoxLayout:
        row = QHBoxLayout()
        build_btn = QPushButton("Build")
        build_btn.clicked.connect(build_fn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self._save_provider(provider, editor))
        row.addWidget(build_btn)
        row.addWidget(save_btn)
        row.addStretch(1)
        return row

    def set_pipeline_context(self, asset_name: str, metadata: dict | None = None) -> None:
        self.pipeline_name.setText(asset_name or "—")
        meta = metadata or {}
        self.identity.setText(str(meta.get("prompt_identity") or _DEFAULT_IDENTITY))
        self.style.setText(str(meta.get("prompt_style") or _DEFAULT_STYLE))
        self.load_from_metadata(meta)

    def load_from_metadata(self, metadata: dict) -> None:
        if metadata.get("mj_prompt"):
            self.mj_out.setPlainText(str(metadata["mj_prompt"]))
        if metadata.get("hf_prompt"):
            self.hf_out.setPlainText(str(metadata["hf_prompt"]))
        if metadata.get("meshy_texture_prompt"):
            self.meshy_out.setPlainText(str(metadata["meshy_texture_prompt"]))

    def template_vars(self) -> dict[str, str]:
        return {"identity": self.identity.text().strip(), "style": self.style.text().strip()}

    def _build_midjourney(self) -> None:
        vars_ = self.template_vars()
        if not vars_["identity"]:
            return
        mj = load_template("midjourney_character.yaml")
        merged = {**mj.get("defaults", {}), **vars_}
        self.mj_out.setPlainText(mj["template"].format(**merged).replace("\n", " ").strip())

    def _build_higgsfield(self) -> None:
        vars_ = self.template_vars()
        if not vars_["identity"]:
            return
        hf = load_template("higgsfield_character.yaml")
        self.hf_out.setPlainText(
            hf["template"].format(**{**hf.get("defaults", {}), **vars_}).replace("\n", " ").strip()
        )

    def _build_meshy(self) -> None:
        hf = load_template("higgsfield_character.yaml")
        self.meshy_out.setPlainText(
            hf.get("meshy_texture_template", "").format(extra_details="").replace("\n", " ").strip()
        )

    def _save_provider(self, provider: str, editor: QPlainTextEdit) -> None:
        text = editor.toPlainText().strip()
        if not text:
            return
        self.promptSaveRequested.emit(provider, text, self.template_vars())
