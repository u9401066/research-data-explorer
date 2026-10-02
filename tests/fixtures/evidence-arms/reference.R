# Independent meta/netmeta validation of the synthetic raw arm fixture.
# No clinical data or platform-derived arm contributions are used as inputs.
suppressPackageStartupMessages(library(meta))
suppressPackageStartupMessages(library(netmeta))
suppressPackageStartupMessages(library(jsonlite))
raw <- read.csv("/fixtures/source.csv", skip = 1, stringsAsFactors = FALSE)
raw <- raw[raw$drug != "X" & raw$study %in% c("s1", "s2"), ]
raw$events <- as.numeric(raw$events)
raw$total <- as.numeric(raw$total)
merged <- aggregate(cbind(events, total) ~ study + drug, data = raw, FUN = sum)
results <- list()
for (measure in c("OR", "RR")) {
  rows <- list()
  for (study in sort(unique(merged$study))) {
    arms <- merged[merged$study == study, ]
    arms <- arms[order(arms$drug), ]
    # Explicit study-wide policy, not meta's default per-pair correction.
    if (any(arms$events == 0 | arms$events == arms$total)) {
      arms$events <- arms$events + 0.5
      arms$total <- arms$total + 1
    }
    pairs <- combn(seq_len(nrow(arms)), 2)
    for (i in seq_len(ncol(pairs))) {
      a <- arms[pairs[1, i], ]; b <- arms[pairs[2, i], ]
      fit <- metabin(a$events, a$total, b$events, b$total,
        sm = measure, method = "Inverse", incr = 0, allstudies = TRUE,
        common = TRUE, random = FALSE)
      rows[[length(rows) + 1]] <- data.frame(study_id = study,
        treatment = a$drug, comparator = b$drug,
        effect = fit$TE, se = fit$seTE)
    }
  }
  contrasts <- do.call(rbind, rows)
  # Also exercise netmeta's shared-arm consistency validation on all three pairs.
  network <- netmeta(TE = effect, seTE = se, treat1 = treatment,
    treat2 = comparator, studlab = study_id, data = contrasts,
    sm = measure, reference.group = "B", common = TRUE, random = FALSE)
  stopifnot(network$n == 3L, network$k == 2L)
  results[[measure]] <- contrasts
}
cat(toJSON(list(versions = list(R = as.character(getRversion()),
  meta = as.character(packageVersion("meta")), netmeta = as.character(packageVersion("netmeta"))),
  results = results), auto_unbox = TRUE, digits = 17))
