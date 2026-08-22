osascript -e 'quit app "Ollama"'

export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_CONTEXT_LENGTH=262144
export OLLAMA_ARG_CACHE_RAM=-1
export OLLAMA_MLX=1

ollama serve
