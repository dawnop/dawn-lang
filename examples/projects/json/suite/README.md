# JSONTestSuite (vendored)

`test_parsing/` is vendored from [nst/JSONTestSuite](https://github.com/nst/JSONTestSuite)
(MIT License, see `LICENSE`). Naming convention:

- `y_*` — must be accepted (valid JSON)
- `n_*` — must be rejected (invalid JSON)
- `i_*` — implementation-defined; either result is acceptable

Dawn's parser (`../src/json/`) is run against every file by `JsonSuiteTest`.
