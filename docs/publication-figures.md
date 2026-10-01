# Versioned publication figure editions

`get_publication_presets` discovers source-dated specifications and exact local font availability.
`render_publication_figures` renders a **new display edition from a completed saved study**.
It never reruns a model, bootstrap, cutoff search or significance test. Supported bundles:
prediction (binary, optional DCA, continuous outcome), diagnostic accuracy, Bland–Altman,
and unweighted Cohen's kappa. Other families need separate publication renderers.

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
