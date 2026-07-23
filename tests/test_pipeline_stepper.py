from asset_assembly_automator.core.state_machine import MESHY_WORKFLOW_STAGE_ORDER, StageId
from asset_assembly_automator.gui.widgets.pipeline_stepper import MeshyWorkflowStepper


def test_meshy_workflow_stage_order_includes_unity_import():
    assert MESHY_WORKFLOW_STAGE_ORDER[-1] == StageId.UNITY_IMPORT


def test_stepper_meshy_complete_unity_pending(qtbot):
    stepper = MeshyWorkflowStepper()
    qtbot.addWidget(stepper)
    stepper.set_stage(StageId.COMPLETE.value)
    unity_idx = len(MESHY_WORKFLOW_STAGE_ORDER) - 1
    assert stepper.labels[unity_idx].text() == "○"
    assert stepper.labels[unity_idx - 1].text() == "✓"


def test_stepper_unity_import_done(qtbot):
    stepper = MeshyWorkflowStepper()
    qtbot.addWidget(stepper)
    stepper.set_stage(StageId.UNITY_IMPORT.value, unity_import_done=True)
    assert all(lbl.text() == "✓" for lbl in stepper.labels)


def test_stepper_concept_image_label(qtbot):
    stepper = MeshyWorkflowStepper()
    qtbot.addWidget(stepper)
    assert stepper.labels[0].toolTip() == "Concept Image"


def test_stepper_unity_import_failed(qtbot):
    stepper = MeshyWorkflowStepper()
    qtbot.addWidget(stepper)
    stepper.set_stage(
        StageId.UNITY_IMPORT.value,
        unity_import_failed=True,
    )
    unity_idx = len(MESHY_WORKFLOW_STAGE_ORDER) - 1
    assert stepper.labels[unity_idx].text() == "!"
    assert stepper.labels[unity_idx - 1].text() == "✓"
