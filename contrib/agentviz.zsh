# Open agentviz when a terminal AI starts. Add commands to this array before
# sourcing the file to extend the list for local tools.
if (( ${#AGENTVIZ_AI_COMMANDS[@]} == 0 )); then
  typeset -ga AGENTVIZ_AI_COMMANDS=(
    codex claude aider gemini opencode cursor-agent amp pi goose qwen-code
  )
fi

typeset -g AGENTVIZ_ROOT="${${(%):-%x}:A:h:h}"

_agentviz_ai_preexec() {
  local line="$1" word command_name="" wrapper="" skip_next=0
  local -a words
  words=( ${(z)line} )

  for word in "${words[@]}"; do
    if (( skip_next )); then
      skip_next=0
      continue
    fi
    case "$word" in
      command|builtin|noglob|nocorrect) continue ;;
      [A-Za-z_][A-Za-z0-9_]*=*) continue ;;
      env|sudo) wrapper="$word"; continue ;;
      -u|-g|-h|-p|-C|-T|-R|-t)
        [[ -n "$wrapper" ]] && skip_next=1
        continue
        ;;
      -*)
        [[ -n "$wrapper" ]] && continue
        command_name="${word:t}"
        break
        ;;
      *) command_name="${word:t}"; break ;;
    esac
  done

  (( ${AGENTVIZ_AI_COMMANDS[(Ie)$command_name]} )) || return 0
  command bash "$AGENTVIZ_ROOT/hooks/launch.sh" >/dev/null 2>&1 &!
}

autoload -Uz add-zsh-hook
add-zsh-hook -d preexec _agentviz_ai_preexec 2>/dev/null
add-zsh-hook preexec _agentviz_ai_preexec
