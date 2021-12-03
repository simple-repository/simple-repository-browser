import logging

from . import _app


logging.basicConfig(level=logging.DEBUG)
app = _app.make_app(index_url='http://acc-py-repo.cern.ch:8000/simple')
