# Preface

This document contains guidelines and BKMs for writing tests. Following these
will significantly reduce number of comments you will receive on the code
review and will speed up the process of merging your patch.

# Tests structure

- All the tests reside in the `tests/` directory, which contains
  subdirectories corresponding to individual test groups.
- Test group directories contain tests that belong to particular groups. Each
  test should belong to exactly one test group.
- Each test should be placed in a separate file (although a test may comprise
  multiple test cases).

# Test file

- A test file corresponds to an individual test.
- Test file name should be preceded with a `test_` prefix, which allows pytest
  to collect it using standard test discovery method.
- Each test file should contain one or more test cases.
- Each test case is a function with its name preceded with `test_` prefix.
- A test file can also contain other functions, classes etc. used by the test
  cases.

# Test case

A test case is a single function. There are four fundamental elements of each
test function:
1. Function name
2. Docstring
3. Pytest marks
4. Testing code

Following sections describe guidelines for each of these elements.

## Function name

- The name of the test case function should begin with a `test_` prefix.
- The name should be consise and meaningful in terms of what the test case
  actually does.

## Docstring

Each test case should contain yaml docstring in the following format:
```python
def test_example():
    """
    title: A brief test title
    description: |
      A more detailed test description.
      This is second line of the test description.
    pass_criteria:
      - The first pass criterium
      - The second pass criterium
      - The third pass criterium
    """
```

## Pytest marks

Test cases can use both standard pytest marks like `@pytest.mark.parametrize`
as well as marks introduced by the Test Framework like
`@pytest.mark.require_disk`.

Please refer to the Test Framework documentation (coming soon).

## Testing code

### Code structure

- A typical test case comprises three basic elements: preparation, testing
  logic, and cleanup.
- The Test Framework allows to define test steps, step groups and iterations.
- Every single line of test code must belong to some test step.
- Test steps may be embedded into test step groups and iterations.
- Step groups may be embedded into other step groups and iterations.
- Iterations may be embedded into step groups and other iterations.
- Neither test steps nor step groups nor iterations may be embedded into
  test steps. In other words, test steps must be the deepest elements in
  the test structure and they may contain only the testing code.

### Test implementation

- Avoid using `TestRun.executor` directly. It's very likely that the Test
  Framework or CAS API already has the functionality you need. If not, then
  you should prefer adding this functionality to the Test Framework/CAS API
  over running commands directly using `TestRun.executor.run()` from the test
  code.
- Avoid using `assert`. Use `if ... TestRun.fail()` pattern instead, as it
  allows pytest to handle test state properly.

Please refer to examples.
