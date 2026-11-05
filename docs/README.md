Longer notes per tool go here as they are written. For now the tool docstrings and the top-level README are the reference.

Known gotchas collected so far:
- Goose Desktop in external-server mode: edits of Signal messages do not render in Note to Self; the bridge uses reactions for progress instead.
- Goose only passes `envs` from config.yaml unreliably to stdio extensions; the launcher sources `.env` itself.
- Playwright MCP resolves relative output filenames against the client's root, hence the extra mount in start-browser.sh.
- Docling's CPU image bundles its models; mounting a cache over /opt/app-root/src/.cache hides them.
- A signal-cli-rest-api link only completes in MODE=normal; switch back to json-rpc afterwards.
- The lab REPL must be single-threaded: SIGALRM-based timeouts need the main thread.
