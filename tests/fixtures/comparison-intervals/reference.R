# Independent R numerical references for synthetic comparison fixtures.
# RR uses direct likelihood optimization, not Python's constrained quadratic.
# OR enumerates the fixed-margin distribution and solves in log-odds space.
library(jsonlite)
confidence <- 0.95
alpha <- 1-confidence
pack <- function(x) list(value=if(is.finite(x)) unname(x) else NULL,
                        status=if(is.na(x)) "undefined" else if(is.infinite(x)) "positive_infinity" else "finite")
wilson <- function(a,n) {
  z <- qnorm(1-alpha/2); p <- a/n
  center <- (p+z*z/(2*n))/(1+z*z/n)
  half <- z*sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
  c(center-half,center+half)
}
rr_score <- function(eta,a,n1,c,n0) {
  ratio <- exp(eta); upper <- min(1,1/ratio)
  likelihood <- function(u) dbinom(a,n1,min(1,ratio*upper*u),log=TRUE)+dbinom(c,n0,upper*u,log=TRUE)
  fitted <- optimize(likelihood,c(0,1),maximum=TRUE,tol=1e-13)
  candidates <- c(0,fitted$maximum,1)
  q <- upper*candidates[which.max(vapply(candidates,likelihood,0))]
  p <- min(1,ratio*q)
  numerator <- a/n1-ratio*c/n0
  variance <- (p*(1-p)/n1+ratio*ratio*q*(1-q)/n0)*(n1+n0)/(n1+n0-1)
  if(variance==0) return(if(numerator==0) 0 else Inf)
  numerator*numerator/variance
}
ratio_ci <- function(a,n1,c,n0) {
  if(a==0 && c==0) return(c(0,Inf))
  center <- if(a==0) -30 else if(c==0) 30 else log((a/n1)/(c/n0))
  f <- function(eta) rr_score(eta,a,n1,c,n0)-qchisq(confidence,1)
  lower <- if(a==0) 0 else exp(uniroot(f,c(-30,center),tol=1e-11)$root)
  upper <- if(c==0) Inf else exp(uniroot(f,c(center,30),tol=1e-11)$root)
  c(lower,upper)
}
conditional_or <- function(a,n1,c,n0) {
  events <- a+c; support <- max(0,events-n0):min(n1,events)
  if(length(support)==1) return(list(estimate=pack(NA_real_),lower=pack(0),upper=pack(Inf)))
  probs <- function(eta) {
    logw <- lchoose(n1,support)+lchoose(n0,events-support)+support*eta
    weights <- exp(logw-max(logw)); weights/sum(weights)
  }
  estimate <- if(a==min(support)) 0 else if(a==max(support)) Inf else exp(uniroot(function(eta) sum(support*probs(eta))-a,c(-40,40),tol=1e-12)$root)
  lower <- if(a==min(support)) 0 else exp(uniroot(function(eta) sum(probs(eta)[support>=a])-alpha/2,c(-40,40),tol=1e-12)$root)
  upper <- if(a==max(support)) Inf else exp(uniroot(function(eta) sum(probs(eta)[support<=a])-alpha/2,c(-40,40),tol=1e-12)$root)
  list(estimate=pack(estimate),lower=pack(lower),upper=pack(upper))
}
cases <- list(c(8,10,1,6),c(0,10,2,10),c(2,10,0,10),c(0,10,0,10),c(10,10,10,10),c(10,10,2,10),c(1,100,4,13),c(9,13,2,100))
results <- lapply(cases,function(v) {
  a<-v[1];n1<-v[2];c<-v[3];n0<-v[4]
  p1<-a/n1;p0<-c/n0;d<-p1-p0
  ci1<-wilson(a,n1);ci0<-wilson(c,n0)
  rd<-c(d-sqrt((p1-ci1[1])^2+(ci0[2]-p0)^2),d+sqrt((ci1[2]-p1)^2+(p0-ci0[1])^2))
  rr<-ratio_ci(a,n1,c,n0)
  list(counts=unname(v),proportion_difference=as.list(rd),proportion_ratio=list(lower=pack(rr[1]),upper=pack(rr[2])),odds_ratio=conditional_or(a,n1,c,n0),fisher_p=fisher.test(matrix(c(a,n1-a,c,n0-c),2,byrow=TRUE))$p.value)
})
welch <- t.test(c(1,3,6,7,8),c(1,1,2,2,2,3,5,15,20),var.equal=FALSE,conf.level=.99)
cat(toJSON(list(r_version=R.version.string,confidence=confidence,cases=results,welch=list(p=unname(welch$p.value),df=unname(welch$parameter),ci=unname(welch$conf.int))),auto_unbox=TRUE,digits=17,pretty=TRUE))
