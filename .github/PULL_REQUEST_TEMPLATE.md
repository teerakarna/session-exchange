## What and why

<!-- What changes, and the reasoning. Link the issue or the migration step if there is one. -->

## Which gate did you break, and what did the failure look like

<!-- Required. See CONTRIBUTING.md: a check has to be able to fail. Paste the failure output from
     deliberately breaking the thing this PR is meant to catch. A new check with no recorded failure
     mode is treated as untested. If this PR adds no check, say so and say why not. -->

## What you ran, as opposed to what CI runs

<!-- Did you use the command? Read the output? The two worst bugs so far both passed the full suite.
     If something could only be checked on one platform or one Python version, say which. -->

## Boundaries touched

<!-- Delete the lines that do not apply, and say how for the ones that do.

     - Root resolution or the cross-root boundary
     - A schema, or anything that writes state
     - Anything that renders into a session's context
     - A hardcoded path, name or environment-specific string (there should be none)
     - The hook handlers, or anything that runs at session start -->

None.
