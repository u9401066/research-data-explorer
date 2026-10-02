# Independent base-R references; source data are the pinned Orthodont wide pivot.
# No Python engine implementation is called. Conditional signed-rank probabilities
# use polynomial convolution, rounded back to exact integer sign-assignment counts.
library(jsonlite)
args <- commandArgs(trailingOnly=TRUE)
exact_signed <- function(d) {
  d <- d[d != 0]
  if (!length(d)) return(list(p=NULL, rank_biserial=NULL))
  r <- rank(abs(d), ties.method="average")
  coeff <- 1
  for (weight in as.integer(2*r)) {
    factor <- c(1, rep(0, weight-1), 1)
    coeff <- round(convolve(coeff, rev(factor), type="open"))
  }
  stopifnot(all(coeff >= 0), sum(coeff) == 2^length(d))
  smaller <- min(sum(r[d>0]), sum(r[d<0]))
  list(p=min(1, 2*sum(coeff[seq_len(as.integer(2*smaller)+1)])/2^length(d)),
       rank_biserial=sum(sign(d)*r)/sum(r))
}
paired <- function(a, b, confidence=0.95) {
  fit <- t.test(a, b, paired=TRUE, conf.level=confidence)
  list(mean=unname(fit$estimate), statistic=unname(fit$statistic),
       df=unname(fit$parameter), p=fit$p.value, ci=unname(fit$conf.int))
}
out <- list(r_version=R.version.string,
  paired=paired(c(3,5,7,9,11,14,15), c(2,4,9,7,12,10,11), 0.99),
  signs=lapply(list(c(0,2,-2,3,-4), c(1,1,-1,2,-2,3,0,0), 1:5), exact_signed))
if (length(args)) {
  x <- read.csv(args[[1]], check.names=FALSE)
  columns <- paste0("distance_age", c(8,10,12,14))
  stopifnot(nrow(x)==27, !anyNA(x), !anyDuplicated(x$study_code))
  pairs <- lapply(columns[-1], function(name) list(
    first=name, second=columns[[1]], paired=paired(x[[name]], x[[columns[[1]]]]),
    signed=exact_signed(x[[name]] - x[[columns[[1]]]])))
  fit <- friedman.test(as.matrix(x[columns]))
  out$orthodont <- list(n=nrow(x), contrasts=pairs,
    friedman=list(statistic=unname(fit$statistic), p=fit$p.value,
                  kendall_w=unname(fit$statistic)/(nrow(x)*(length(columns)-1))))
}
cat(toJSON(out, auto_unbox=TRUE, digits=17, pretty=TRUE, null="null"))
