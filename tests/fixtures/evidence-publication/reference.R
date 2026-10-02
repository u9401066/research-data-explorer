# Pure statistical executor: no network, no shell, no generated code.
suppressPackageStartupMessages(library(netmeta))
suppressPackageStartupMessages(library(jsonlite))
stopifnot(as.character(packageVersion("netmeta")) == "3.7.0",
          as.character(packageVersion("meta")) == "8.5.0")
args <- commandArgs(trailingOnly = TRUE)
input <- fromJSON(args[[1]])
o <- input$options
d <- input$rows
stopifnot(nrow(d) >= 2, all(is.finite(d$effect)), all(is.finite(d$se)),
          all(d$se > 0), o$measure %in% c("OR", "RR", "MD"),
          o$model %in% c("common", "random"))
if (o$measure == "MD" && (is.null(o$outcomeUnit) || !nzchar(trimws(o$outcomeUnit)))) stop("MD requires an explicit common outcome unit")
stopifnot(isTRUE(input$review$valid), identical(d$row, input$review$included$row))
# Safe model identities: raw labels can contain colons or any comparison separator.
treatments <- data.frame(code = sprintf("T%03d", seq_along(input$review$treatments)),
                         label = input$review$treatments)
studies <- data.frame(code = sprintf("S%03d", seq_along(unique(d$study_id))),
                      study_id = unique(d$study_id))
d$treatment_code <- treatments$code[match(d$treatment, treatments$label)]
d$comparator_code <- treatments$code[match(d$comparator, treatments$label)]
d$study_code <- studies$code[match(d$study_id, studies$study_id)]
reference_code <- treatments$code[match(o$reference, treatments$label)]
stopifnot(!anyNA(d$treatment_code), !anyNA(d$comparator_code), length(reference_code) == 1, !is.na(reference_code))
label <- function(code) treatments$label[match(code, treatments$code)]
warnings <- character()
json <- function(object, path) write_json(object, path, pretty = TRUE, auto_unbox = TRUE,
                                         digits = NA, na = "null", null = "null")
