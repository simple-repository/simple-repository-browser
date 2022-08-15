FROM registry.cern.ch/acc/acc-py_cc7_ci:2021.12 as builder

# The build context of this Dockerfile MUST have a directory called ``.wheel-to-deploy/`` containing the single wheel
# that should be deployed with ``acc-py deploy``, and MAY contain a directory called ``./extra-wheels`` which can be a
# source of wheels that aren't yet published on the acc-py index.
COPY . /tmp/context/
ENV PIP_FIND_LINKS=file:///tmp/context/extra-wheels/
RUN acc-py -vv app deploy --deploy-base=/opt/apps/ /tmp/context/.wheel-to-deploy/*.whl


FROM registry.cern.ch/acc/acc-py_cc7:2021.12

COPY --from=builder /opt/apps/ /opt/apps/

CMD [ "/opt/apps/*/latest/exec/default-executable" ]
