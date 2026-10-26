# Parsing and actual startup are different checks. Preserve the latter failure.
.libPaths(c("/work/r-library", .libPaths()))
files <- list.files("R", pattern = "\\.R$", recursive = TRUE, full.names = TRUE)
errors <- character(0)
for (path in files) {
  tryCatch(parse(file = path), error = function(e) {
    errors <<- c(errors, paste(path, conditionMessage(e)))
  })
}
writeLines(c(paste("parsed_files", length(files)), errors), "/work/r-syntax-check.txt")
writeLines(capture.output(sessionInfo()), "/work/r-session.txt")
Sys.setenv(BANC_LIVE = "0", BANC_NCORES = "1")
tryCatch({
  source("R/startup/banc-startup.R")
  source("R/startup/banc-meta.R")
}, error = function(e) {
  writeLines(conditionMessage(e), "/work/r-startup-error.txt")
  stop(e)
})
if (length(errors)) stop("One or more pinned R sources could not be parsed")