back <- function(x) if (o$measure == "MD") x else exp(x)
get_model <- function(x, name) x[[paste0(name, ".", o$model)]]
withCallingHandlers({
  # Each direct contrast is its own meta-analysis, with independently estimated REML tau².
  pair_keys <- vapply(seq_len(nrow(d)), function(i) paste(sort(c(d$treatment_code[i], d$comparator_code[i])), collapse = ":"), character(1))
  direct_observations <- list()
  direct <- lapply(unique(pair_keys), function(key) {
    g <- d[pair_keys == key, , drop = FALSE]
    codes <- sort(unique(c(g$treatment_code, g$comparator_code)))
    effects <- ifelse(g$treatment_code == codes[1], g$effect, -g$effect)
    m <- metagen(effects, g$se, studlab = g$study_id, sm = o$measure,
                 common = o$model == "common", random = o$model == "random",
                 method.tau = "REML", method.ci = "z", method.random.ci = "classic", level = o$confidence,
                 level.ma = o$confidence, prediction = FALSE)
    weights <- get_model(m, "w")
    direct_observations[[key]] <<- data.frame(
      pair = key, row = g$row, study_code = g$study_code, study_id = g$study_id,
      treatment_code = codes[1], comparator_code = codes[2],
      treatment = label(codes[1]), comparator = label(codes[2]),
      source_direction_reversed = g$treatment_code != codes[1],
      effect = m$TE, se = m$seTE, lower_effect = m$lower, upper_effect = m$upper,
      estimate = back(m$TE), lower = back(m$lower), upper = back(m$upper), p = m$pval,
      weight = weights, weight_percent = 100 * weights / sum(weights))
    data.frame(pair = key, treatment_code = codes[1], comparator_code = codes[2],
               treatment = label(codes[1]), comparator = label(codes[2]), studies = nrow(g),
               estimate = back(get_model(m, "TE")), lower = back(get_model(m, "lower")),
               upper = back(get_model(m, "upper")), effect = get_model(m, "TE"),
               lower_effect = get_model(m, "lower"), upper_effect = get_model(m, "upper"),
               se = get_model(m, "seTE"), p = get_model(m, "pval"),
               tau2 = if (nrow(g) > 1) m$tau2 else NA_real_,
               I2 = if (nrow(g) > 1) m$I2 else NA_real_)
  })
  direct <- do.call(rbind, direct)
  direct_observations <- do.call(rbind, direct_observations)
  rownames(direct_observations) <- NULL
  write.csv(direct, "pairwise.csv", row.names = FALSE)
  write.csv(direct_observations, "direct-study-effects.csv", row.names = FALSE)
  write.csv(treatments, "treatment-map.csv", row.names = FALSE)
  write.csv(studies, "study-map.csv", row.names = FALSE)
  nodes <- lapply(treatments$code, function(code) {
    g <- d[d$treatment_code == code | d$comparator_code == code, , drop = FALSE]
    list(code = code, label = label(code), studies = length(unique(g$study_id)),
         study_codes = as.list(unique(g$study_code)), rows = as.list(g$row))
  })
  edges <- lapply(unique(pair_keys), function(key) {
    g <- d[pair_keys == key, , drop = FALSE]
    codes <- sort(unique(c(g$treatment_code, g$comparator_code)))
    list(pair = key, treatment_code = codes[1], comparator_code = codes[2],
         studies = length(unique(g$study_id)), study_codes = as.list(unique(g$study_code)),
         rows = as.list(g$row))
  })
  result <- list(contract = "evidence-synthesis-v2", options = o,
                 direction = "row treatment relative to comparator; OR/RR effect and SE are on log scale",
                 treatment_map = treatments, study_map = studies,
                 observations = d, direct_observations = direct_observations,
                 topology = list(nodes = nodes, edges = edges),
                 review = input$review[c("inputRows", "inputHash", "optionsHash", "decisions")],
                 pairwise = direct, study_count = length(unique(d$study_id)),
                 contrast_count = nrow(d), diagnostics = list(), network = NULL)
  if (o$mode == "network") {
    m <- netmeta(TE = effect, seTE = se, treat1 = treatment_code, treat2 = comparator_code,
                 studlab = study_code, data = d, sm = o$measure,
                 common = o$model == "common", random = o$model == "random",
                 reference.group = reference_code, baseline.reference = TRUE,
                 method.tau = "REML", level = o$confidence, level.ma = o$confidence,
                 prediction = FALSE, details.chkmultiarm = TRUE, tol.multiarm.se = 0.001,
                 keeprma = TRUE)
    te <- get_model(m, "TE"); lo <- get_model(m, "lower"); hi <- get_model(m, "upper")
    estimates <- expand.grid(treatment_code = rownames(te), comparator_code = colnames(te), stringsAsFactors = FALSE)
    estimates$treatment <- label(estimates$treatment_code)
    estimates$comparator <- label(estimates$comparator_code)
    estimates$effect <- as.vector(te)
    estimates$se <- as.vector(get_model(m, "seTE"))
    estimates$estimate <- back(estimates$effect)
    estimates$lower_effect <- as.vector(lo); estimates$upper_effect <- as.vector(hi)
    estimates$lower <- back(estimates$lower_effect); estimates$upper <- back(estimates$upper_effect)
    estimates$p <- as.vector(get_model(m, "pval"))
    estimates <- estimates[estimates$treatment != estimates$comparator, ]
    reference <- estimates[estimates$comparator == o$reference, ]
    if (!all(is.finite(reference$effect)) || !all(is.finite(reference$se))) stop("Non-estimable network reference effects")
    result$network <- list(estimates = estimates, reference = reference,
                           tau2 = m$tau^2, I2 = m$I2, Q = m$Q, df = m$df.Q, p = m$pval.Q)
    result$diagnostics <- list(
      global = list(Q = m$Q.inconsistency, df = m$df.Q.inconsistency,
                    p = if (m$df.Q.inconsistency > 0) m$pval.Q.inconsistency else NA_real_,
                    status = if (m$df.Q.inconsistency > 0) "estimated" else "not_estimable"),
      within_design = list(Q = m$Q.heterogeneity, df = m$df.Q.heterogeneity,
                           p = if (m$df.Q.heterogeneity > 0) m$pval.Q.heterogeneity else NA_real_))
    ns <- netsplit(m, method = "Back-calculation", order = treatments$code, sep.trts = " ~ ")
    split_codes <- strsplit(ns$comparison, " ~ ", fixed = TRUE)
    stopifnot(all(lengths(split_codes) == 2))
    local_rows <- lapply(c("direct", "indirect", "compare"), function(kind) {
      values <- ns[[paste0(kind, ".", o$model)]]
      stopifnot(identical(as.character(values$comparison), as.character(ns$comparison)))
      t1 <- vapply(split_codes, `[`, character(1), 1)
      t2 <- vapply(split_codes, `[`, character(1), 2)
      stopifnot(all(t1 %in% treatments$code), all(t2 %in% treatments$code))
      # A direct-minus-indirect difference remains on the analysis scale, never an OR/RR.
      transform <- if (kind == "compare") identity else back
      data.frame(treatment_code = t1, comparator_code = t2,
        treatment = label(t1), comparator = label(t2), component = kind,
        effect = values$TE, se = values$seTE, lower_effect = values$lower, upper_effect = values$upper,
        estimate = transform(values$TE), lower = transform(values$lower), upper = transform(values$upper),
        p = values$p, direct_studies = ns$k, direct_proportion = ns[[paste0("prop.", o$model)]],
        status = ifelse(is.finite(values$TE) & is.finite(values$seTE) &
                          is.finite(values$lower) & is.finite(values$upper), "estimated", "not_estimable"))
    })
    result$diagnostics$local <- list(method = ns$method,
      direct = ns[[paste0("direct.", o$model)]],
      indirect = ns[[paste0("indirect.", o$model)]],
      comparison = ns[[paste0("compare.", o$model)]],
      rows = do.call(rbind, local_rows),
      direct_tau2_policy = "network common between-study variance; not pairwise.csv tau2",
      difference_scale = if (o$measure == "MD") "MD difference in the declared outcome unit" else paste("difference of log", o$measure))
    write.csv(result$diagnostics$local$rows, "direct-indirect-effects.csv", row.names = FALSE)
    write.csv(estimates, "network-estimates.csv", row.names = FALSE)
    write.csv(reference, "reference-estimates.csv", row.names = FALSE)
    writeLines(capture.output(print(ns)), "inconsistency.txt")
    saveRDS(m, "network-model.rds")
  } else {
    # Canonical direct orientation can be opposite to the selected reference.
    r <- direct
    if (r$treatment == o$reference) {
      old <- r$treatment; r$treatment <- r$comparator; r$comparator <- old
      old <- r$treatment_code; r$treatment_code <- r$comparator_code; r$comparator_code <- old
      r$effect <- -r$effect
      old <- r$lower_effect; r$lower_effect <- -r$upper_effect; r$upper_effect <- -old
      r$estimate <- back(r$effect)
      old_lower <- r$lower
      r$lower <- if (o$measure == "MD") -r$upper else 1 / r$upper
      r$upper <- if (o$measure == "MD") -old_lower else 1 / old_lower
    }
    reference <- r
    result$reference <- r
    result$diagnostics <- list(status = "pairwise_only", inconsistency = "not_applicable")
    write.csv(reference, "reference-estimates.csv", row.names = FALSE)
  }
  # Preserve numerical results before rendering. A figure failure is a failed attempt, not a lost result.
  result$warnings <- as.list(unique(warnings))
  json(result, "numeric-result.json")
  if (o$mode == "network") {
    png("network.png", width = 1400, height = 1000, res = 140, type = "cairo")
    par(family = "Noto Sans CJK TC")
    netgraph(m, plastic = FALSE, points = TRUE, number.of.studies = TRUE,
             cex = 1.1, cex.points = 3, thickness = "number.of.studies")
    title(main = "Treatment network", sub = "Treatment identities: treatment-map.csv; edge labels: independent studies")
    dev.off()
  }
  png("forest.png", width = 1400, height = max(700, 110 * nrow(reference)), res = 140, type = "cairo")
  par(mar = c(5, 9, 4, 2), family = "Noto Sans CJK TC")
  y <- seq_len(nrow(reference))
  x <- reference$estimate; lower <- reference$lower; upper <- reference$upper
  if (any(!is.finite(c(x, lower, upper))) || (o$measure != "MD" && any(c(x, lower, upper) <= 0))) stop("Effect scale overflow: cannot render valid confidence limits")
  limits <- range(c(lower, upper, if (o$measure == "MD") 0 else 1))
  if (diff(limits) == 0) limits <- limits + c(-0.1, 0.1)
  plot(x, y, xlim = limits, ylim = c(0.5, nrow(reference) + 0.5), yaxt = "n", pch = 19,
       xlab = paste(o$measure, "relative to", o$reference), ylab = "",
       log = if (o$measure == "MD") "" else "x",
       main = paste(o$model, "effects;", 100 * o$confidence, "% confidence intervals"))
  segments(lower, y, upper, y, lwd = 2, col = "#23766e")
  points(x, y, pch = 19, cex = 1.2, col = "#13443f")
  axis(2, at = y, labels = reference$treatment, las = 1)
  abline(v = if (o$measure == "MD") 0 else 1, lty = 2, col = "grey50")
  dev.off()
  result$warnings <- as.list(unique(warnings))
  json(result, "result.json")
  file.copy("/opt/evidence/packages.csv", "packages.csv")
  writeLines(capture.output(sessionInfo()), "session.txt")
}, warning = function(w) { warnings <<- c(warnings, conditionMessage(w)); invokeRestart("muffleWarning") })
