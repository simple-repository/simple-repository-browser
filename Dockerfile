FROM node:15 as js_builder

COPY . /opt/src/

RUN cd /opt/src \
 && npm install --include=dev \
 && npm run build \
;

# ---------------


FROM python:3.11 as py_builder
COPY --from=js_builder /opt/src /opt/src
COPY . /opt/src
RUN cd /opt/src/ \
 && python setup.py sdist

# ---------------


FROM python:3.11 as runner

COPY --from=py_builder /opt/src/dist /opt/src/dist
RUN pip install /opt/src/dist/*

WORKDIR /opt/pypi-frontend/
CMD uvicorn simple_repository_browser._develop:app --host 0.0.0.0
