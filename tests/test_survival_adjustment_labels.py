"""Adjustment describes source predictors, never the number of encoded terms."""

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from rde.infrastructure.clinical import report, survival_publication
from rde.infrastructure.clinical.survival import run_survival
from test_clinical_survival import cox_frame, spec


@pytest.mark.parametrize("adjusted", [False, True])
@pytest.mark.parametrize("competing", [False, True])
def test_one_multilevel_factor_remains_unadjusted_in_report_axis_and_real_caption(
    tmp_path, monkeypatch, adjusted, competing
):
    frame = cox_frame()
    frame["group"] = np.array(["control", "treated", "third"])[np.arange(len(frame)) % 3]
    if competing:
        frame.loc[(frame.index % 9 == 0) & (frame.status == "D"), "status"] = "T"
    options = spec(
        group="group",
        covariates=["group", "x"] if adjusted else ["group"],
        categorical_covariates=["group"],
        references={"group": "control"},
        competing_values=["T"] if competing else [],
        risk_times=[0, 10],
    )
    result = run_survival(frame, options)
    saved = deepcopy(result)
    assert len(result["cox"]["coefficients"]) == (3 if adjusted else 2)
    rendered_labels = []
    save = survival_publication.save_publication_figure

    def record_axis(fig, *args, **kwargs):
        if "hazard ratios" in kwargs["title"]:
            rendered_labels.append(fig.axes[0].get_xlabel())
        return save(fig, *args, **kwargs)

    monkeypatch.setattr(survival_publication, "save_publication_figure", record_axis)
    text = report.markdown(result)
    figures = survival_publication.figures(result, tmp_path, "adjustment")
    cox = next(f for f in figures if f["plot_type"] == "clinical_cox_1")
    label = "Adjusted" if adjusted else "Unadjusted"
    assert rendered_labels == [
        f"{label} {'cause-specific ' if competing else ''}HR (95.0% CI; log scale)"
    ]
    caption = Path(cox["publication"]["files"]["caption"]).read_text()
    assert f"{label} hazard ratios for the target event." in caption
    assert Path(cox["path"]).is_file()
    assert not cox["publication"]["text_outside_canvas"]
    if adjusted:
        assert "mutually adjusted for the 2 prespecified source predictors" in caption
        assert "調整其他因素後的瞬時事件率" in text
        assert "每個 HR 都在其他已納入因素相同的條件下解讀" in text
    else:
        assert "This univariable model contains one source predictor" in caption
        assert "未調整其他因素" in caption and "多個編碼係數" in caption
        assert "單一因素的瞬時事件率（未調整 Cox regression）" in text
        assert "調整其他因素後的瞬時事件率" not in text
        assert "每個 HR 都在其他已納入因素相同的條件下解讀" not in text
    assert result == saved
