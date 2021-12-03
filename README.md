# pypi-frontend

SHORT DESCRIPTION OF PROJECT

You can use [Github-flavored Markdown](https://guides.github.com/features/mastering-markdown/)
to write your content.

## Purpose of this project
## Getting started
##


```
uvicorn pypi_frontend._app:app --reload

npm install
npm run build
```


## Deployment

On development machine:

```
npm run build

python -m build
```

Then, copy the built wheel to acc-py-repo.cern.ch. On that machine:

```
source /opt/acc-py/base/2020.11/setup.sh
acc-py app deploy /path/to/wheel
```

Promote this new version to pro (once tested), and restart the acc-pypi-frontend service:

```
systemctrl restart acc-pypi-frontend
```



