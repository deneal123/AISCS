# Minimal R environment from the pinned README; writes its resolved versions.
dir.create("/work/r-library", showWarnings = FALSE, recursive = TRUE)
.libPaths(c("/work/r-library", .libPaths()))
options(repos = c(CRAN = "https://cloud.r-project.org"), Ncpus = 4, timeout = 180)
Sys.setenv(LIBARROW_BINARY = "true")
tryCatch({
  install.packages("remotes", quiet = TRUE)
  if (!requireNamespace("remotes", quietly = TRUE)) stop("remotes installation failed")
  # Exact upstream commit whose DESCRIPTION first declares bancr 0.3.0.
  remotes::install_github("natverse/bancr", ref = "c4e9f751455a866fa053decdfea4b0d8d7ac84f5",
                          dependencies = NA, upgrade = "never", quiet = FALSE)
  remotes::install_version("arrow", version = "16.1.0", upgrade = "never", quiet = FALSE)
  install.packages(c("readr", "dplyr", "ggplot2", "igraph", "reticulate"))
  wanted <- c("bancr", "arrow", "readr", "dplyr", "ggplot2", "igraph", "reticulate")
  if (!all(vapply(wanted, requireNamespace, logical(1), quietly = TRUE))) {
    stop("Not all minimal README dependencies are available")
  }
}, error = function(e) {
  writeLines(conditionMessage(e), "/work/r-install-error.txt")
  write.csv(installed.packages()[, c("Package", "Version")], "/work/r-dependencies.csv", row.names = FALSE)
  stop(e)
})
write.csv(installed.packages()[, c("Package", "Version")], "/work/r-dependencies.csv", row.names = FALSE)
writeLines(capture.output(sessionInfo()), "/work/r-session.txt")
