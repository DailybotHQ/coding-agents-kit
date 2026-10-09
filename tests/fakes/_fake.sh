# shellcheck shell=sh
# Shared body of every fake CLI in tests/fakes/. Sourced by the per-CLI entry
# points (claude, codex, agent, opencode, pi, cline, grok); never run directly.
#
# A fake never talks to a network and never reads a credential. It reports
# what it received so the suite can assert the exact argv and environment:
#
#   default            prints a record on stdout (CLI=, CWD=, knob variables,
#                      ARGC=, one ARG= line per argument, ARGV=)
#   FAKE_LOG=<file>    also appends the record to <file> (several calls)
#   FAKE_MODE=headless prints CLI-shaped output instead of the record:
#                      the CLI's JSON shape when its JSON flag is present,
#                      else FAKE_RESULT as plain text
#   FAKE_RESULT        the answer text (default "fake answer")
#   FAKE_IS_ERROR=1    the JSON output reports an error
#   FAKE_EXIT=<n>      exit status (default 0)
#   FAKE_SLEEP=<s>     sleep before answering (timeouts, cancellation)
#   FAKE_CHILD_PID=<f> start a grandchild `sleep`, write its pid to <f>
#   FAKE_STDERR=<text> written to stderr (the CLI's transcript)
#   FAKE_SHOW_SECRETS=1 print secret-carrying variables' values (key-routing
#                      tests only; the security scope never sets it)
#   FAKE_CLINE_HISTORY=<file> what `cline history --json` prints

fake_name="$(basename "$0")"

# --- side commands the kit calls before launching ------------------------
case "${fake_name}:${1:-}" in
  agent:--version) echo "2026.09.15-fake"; exit 0 ;;
  agent:--help) echo "Cursor Agent (fake) - start the Cursor agent"; exit 0 ;;
  *:--version) echo "${fake_name} 0.0.0-fake"; exit 0 ;;
  cline:history)
    if [ "${2:-}" = "--json" ]; then
      if [ -n "${FAKE_CLINE_HISTORY:-}" ] && [ -f "${FAKE_CLINE_HISTORY}" ]; then
        cat "${FAKE_CLINE_HISTORY}"
      else
        echo '[]'
      fi
      exit 0
    fi
    ;;
esac

fake_record() {
  echo "CLI=${fake_name}"
  echo "CWD=$(pwd)"
  for var in HOME CLAUDE_CONFIG_DIR CODEX_HOME AGENT_CLI_CREDENTIAL_STORE CURSOR_CONFIG_DIR \
      XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME PI_CODING_AGENT_DIR \
      CLINE_DIR GROK_HOME ANTHROPIC_BASE_URL API_TIMEOUT_MS ANTHROPIC_DEFAULT_OPUS_MODEL \
      ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL AGENTKIT_ACTIVE_PROFILE \
      AGENTKIT_PERMISSIONS; do
    eval "val=\${${var}:-}"
    echo "${var}=${val}"
  done
  for var in ANTHROPIC_AUTH_TOKEN ZAI_CODING_API_KEY ZHIPU_API_KEY ZAI_API_KEY XAI_API_KEY \
      AZURE_OPENAI_API_KEY; do
    eval "val=\${${var}:-}"
    if [ "${FAKE_SHOW_SECRETS:-}" = 1 ]; then
      echo "${var}=${val}"
    elif [ -n "${val}" ]; then
      echo "${var}=(set)"
    else
      echo "${var}="
    fi
  done
  echo "ARGC=$#"
  for arg in "$@"; do
    echo "ARG=${arg}"
  done
  echo "ARGV=$*"
}

if [ -n "${FAKE_LOG:-}" ]; then
  fake_record "$@" >> "${FAKE_LOG}"
  echo "---" >> "${FAKE_LOG}"
fi

if [ -n "${FAKE_STDERR:-}" ]; then
  echo "${FAKE_STDERR}" >&2
fi

if [ -n "${FAKE_CHILD_PID:-}" ]; then
  sleep 300 &
  echo "$!" > "${FAKE_CHILD_PID}"
fi

if [ -n "${FAKE_SLEEP:-}" ]; then
  sleep "${FAKE_SLEEP}"
fi

fake_has() {
  want="$1"
  shift
  for arg in "$@"; do
    [ "${arg}" = "${want}" ] && return 0
  done
  return 1
}

fake_json_text() {
  # JSON string body for FAKE_RESULT (quotes and backslashes escaped).
  printf '%s' "${FAKE_RESULT:-fake answer}" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

if [ "${FAKE_MODE:-}" = headless ]; then
  text="$(fake_json_text)"
  err=false
  [ "${FAKE_IS_ERROR:-}" = 1 ] && err=true
  case "${fake_name}" in
    claude|agent)
      if fake_has json "$@"; then
        printf '{"type":"result","subtype":"success","is_error":%s,"result":"%s","session_id":"fake-session"}\n' "${err}" "${text}"
      else
        printf '%s\n' "${FAKE_RESULT:-fake answer}"
      fi
      ;;
    codex)
      if fake_has --json "$@"; then
        printf '{"type":"thread.started","thread_id":"fake-thread"}\n'
        printf '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"%s"}}\n' "${text}"
        if [ "${err}" = true ]; then
          printf '{"type":"turn.failed","error":{"message":"fake failure"}}\n'
        else
          printf '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        fi
      else
        printf '%s\n' "${FAKE_RESULT:-fake answer}"
      fi
      ;;
    opencode)
      if fake_has json "$@"; then
        printf '{"type":"step_start","part":{"type":"step-start"}}\n'
        printf '{"type":"text","part":{"type":"text","text":"%s"}}\n' "${text}"
        [ "${err}" = true ] && printf '{"type":"error","error":{"message":"fake failure"}}\n'
      else
        printf '%s\n' "${FAKE_RESULT:-fake answer}"
      fi
      ;;
    pi)
      if fake_has json "$@"; then
        printf '{"type":"agent_start"}\n'
        printf '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"%s"}]}}\n' "${text}"
        printf '{"type":"agent_end"}\n'
      else
        printf '%s\n' "${FAKE_RESULT:-fake answer}"
      fi
      ;;
    cline)
      if fake_has --json "$@"; then
        printf '{"type":"say","say":"text","text":"working"}\n'
        printf '{"type":"say","say":"completion_result","text":"%s"}\n' "${text}"
      else
        printf '%s\n' "${FAKE_RESULT:-fake answer}"
      fi
      ;;
    grok)
      if fake_has json "$@"; then
        printf '{"type":"result","is_error":%s,"result":"%s"}\n' "${err}" "${text}"
      else
        printf '%s\n' "${FAKE_RESULT:-fake answer}"
      fi
      ;;
  esac
else
  fake_record "$@"
fi

exit "${FAKE_EXIT:-0}"
