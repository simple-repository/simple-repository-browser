# IF FROM SOURCE:

#FROM python:3.11.0-alpine as build
#
#COPY . /opt/src
#RUN export PIP_TRUSTED_HOST=acc-py-repo.cern.ch \
# && export PIP_INDEX_URL=https://acc-py-repo.cern.ch/repository/vr-py-releases/simple \
# && python -m pip install build \
# && export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_SIMPLE_REPOSITORY_BROWSER=0.5.0post1 \
# && python -m build --wheel /opt/src -o /opt/dist/ \
#;
#
#FROM python:3.11.0-alpine
#
#COPY --from=build /opt/dist /opt/dist
#
#RUN PIP_TRUSTED_HOST=acc-py-repo.cern.ch \
#    PIP_INDEX_URL=https://acc-py-repo.cern.ch/repository/vr-py-releases/simple \
#    python -m pip install \
#        --no-cache \
#        /opt/dist/*.whl \
#;


# ELSEIF

FROM python:3.11.0-alpine

RUN pip install simple-repository-browser \
;

# ENDIF

COPY ./public/templates /opt/simple-repository-browser/templates

# TODO: Warm up the cache.

ENV XDG_CACHE_DIR=/cache

# Make the cache directory. Note that in OpenShift, this is mounted anyway.
RUN mkdir -p $XDG_CACHE_DIR \
 && chmod a+wr $XDG_CACHE_DIR \
;
CMD simple-repository-browser \
    --no-popular-project-crawl \
    --port 5000 \
    --templates-dir /opt/simple-repository-browser/templates \
;
