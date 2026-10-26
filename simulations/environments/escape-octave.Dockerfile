FROM gnuoctave/octave:10.3.0@sha256:781eb67884fed0f2ce5c54bc0579bed3b18e3f79af08b6ba68618de696524eb1
USER root
ENTRYPOINT []
LABEL aspa.simulation.owner="simctl" aspa.simulation.candidate="SIM-004"
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends python3-venv \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location --retry 1 \
        https://pub.ista.ac.at/~schloegl/matlab/NaN/nan-3.7.2.tar.gz -o /tmp/nan.tar.gz \
    && echo 'd2d2bac3f1d790428df2f7a396c6a1ffed93e91e29ab13678f641deaf021a216  /tmp/nan.tar.gz' | sha256sum -c - \
    && octave --no-gui --quiet --eval "pkg install -global /tmp/nan.tar.gz" \
    && rm /tmp/nan.tar.gz
