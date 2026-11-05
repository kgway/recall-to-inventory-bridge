# SPDX-License-Identifier: MPL-2.0
# Load the contest EAP image locally first. Never push this image publicly.
ARG IRIS_IMAGE=recall-guard-aihub:2027.1.0AI.109.0
FROM ${IRIS_IMAGE}

USER root
WORKDIR /opt/recall-guard
RUN chown irisowner:irisowner /opt/recall-guard
COPY --chown=irisowner:irisowner python /opt/recall-guard/python
COPY --chown=irisowner:irisowner src /opt/recall-guard/src
COPY --chown=irisowner:irisowner fixtures /opt/recall-guard/fixtures
COPY --chown=irisowner:irisowner research/evidence /opt/recall-guard/research/evidence
COPY --chown=irisowner:irisowner web /opt/recall-guard/web
COPY --chown=irisowner:irisowner docker /opt/recall-guard/docker
ENV PYTHONPATH=/opt/recall-guard/python:/usr/irissys/lib/python:/usr/irissys/mgr/python
USER irisowner
RUN iris start IRIS && \
    iris merge IRIS /opt/recall-guard/docker/merge.cpf && \
    iris session IRIS -U RECALLGUARD < /opt/recall-guard/docker/install.script && \
    iris stop IRIS quietly
