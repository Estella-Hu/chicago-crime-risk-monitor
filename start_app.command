#!/bin/zsh
cd "$HOME/Desktop/Final Version" || exit 1
source ".venv/bin/activate"
python -m streamlit run app.py --server.port 8501 &
sleep 4
open "http://localhost:8501"
wait
