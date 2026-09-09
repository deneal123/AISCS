# Disposable LaTeX compiler used only through the workspace sidecar.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="GPTHub Document Runtime" \
      org.opencontainers.image.version="1" \
      org.opencontainers.image.description="Network-isolated reproducible LaTeX compiler"

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        biber chktex fontconfig ghostscript latexmk poppler-utils qpdf tar zip \
        texlive-bibtex-extra texlive-fonts-recommended texlive-lang-cyrillic \
        texlive-latex-base texlive-latex-extra texlive-latex-recommended \
        texlive-luatex texlive-pictures texlive-publishers texlive-science texlive-xetex \
    && rm -rf /var/lib/apt/lists/*

COPY docker/document_runner.py /opt/document-runtime/runner.py
COPY docker/generate_document_sbom.py /opt/document-runtime/generate_sbom.py
RUN chmod 0555 /opt/document-runtime/runner.py \
    && python3 /opt/document-runtime/generate_sbom.py \
    && dpkg-query -W -f='${binary:Package}\t${Version}\n' \
        > /tmp/document-packages.tsv \
    && LC_ALL=C sort /tmp/document-packages.tsv > /opt/document-runtime/packages.tsv \
    && fc-list : family style file > /tmp/document-fonts.txt \
    && LC_ALL=C sort /tmp/document-fonts.txt > /opt/document-runtime/fonts.txt \
    && test -s /opt/document-runtime/packages.tsv \
    && test -s /opt/document-runtime/fonts.txt \
    && test -s /opt/document-runtime/sbom.cdx.json \
    && sha256sum /opt/document-runtime/packages.tsv /opt/document-runtime/fonts.txt \
        /opt/document-runtime/sbom.cdx.json > /opt/document-runtime/toolchain.sha256 \
    && rm /tmp/document-packages.tsv /tmp/document-fonts.txt \
    && rm /opt/document-runtime/generate_sbom.py \
    && mkdir -p /job /output /tmp/texmf-var \
    && chown -R 65534:65534 /job /output /tmp/texmf-var \
    && printf 'shell_escape = f\nopenin_any = p\nopenout_any = p\n' >/etc/texmf/texmf.d/99-gpthub.cnf \
    && update-texmf

ENV HOME=/tmp \
    TEXMFVAR=/tmp/texmf-var \
    SOURCE_DATE_EPOCH=1704067200 \
    FORCE_SOURCE_DATE=1 \
    TZ=UTC
USER 65534:65534
WORKDIR /job
ENTRYPOINT ["python3", "/opt/document-runtime/runner.py"]
