FROM node:15 as js_builder

COPY . /opt/src/

RUN cd /opt/src \
 && npm install --include=dev \
 && npm run build \
;

# ---------------


FROM python:3.7 as py_builder
COPY --from=js_builder /opt/src /opt/src
COPY . /opt/src
RUN cd /opt/src/ \
 && python setup.py sdist

# ---------------


FROM python:3.7 as runner

COPY --from=py_builder /opt/src/dist /opt/src/dist
RUN pip install /opt/src/dist/* 

WORKDIR /opt/pypi-frontend/
CMD uvicorn pypi_frontend._develop:app --host 0.0.0.0

