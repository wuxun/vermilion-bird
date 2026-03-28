Task: Implement _execute_llm_chat in TaskExecutor to support model selection and model_params, and log execution history.

- Key changes:
  - Extract message, history, and optional model from Task.params
  - Pass model to LLM client if provided
  - Merge model_params for temperature and max_tokens into the chat request
  - Do not pass model when it is not specified to avoid unnecessary kwargs
  - Ensure execution history is saved via Storage as part of TaskExecution save in execute()

- Rationale:
  - Enables per-task model switching and fine-tuning per call
  - Keeps backward compatibility for tasks without explicit model
  - Maintains existing backoff/retry logic and storage integration

- Verification notes:
  - Run tests: pytest -k llm_chat -v to confirm behavior
  - Specifically check that when task.params include {"model": "gpt-4"}, the chat call receives model="gpt-4"; when model_params present, temperature and max_tokens are passed accordingly.
