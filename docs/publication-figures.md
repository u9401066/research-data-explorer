# Versioned publication figure editions

`get_publication_presets` discovers source-dated specifications and exact local font availability.
`render_publication_figures` renders a **new display edition from a completed saved study**.
It never reruns a model, bootstrap, cutoff search or significance test. Supported bundles:
prediction (binary, optional DCA, continuous outcome), diagnostic accuracy, Bland–Altman,
unweighted Cohen's kappa, survival/competing-event studies, [longitudinal GEE/Gaussian mixed models](longitudinal.md), and [independent-case regression](regression.md). Other families need separate publication renderers.

Pass the project ID, exact `clinical_study_*.json` / `prediction_study_*.json` filename,
its SHA256, a preset ID, a new canonical UUID, optional starting figure number, and optional
caption edits keyed by the original one-based figure index. Editable fields are `title`,
`caption_en` and `explanation_zh`; original captions remain in the receipt.
The source and complete original artifact bundle must verify. A same-ID/same-request replay
verifies and returns saved files; conflicting requests or corrupted receipts/outputs fail.
Rendering is staged, committed as a complete edition under `figures/editions/<UUID>/`,
and logged at report assembly. The locked plan and numerical evidence remain unchanged.

| Preset ID | Width | Typography | Main submission file |
| --- | --- | --- | --- |
| `journal-neutral-english-v1` | 180 mm | DejaVu Sans, original 9–10 pt body | Vector PDF; outlined SVG; 300 dpi PNG/TIFF |
| `nature-single-v1` | 89 mm | Arial, 5–7 pt | Editable vector PDF; editable SVG companion |
| `nature-double-v1` | 183 mm | Arial, 5–7 pt | Same |
| `plos-column-v1` | 132 mm | Arial, 8–12 pt | 600 dpi RGB LZW TIFF |
| `plos-full-v1` | 190.5 mm | Arial, 8–12 pt | Same |

Sources checked **2026-10-01**: [Nature final submission](https://www.nature.com/nature/for-authors/final-submission),
[Nature figure guide](https://www.nature.com/documents/Final_guide_to_authors.pdf),
[PLOS One figures](https://journals.plos.org/plosone/s/figures).
Nature line widths are clamped to 0.25–1 pt; the preset leaves legend room with a 170 mm figure height.
PLOS uses at most 222.3 mm height, 10 MB TIFF and 15 words in a figure title. Captions belong in the
manuscript and file names match figure numbering. These main-article technical presets do not
certify manuscript content, other article types, editorial acceptance or scientific validity.

Set `RDE_PUBLICATION_FONT_DIR` to authorized local Arial font files before starting MCP.
Unavailable families and missing glyphs fail explicitly; no font is downloaded during rendering.
The neutral preset uses bundled DejaVu Sans. Receipts record font hash, rendering version,
dimensions/DPI, original numerical receipt, English caption, Chinese explanation and every output hash.
Each figure includes PDF, SVG, PNG, RGB LZW TIFF, caption Markdown and exact plotted-data CSV.
An edition also contains a human-readable report and integrity-checked JSON receipt.

Review actual images and vector PDF rendering alongside full captions. Mechanical canvas checks
do not detect every overlap or establish clinical interpretation. Figure editions are independent
historical outputs; changing a preset or caption must create a new edition, never rewrite an old one.

## Survival and competing-event figures

The survival renderer uses saved participant counts, KM/Aalen–Johansen points, risk tables,
Cox coefficients and scaled Schoenfeld residuals. It performs no fitting, resampling, smoothing,
cutoff selection or new significance test. Each new bundle includes participant flow, curves,
risk counts, all Cox coefficients and one diagnostic per encoded term when a Cox model exists.
Competing-event curves use a separate figure for each group. Risk tables use at most six time
columns per figure and coefficient plots at most eight rows; every panel has a distinct report
identity, so later panels cannot displace earlier ones in the report index.

- KM captions state Greenwood log–log pointwise intervals, the meaning of censor marks and
  the saved overall log-rank comparison. A mark at a tied event/censor time lies at the
  post-event estimate; its multiplicity stays in the plotted-data CSV. Curves stop at each
  group's last observation. See [lifelines KM intervals](https://lifelines.readthedocs.io/en/latest/fitters/univariate/KaplanMeierFitter.html).
- Risk counts refer to **immediately before** the stated time, including people whose follow-up
  ends at that time. This explicit convention is preserved from the numerical receipt;
  it is not silently changed to a library's end-of-period default. The tables retain prior
  target events, competing events and censoring separately. See [lifelines risk-count conventions](https://lifelines.readthedocs.io/en/latest/lifelines.plotting.html).
- Aalen–Johansen figures retain tied times, every declared cause and bounded pointwise normal
  intervals. No-event groups are labelled as having no estimated uncertainty. A plotted
  pre-event origin is labelled separately from stored estimates in the CSV. There is no
  new Gray test, Fine–Gray fit or interpretation of competing events as ordinary loss to follow-up.
  See [statsmodels cumulative incidence](https://www.statsmodels.org/stable/generated/statsmodels.duration.survfunc.CumIncidenceRight.html).
- Cox plots use a log axis, HR=1 reference and every saved Wald interval. Units, categorical
  references and the cause-specific interpretation stay explicit. PH panels retain each event's
  scaled residual and report the saved rank/KM checks with within-model Holm adjustment;
  a flat plot or large p value does not prove PH. [Cox model documentation](https://lifelines.readthedocs.io/en/latest/Survival%20Regression.html).

Figures use English labels with exact source mappings in captions and CSVs. Group codes G1…
are stable within a study. Long or non-ASCII covariate labels use V codes; common Chinese time
unit names have explicit English display translations without numerical conversion, while
unrecognized unit text uses U1 with its original value recorded. Covariate units are not inferred
from a column name or the follow-up unit. Local dictionary/display-label editing remains a
separate extension.

New survival sensitivity branches export the same six formats, identify their exploratory
scope, and keep the primary complete-case population. Their full reports show one image per
figure and separate captions; the Workbench exploration summary embeds one browser-readable
format per figure while retaining every original download. `render_branch_publication` now
accepts the exact native `br_*` / `exp_*` identity and the branch analysis record's SHA256.
It checks the completed execution wrapper, both experiment ledgers, complete original
primary/branch artifacts, numerical receipts and fixed-case binding before rendering.
The full source closure is checked again before committing a new edition. Source changes
also block same-ID recovery; incomplete, manual-only and unsupported generic branches
cannot stand in for an executed survival study.

Editions record the native run, branch, experiment and primary binding. The report and
every caption retain the exploratory adjustment-sensitivity limitation, including when
caption text is edited. Rendering neither changes the primary plan nor adopts/promotes a
branch. Workbench displays the current keep/discard/pending decision independently and
connects the edition to that exact branch in the research graph.

Legacy general exploration still needs typed saved numerical/plot-data bundles before
it can use this flow; this addition does not claim all generic branches are publication-ready.
Historical PNG-only studies and reports remain unchanged.
