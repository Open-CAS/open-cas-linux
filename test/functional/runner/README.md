## Installation

You just need to install required python packages running `pip3 install -r
requirements.txt` and set following environment variables in `~/.bashrc`:
```
export RUNNER_PATH=<path to superrunner directory>
export PATH="$PATH:$RUNNER_PATH/bin/"
```

## Setup

1. To start new validation scope create empty directory and inside this
directory run `jogger init`.
2. Fill `configs/duts_config.yml` with your DUT configuration.
3. Edit `configs/scope_config.yml`. Set path to OCL tests directory
and provide list of tests to be included in scope.
4. Start runner daemon by running `runnerd`.
5. At this point you should be able to run selected tests and check scope
progress using `jogger` utility.

## Usage

See `jogger --help`.
