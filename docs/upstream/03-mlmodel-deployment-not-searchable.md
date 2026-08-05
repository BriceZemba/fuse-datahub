# Issue draft - `MLMODEL_DEPLOYMENT` is not a valid `EntityType`

**Repository:** `datahub-project/datahub`
**Type:** bug or documentation gap

---

**Title:** `searchAcrossEntities` rejects `MLMODEL_DEPLOYMENT`, so deployments cannot be searched

### Environment

- DataHub OSS `v1.5.0.6` (quickstart)
- GraphQL at `POST /api/graphql`

### What happens

`mlModelDeployment` entities can be created and read, but the type cannot be used in a
search:

```bash
curl -s -X POST http://localhost:8080/api/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ searchAcrossEntities(input:{query:\"*\",count:50,start:0,types:[MLFEATURE,MLFEATURE_TABLE,MLMODEL,MLMODEL_GROUP,MLMODEL_DEPLOYMENT]}) { total } }"}'
```

```
Validation error (WrongType@[searchAcrossEntities]) : argument 'input.types[4]' with
value 'EnumValue{name='MLMODEL_DEPLOYMENT'}' is not a valid 'EntityType' - Literal value
not in allowable values for enum 'EntityType'
```

The first four types are accepted; only the deployment is rejected. The entity itself is
real - `MLModelProperties.deployments` references it, and `datahub get` returns its
`mlModelDeploymentProperties`.

Note the failure mode: one invalid member fails **the entire query**, so a caller
enumerating ML types gets nothing rather than partial results.

### Expected

Either `MLMODEL_DEPLOYMENT` is added to the `EntityType` enum, or the documentation
states that deployments are not independently searchable and must be reached through
`MLModelProperties.deployments`.

### Why it matters

The deployment is the entity that answers "is this model actually serving traffic?" -
the one that matters most when judging the blast radius of an upstream change. Reaching
it only via a model's properties means you must already know the model.

### Workaround

Omit the type from the search and read `MLModelProperties.deployments` on each model.
