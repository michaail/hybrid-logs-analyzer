# MVP Draft — Productionizing a Log Anomaly Detection System

## Context

This is an existing brownfield project developed as part of my master's thesis.

The system focuses on anomaly detection in HDFS system logs from the LogHub

dataset. The current implementation consists mainly of Jupyter Notebooks.

The notebooks contain data preparation, transformations and feature

engineering, model training, evaluation, and exploratory analysis of

anomaly detection results.

The current pipeline can be used in a research or development environment,

but it is not yet a repeatable production-oriented workflow for end users.

Running it requires knowledge of the notebook structure, execution order,

local environment setup, and implicit assumptions between notebook cells.

## Problem

A technical user cannot independently and repeatably train, validate,

publish, and reuse an anomaly detection model without manually running

notebooks and understanding their internal execution order.

The current solution does not provide a consistent way to:

- run the pipeline as an application workflow;

- track progress and intermediate results;

- validate the quality of data transformations and training;

- store model versions, configurations, and evaluation metrics;

- explicitly publish a validated model for later use;

- run anomaly analysis on new logs;

- isolate data, models, and results between projects or tenants.

## Main User

The primary user is a technical operations-oriented user, such as an

SRE, DevOps Engineer, or system analyst responsible for investigating

unusual behavior in system logs after incidents, deployments, or

operational changes.

The user can provide or select input log data and interpret technical

results, but should not need to understand notebook internals or modify

the machine learning code to perform a standard training or analysis run.

## MVP Goal

Convert the verified notebook-based pipeline into a repeatable,

production-oriented workflow that allows an authorized user to train,

evaluate, register, publish, and use anomaly detection models.

The first end-to-end workflow should be:

1. The user starts a training pipeline using HDFS logs from LogHub.

2. The system validates the input data.

3. The system runs the pipeline asynchronously.

4. The user can observe progress, step statuses, and selected intermediate

   outputs required to validate the process.

5. The system stores the final model artifact, training configuration,

   data reference, and evaluation metrics.

6. The system registers the resulting model as a versioned model.

7. An authorized user explicitly publishes a selected successful model.

8. The user starts a test or evaluation run with new log data and a

   published model.

9. The system presents detected anomalies, anomaly scores or anomaly levels,

   the decision threshold, relevant log context, and the exact model version

   used for the analysis.

## MVP Scope

### Input data

- The MVP supports one defined input format only: HDFS logs from the

  LogHub dataset.

- The system validates input structure before processing.

- Invalid files or malformed records produce a clear validation result

  and do not silently continue through the pipeline.

### Production pipeline

- The training and evaluation pipeline is executed outside Jupyter Notebooks

  as a repeatable application or worker process.

- The pipeline runs asynchronously.

- Each pipeline run has a unique identifier, status, timestamps,

  configuration, and error information when applicable.

- The user can observe progress and the status of individual pipeline steps.

- The system stores selected intermediate results needed to validate

  preprocessing, transformations, training, and evaluation.

- The notebook implementation remains available for research, exploration,

  experimentation, and comparison of results.

### Model registry

- The system stores versioned trained models in a model registry.

- A model version includes at least:

  - unique identifier;

  - project or tenant ownership;

  - model version;

  - status;

  - training configuration;

  - source data reference;

  - pipeline version or code version;

  - evaluation metrics;

  - creation timestamp;

  - reference to the model artifact.

- Example model statuses may include:

  `training`, `ready`, `failed`, `published`, and `archived`.

### Explicit publishing

- A model can be published only after a successful training and evaluation run.

- Publishing is an explicit action performed by an authorized user.

- Only published models can be used for standard analysis runs.

- The system records who published a model, when it was published,

  and which model version was published.

### Test and evaluation runs

- The user can start a test or evaluation run on a selected input log dataset.

- The user can choose a published model available within the same project

  or tenant.

- An analysis run has its own identifier, status, timestamps, input data

  reference, selected model version, and error information when applicable.

### Results presentation

- The system presents a list of detected anomalies.

- Each anomaly result includes:

  - the relevant log record or record identifier;

  - anomaly score or anomaly level;

  - the decision threshold;

  - contextual log information;

  - the model identifier and exact model version used;

  - the analysis run identifier.

- The user should be able to distinguish anomalous records from normal,

  rejected, or invalid records.

### Isolation and security

- Input data, models, model artifacts, pipeline runs, analysis runs,

  and results are isolated per project or tenant.

- The system provides authentication and authorization.

- Only authorized users can start training, publish models, or access

  data and models belonging to a given project or tenant.

- Significant actions, especially model publication and run execution,

  are recorded in an audit log.

### Production baseline

- Authentication and authorization.

- Per-project or per-tenant data isolation.

- Input validation.

- Clear error handling and terminal run statuses.

- Operational logging and audit logging.

- Automated tests for the critical workflow:

  training → evaluation → model registration → publication →

  analysis run → result presentation.

## Business Rule

A model can be published and used for log analysis only if it was created

by a successful repeatable pipeline run, has stored evaluation metrics,

was explicitly published by an authorized user, and belongs to the same

project or tenant as the analyzed log data.

## Constraints and Preserved Behavior

- The existing anomaly detection logic, data preparation approach, and

  evaluation logic implemented and validated in the notebooks are the

  starting point for the MVP.

- For the same dataset and configuration, the production-oriented pipeline

  should reproduce the agreed notebook results within a defined numerical

  tolerance.

- Notebooks remain available as an R&D and exploratory environment.

- Standard training, evaluation, model publication, and log analysis must

  not require manual notebook execution.

- A standard user run must not require manual code edits, manual state

  preparation, or direct database/file-system modifications.

- The MVP supports HDFS logs from LogHub only.

## Non-Goals

The following are explicitly outside the MVP scope:

- Real-time log streaming and continuous anomaly detection.

- Automatic or scheduled model retraining.

- Automated hyperparameter optimization.

- Automatic model selection or multi-model experiments.

- A/B testing of models.

- Advanced MLOps platform capabilities, such as feature stores,

  full experiment-tracking infrastructure, or production model monitoring.

- Advanced alerting and integrations with PagerDuty, Slack, SIEM,

  Elasticsearch, OpenSearch, or ticketing systems.

- Support for multiple log formats beyond HDFS logs from LogHub.

- Automated root-cause analysis, remediation recommendations, or

  advanced explainability beyond anomaly score, threshold, and log context.

- Replacing Jupyter Notebooks as an R&D environment.