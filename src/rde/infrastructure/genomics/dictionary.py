"""Source-specific display meanings never alter joins, gene membership or R values."""

from rde.infrastructure.prediction.splits import digest
from rde.infrastructure.visualization.dictionary import (
    DisplayDictionary,
    validate_dictionary_entries,
    validate_dictionary_header,
)

from .contract import require

ROLES = ("counts", "sample_metadata", "gene_sets")


def validate_genomics_dictionary(value, record, result):
    require(
        isinstance(value, dict)
        and set(value) == {"schema", "basis", "dictionary_sha256", "dictionaries"}
        and value["schema"] == "publication-genomics-dictionary-v1",
        "Genomics requires complete, separately bound source dictionaries.",
    )
    sources = result["source"]["source"]
    roles = [role for role in ROLES if role in sources]
    items = value["dictionaries"]
    require(
        isinstance(items, list)
        and len(items) == len(roles)
        and all(
            isinstance(item, dict) and set(item) == {"role", "dataset_id", "dictionary"}
            for item in items
        )
        and [item["role"] for item in items] == roles,
        "Every approved source role must appear exactly once in its original order.",
    )
    options = result["analysis"]["options"]
    shared_samples, shared_genes = {}, {}
    entry_count = 0

    def meaning(mapping, code, label):
        require(
            code not in mapping or mapping[code] == label,
            "One original sample or gene has conflicting meanings across source dictionaries.",
        )
        mapping[code] = label

    for item in items:
        role, dictionary = item["role"], item["dictionary"]
        source = sources[role]
        require(item["dataset_id"] == source["dataset_id"], "Dictionary dataset role differs.")
        entries = validate_dictionary_header(dictionary, source, allow_empty=True)
        require(dictionary["basis"] == value["basis"], "Source dictionary review bases differ.")
        if value["basis"]["kind"] == "approved_plan":
            require(
                value["basis"]["plan_id"] == result["source"]["identity"]["plan_id"],
                "Genomics dictionary belongs to another approved plan.",
            )
        table = record["dictionary_source_tables"][role]
        if role == "counts":
            columns = set(table["columns"])
            units = {c: "counts" for c in columns if c != options["geneIdColumn"]}
        elif role == "sample_metadata":
            columns = {
                options["sampleIdColumn"],
                options["conditionColumn"],
                *options["numericCovariates"],
                *[options[k] for k in ("batchColumn", "subjectColumn") if options.get(k)],
            }
            # Numeric-covariate units were not declared in the original R contract.
            units = {}
        else:
            columns, units = {"set_id", "gene_id"}, {}
        validate_dictionary_entries(entries, columns, units)
        for entry in entries:
            column = entry["column"]
            identifiers = (
                role == "gene_sets"
                or (role == "counts" and column == options["geneIdColumn"])
                or (role == "sample_metadata" and column not in options["numericCovariates"])
            )
            require(not identifiers or "unit" not in entry, "Identifiers have no physical unit.")
            if role == "counts" and column != options["geneIdColumn"]:
                require(not entry["levels"], "Raw count values cannot be relabeled as categories.")
                if entry.get("label_en"):
                    meaning(shared_samples, column, entry["label_en"])
            index = table["columns"].index(column)
            original = {row[index] for row in table["rows"]} if entry["levels"] else set()
            for level in entry["levels"]:
                code, label = level["value"], level["label_en"]
                require(
                    code in original, "Dictionary code is absent from its complete pinned source."
                )
                if role == "sample_metadata" and column == options["sampleIdColumn"]:
                    meaning(shared_samples, code, label)
                if (role == "counts" and column == options["geneIdColumn"]) or (
                    role == "gene_sets" and column == "gene_id"
                ):
                    meaning(shared_genes, code, label)
        entry_count += len(entries)
    require(entry_count > 0, "No reviewed English annotations in these source dictionaries.")
    expected = digest(
        [
            [item["role"], item["dataset_id"], item["dictionary"]["dictionary_sha256"]]
            for item in items
        ]
    )
    require(value["dictionary_sha256"] == expected, "Combined dictionary fingerprint differs.")
    return value


class GenomicsDisplayDictionary:
    def __init__(self, value, options):
        self.value, self.options = value, options
        self.sources = {
            item["role"]: DisplayDictionary(item["dictionary"])
            for item in (value or {}).get("dictionaries", [])
        }

    def source(self, role):
        return self.sources.get(role, DisplayDictionary())

    def sample(self, sample_id):
        label = self.source("sample_metadata").level(self.options["sampleIdColumn"], sample_id)
        return self.source("counts").label(sample_id, label)

    def condition(self, condition):
        return self.source("sample_metadata").level(self.options["conditionColumn"], condition)

    def gene_set(self, set_id):
        return self.source("gene_sets").level("set_id", set_id)

    def captions(self):
        if not self.value:
            return ()
        mappings = "".join(
            f"Source role {role!r}. "
            + dictionary.describe(column, [v["value"] for v in entry["levels"]])
            for role, dictionary in self.sources.items()
            for column, entry in dictionary.entries.items()
        )
        return (
            next(iter(self.sources.values())).note(),
            mappings,
            "Dictionary meanings annotate separately pinned counts, sample metadata and any approved gene-set source. "
            "Original sample joins, gene IDs and namespace, numerator/reference direction, design, count scale, "
            "filtering, BH testing families, set membership and background universe remain fixed. "
            "Reviewed names do not merge genes, equate samples, translate gene namespaces or verify biological identity. "
            "Numeric-covariate units are researcher annotations, not independently established by the original R contract. "
            "Unannotated identities retain their original meaning; a partial label mapping is not a complete gene annotation. ",
        )
