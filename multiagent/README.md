# TollChat multiagent rewrite

This directory is the exclusive home for TollChat's from-scratch multiagent rewrite, including its code, tests, evals, infrastructure, and documentation.

The existing repository outside `multiagent/` remains the current single-agent implementation and keeps its existing build and deployment behavior. The rewrite has no compatibility or dependency contract with those modules. Reuse code only through an explicit future change that copies or reintroduces the needed behavior here.

Existing multiagent-related documents elsewhere in the repository are reference material until the rewrite deliberately adopts them.
