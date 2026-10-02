# Independent reference calculations only; actual research runs use the RDE MCP.
# R stats power.t.test(strict=TRUE) includes both rejection tails.
# Unequal allocation uses R's noncentral-t CDF with pooled degrees of freedom.
# Two proportions: normal pooled-null / unpooled-alternative approximation.
library(jsonlite)
t_power <- function(n1, n2, d, alpha) {
  df <- n1 + n2 - 2
  lambda <- d / sqrt(1/n1 + 1/n2)
  cut <- qt(1-alpha/2, df)
  pt(-cut, df, ncp=lambda) + pt(cut, df, ncp=lambda, lower.tail=FALSE)
}
p_power <- function(n1, n2, p1, p2, alpha) {
  pooled <- (n1*p1+n2*p2)/(n1+n2)
  sd0 <- sqrt(pooled*(1-pooled)*(1/n1+1/n2))
  sda <- sqrt(p1*(1-p1)/n1+p2*(1-p2)/n2)
  cut <- qnorm(1-alpha/2)*sd0
  pnorm((-cut-(p1-p2))/sda) + pnorm((cut-(p1-p2))/sda, lower.tail=FALSE)
}
rows <- list(
  list(design="independent_means", n1=64L, n2=64L, d=.5, alpha=.05,
       power=power.t.test(n=64,delta=.5,sd=1,type="two.sample",sig.level=.05,strict=TRUE)$power),
  list(design="independent_means", n1=80L,n2=40L,d=-.4,alpha=.025,
       power=t_power(80,40,-.4,.025)),
  list(design="paired_means", pairs=34L,d=.5,alpha=.05,
       power=power.t.test(n=34,delta=.5,sd=1,type="paired",sig.level=.05,strict=TRUE)$power),
  list(design="paired_means", pairs=3L,d=.01,alpha=.2,
       power=power.t.test(n=3,delta=.01,sd=1,type="paired",sig.level=.2,strict=TRUE)$power),
  list(design="independent_proportions",n1=120L,n2=240L,p1=.4,p2=.55,alpha=.05,
       power=p_power(120,240,.4,.55,.05)),
  list(design="independent_proportions",n1=240L,n2=120L,p1=.55,p2=.4,alpha=.05,
       power=p_power(240,120,.55,.4,.05))
)
cat(toJSON(list(R=R.version.string,method="R stats, both rejection tails; reference.R",rows=rows),
           auto_unbox=TRUE,pretty=TRUE,digits=17),"\n")
