# Public demonstration of simple-repository-browser

This is the configuration for https://simple-repository.app.cern.ch/.

To test locally:

```
docker build .. --file ./Dockerfile --progress=plain -t registry.paas.cern.ch/simple-repository/simple-repository-browser:latest
docker run -p 5000:5000 -it registry.paas.cern.ch/simple-repository/simple-repository-browser:latest
```

To deploy the change:

```
docker push registry.paas.cern.ch/simple-repository/simple-repository-browser:latest
```

(you will need to have authenticated, see https://paas.docs.cern.ch/faq/#how-can-i-access-the-paas-image-registry-from-outside-the-cluster)
