#!/bin/zsh
# Double-click to start the stock screener and open it in the browser.
# Closing this Terminal window (or Ctrl+C) stops it.

cd "${0:A:h}" || exit 1

if [[ ! -x .venv/bin/screener ]]; then
  echo "The Python environment is missing. In this folder, run: uv sync"
  read -k 1 "?Press any key to close."
  exit 1
fi

.venv/bin/screener serve
status=$?
if (( status != 0 )); then
  read -k 1 "?The screener stopped with an error (see above). Press any key to close."
fi
exit $status
