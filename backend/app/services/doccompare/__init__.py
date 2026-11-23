"""Original-versus-test document comparison.

Pure analysis (`geometry`, `registration`, `pages`, `visual`, `text`, `fusion`, `vision`,
`annotate`, `report`) is orchestrated by `engine.compare`. `service` is the API side and `run`
the worker side. Findings are differences located on the test document, each with its
evidence and a measured confidence; never a verdict on authenticity.
"""
