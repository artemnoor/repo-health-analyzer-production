# Repository Health Analyzer roadmap

The backend extraction baseline is implemented under `src/repo_health`.

Future work must preserve the frozen score and golden calibration behavior while
improving operational adapters, observability, and optional process/queue
deployment. New analyzers or integrations require a versioned contract, an
adapter boundary, independent tests, and an explicit persistence/API decision.

The durable workflow is:

`explore → plan → improve → implement → verify → review`
