# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## A/B test a Cursor rule before adding it

- **Context**: When proposing or adding a new Cursor rule in .cursor/rules
- **Problem**: Rules accumulate untested; they add prompt noise and maintenance cost even when the agent already follows the convention without them
- **Rule**: Before adding a Cursor rule, run an A/B test; discard it when the agent already follows the convention without it.
- **Applies to**: implement

## Delete unused code after impl-review, with operator confirmation

- **Context**: applies after implementing last phase and after running 10x-impl-review
- **Problem**: codebase gets cluttered with unused/dead code
- **Rule**: Based on the 10x-impl-review perform a code check to delete unused/dead code paths. Verify with operator first
- **Applies to**: implement, impl-review
